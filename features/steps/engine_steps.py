from __future__ import annotations

import array
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from features.support.tool_replay import tool_patch
from agavai.harness import Harness

from behave import given, when, then

from agavai.config import Config, LlmConfig, load_config
from agavai.llm import LlmError
from agavai.meter import AcousticResult, Endpointer
from agavai.harness.engine import run_turn
from agavai.speech_backends import WhistleBackend


def directory(context):
    tmp = tempfile.TemporaryDirectory()
    context.add_cleanup(tmp.cleanup)
    return Path(tmp.name)


@given('an engine config selecting Whistle and Needle')
def engine_config(context):
    context.engine_path = directory(context) / 'config.toml'
    context.engine_path.write_text('''[asr]
backend = "whistle-cactus"
endpoint = "manual"
venv = "/speech"
model_path = "/whistle.cact"
runtime_library = "/libneedle.so"
[brain.small]
backend = "needle-cactus"
model_path = "/needle.cact"
venv = "/brain"
[brain.large]
backend = "llama-server"
model_path = "/qwen.gguf"
port = 19000
''')


@given('an engine config with "{setting}"')
def invalid_config(context, setting):
    context.engine_path = directory(context) / 'config.toml'
    variants = {
        'unknown speech': '[asr]\nbackend="unknown"',
        'whistle native': '[asr]\nbackend="whistle-cactus"',
        'whistle gpu': '[asr]\nbackend="whistle-cactus"\nendpoint="manual"\ndevice="gpu"',
        'whistle language': '[asr]\nbackend="whistle-cactus"\nendpoint="manual"\nlanguage="english"',
        'zero deadline': '[asr]\nfinish_timeout_secs=0',
        'vad disabled': '[asr]\nbackend="whistle-cactus"\nendpoint="vad"\n[vad]\nenabled=false',
        'vad backend': '[asr]\nbackend="whistle-cactus"\nendpoint="vad"\n[vad]\nbackend="webrtc"',
        'vad frame': '[asr]\nbackend="whistle-cactus"\nendpoint="vad"\n[vad]\nframe_ms=40',
        'vad zero silence': '[asr]\nbackend="whistle-cactus"\nendpoint="vad"\n[vad]\nsilence_ms=0',
        'unknown brain': '[brain.small]\nbackend="unknown"\nmodel_path="/m"',
        'missing brain model': '[brain.small]\nbackend="needle-cactus"',
        'unknown tool selection': '[brain.small]\nmodel="qwen3-4b-instruct"\ntool_selection="guess"',
        'unknown router': '[router]\nbackend="guess"',
        'zero tool budget': '[router]\nmax_tools=0',
        'missing router model': '[router]\nbackend="needle-cactus"',
        'router model path missing': '[router]\nbackend="needle-cactus"\n[router.needle]\nmax_tokens=64',
        'zero router tokens': '[router]\nbackend="needle-cactus"\n[router.needle]\nmodel_path="/needle.cact"\nmax_tokens=0',
        'cloud deferred': '[brain.cloud]\nbackend="openai-compatible"',
    }
    context.engine_path.write_text(variants[setting])


@when('I load the engine config')
def load_engine(context):
    context.engine_error = None
    try:
        context.engines = load_config(context.engine_path)
    except ValueError as exc:
        context.engine_error = str(exc)


@then('the selected engines and independent environments are preserved')
def config_selected(context):
    c = context.engines
    assert c.asr.backend == 'whistle-cactus' and c.asr.endpoint == 'manual' and c.asr.language == 'en'
    assert str(c.asr.venv) == '/speech'
    assert c.small_brain.backend == 'needle-cactus' and str(c.small_brain.venv) == '/brain'
    assert c.large_brain.port == 19000
    assert c.tts.venv != c.asr.venv


@then('engine configuration fails with "{message}"')
def bad_config(context, message):
    assert message.lower() in (context.engine_error or '').lower(), context.engine_error


@when('I select catalog models for the agent and fallback')
def role_catalog(context):
    path = directory(context) / 'config.toml'
    path.write_text('''[llm.models.test-agent]
path = "/test-agent.gguf"
ctx_size = 4096
n_gpu_layers = 3
[brain.small]
model = "test-agent"
tool_selection = "all"
port = 18767
ctx_size = 2048
[brain.large]
model = "qwen3-4b-instruct"
''')
    context.engines = load_config(path)


@then('both local models resolve with their own tool policy and runtime limits')
def role_catalog_result(context):
    small, large = context.engines.small_brain, context.engines.large_brain
    assert small.model_path == Path('/test-agent.gguf') and small.ctx_size == 2048 and small.n_gpu_layers == 3
    assert small.tool_selection == 'all' and small.port == 18767
    assert large.model_path.name == 'Qwen3-4B-Instruct-2507-Q4_K_M.gguf' and large.ctx_size == 8192
    assert large.tool_selection == 'routed' and large.port == 18766
    assert small.active_spec().id == 'test-agent' and large.active_spec().id == 'qwen3-4b-instruct'


class FakeWhistle:
    def __init__(self, **_):
        self.cancelled = 0
        self.languages = []

    def stream(self, chunks, language):
        self.languages.append(language)
        try:
            for chunk in chunks:
                assert isinstance(chunk, array.array) and chunk.typecode == 'f'
                yield {'text': 'word', 'pending': 'pending'}
        except GeneratorExit:
            self.cancelled += 1
            raise
        yield {'text': 'tail', 'pending': ''}

    def transcribe(self, samples, language):
        assert len(samples) == 33600
        self.languages.append(language)
        return {'text': 'word word word tail'}


def whistle(context, mode, language='en'):
    context.partials = []
    cfg = SimpleNamespace(mode=mode, chunk_ms=1000, model_path='fixture', runtime_library='fixture', language=language)
    with patch.dict(sys.modules, needle=SimpleNamespace(Whistle=FakeWhistle)), patch("agavai.cactus_runtime.prepare"):
        return WhistleBackend(cfg, lambda kind, text: context.partials.append((kind, text)))


@when('a "{mode}" Whistle adapter receives two chunks and a short tail')
def feed_whistle(context, mode):
    backend = whistle(context, mode)
    for packet in (bytes(11000), bytes(29000), bytes(27200)):
        backend.feed(packet)
    context.final_text = backend.finish()


@when('a "{mode}" Whistle adapter set to "{language}" transcribes speech')
def whistle_language(context, mode, language):
    context.whistle = whistle(context, mode, language)
    for packet in (bytes(11000), bytes(29000), bytes(27200)):
        context.whistle.feed(packet)
    context.whistle.finish()


@then('Whistle was asked to transcribe "{language}"')
def whistle_asked(context, language):
    expected = None if language == 'detected' else language
    assert context.whistle.model.languages == [expected], context.whistle.model.languages


@then('the final speech text contains the tail exactly once')
def tail_once(context):
    assert context.final_text == 'word word word tail', context.final_text


@then('"{mode}" partial behavior is respected')
def partials(context, mode):
    assert bool(context.partials) == (mode == 'streaming')
    if context.partials:
        assert context.partials[-1][1] == context.final_text


@when('I cancel Whistle after a partial and start another utterance')
def cancel_whistle(context):
    backend = whistle(context, 'streaming')
    backend.feed(bytes(32000))
    backend.cancel()
    assert backend.model.cancelled == 1
    backend.start()
    backend.feed(bytes(2000))
    context.final_text = backend.finish()


@then('only the second utterance is finalized')
def second_only(context):
    assert context.final_text == 'word tail', context.final_text


WORKER = '''
import json, struct, sys
print(json.dumps({'kind':'ready','protocol':1,'native_endpoint':False}), flush=True)
audio_bytes = 0
while header := sys.stdin.buffer.read(4):
    frame = sys.stdin.buffer.read(struct.unpack('>I', header)[0])
    kind, uid = struct.unpack('>cI', frame[:5])
    if kind == b'A':
        audio_bytes += len(frame[5:])
    elif kind == b'F':
        open(sys.argv[1], 'w').write(str(audio_bytes))
        if sys.argv[2] != 'timeout':
            print(json.dumps({'kind':'final','utterance_id':uid,'text':'open the browser'}), flush=True)
    elif kind == b'C':
        print(json.dumps({'kind':'cancelled','utterance_id':uid}), flush=True)
'''
CAPTURE = '''
import sys,time
if len(sys.argv) > 1:
    with open(sys.argv[1], 'rb') as audio:
        while chunk := audio.read(137):
            sys.stdout.buffer.write(chunk); sys.stdout.buffer.flush(); time.sleep(.001)
    sys.exit(0)
while True:
    sys.stdout.buffer.write(bytes(640)); sys.stdout.buffer.flush(); time.sleep(.02)
'''


def worker_session(context, mode, *, endpoint='manual', pcm=None):
    from agavai.harness.session import listen_session, _cancel_path
    cfg = context.cfg
    cfg.asr.backend = 'whistle-cactus'
    cfg.asr.endpoint = endpoint
    cfg.asr.mode = 'batch' if mode == 'cancel' or mode.startswith('batch_finish') else 'streaming'
    cfg.asr.model_path = context.runtime_dir / 'whistle.cact'
    cfg.asr.runtime_library = context.runtime_dir / 'libneedle.so'
    cfg.asr.model_path.touch()
    cfg.asr.runtime_library.touch()
    cfg.asr.venv = Path(sys.executable).resolve().parents[1]
    cfg.asr.finish_timeout_secs = .2
    cfg.asr.max_utterance_secs = 5
    audio = context.runtime_dir / 'endpoint.pcm'
    if pcm is not None:
        audio.write_bytes(pcm)
    marker = context.runtime_dir / 'finished'
    spawn = subprocess.Popen
    context.capture_count = 0
    def popen(argv, **kwargs):
        if argv[0] == 'parec':
            context.capture_count += 1
            return spawn([sys.executable, '-c', CAPTURE, *([str(audio)] if pcm is not None else [])], **kwargs)
        return spawn([sys.executable, '-c', WORKER, str(marker), mode], **kwargs)
    stopped = False
    def level(*_):
        nonlocal stopped
        if mode == 'short_noise' and context.capture_count == 1:
            return
        if mode not in {'finish', 'timeout', 'cancel', 'batch_finish', 'short_noise'}:
            return
        if not stopped:
            stopped = True
            if mode in {'cancel', 'short_noise'}:
                _cancel_path(cfg).touch()
            os.kill(os.getpid(), signal.SIGTERM)
    def submitted(*args, **kwargs):
        from agavai.ui import cancel_ui
        cancel_ui(cfg)
        return 'Browser opened.'
    with patch('agavai.asr.subprocess.Popen', side_effect=popen), patch('agavai.asr.shutil.which', return_value='parec'), patch.object(context.ui, 'level', side_effect=level), patch('agavai.harness.session._run_stop_body', side_effect=submitted) as submit, patch('agavai.harness.session.prepare_listen'), patch('agavai.harness.session.cue_listen'), patch('agavai.harness.session.finish'), patch('agavai.harness.session._publish_pid'), patch('agavai.tts.sweep_playback_wavs'):
        listen_session(cfg, harness=Harness(cfg, on_event=context.ui.on_harness_event, should_cancel=context.ui.cancelled))
        context.submit_count = submit.call_count
        context.submit_calls = submit.call_args_list
        if submit.called:
            context.submitted_line = submit.call_args.kwargs['text']
    context.did_finalize = marker.exists()
    context.finalized_bytes = int(marker.read_text()) if marker.exists() else 0


@when('Whistle "{mode}" hears speech with a short pause then trailing silence')
def automatic_whistle(context, mode):
    context.cfg.vad.silence_ms = 900
    context.cfg.vad.max_record_ms = 120000
    speech = struct.pack('<h', 8192) * 6400
    pcm = bytes(6000 * 32) + speech + bytes(700 * 32) + speech + bytes(1400 * 32)
    worker_session(context, 'batch_finish_auto' if mode == 'batch' else 'auto', endpoint='vad', pcm=pcm)
    context.expected_endpoint_bytes = (6000 + 400 + 700 + 400 + 900) * 32


@then('only the long trailing pause finishes recognition')
def automatic_endpoint(context):
    assert context.finalized_bytes == context.expected_endpoint_bytes, context.finalized_bytes
    assert context.ui.data['asr_endpoint'] == 'vad'


@when('Whistle with "{endpoint}" endpointing hears "{sound}" without Enter')
def no_automatic_turn(context, endpoint, sound):
    pcm = bytes(6000 * 32)
    if sound == 'speech and silence':
        pcm = struct.pack('<h', 8192) * 6400 + bytes(1000 * 32)
    worker_session(context, 'auto', endpoint=endpoint, pcm=pcm)


@when('I cancel Whistle with VAD before its trailing pause')
def cancel_vad(context):
    worker_session(context, 'cancel', endpoint='vad')


@when('Whistle hears a brief noise with VAD before I cancel')
def short_noise(context):
    pcm = struct.pack('<h', 8192) * 1600 + bytes(1200 * 32)
    worker_session(context, 'short_noise', endpoint='vad', pcm=pcm)
    assert context.capture_count == 2, context.capture_count


@when('Whistle with VAD exceeds its configured speech duration')
def long_speech(context):
    context.cfg.vad.max_record_ms = 500
    worker_session(context, 'auto', endpoint='vad', pcm=struct.pack('<h', 8192) * 16000)


class UnresponsiveClassifier:
    def feed(self, frame):
        return AcousticResult("non_speech", backend_failed="infer")

    def reset(self):
        pass

    def close(self):
        pass


@when('the VAD classifier stops responding while Whistle listens')
def unresponsive_vad(context):
    endpointer = Endpointer(context.cfg.vad, backend=UnresponsiveClassifier())
    with patch('agavai.asr.streaming_endpointer', return_value=endpointer):
        worker_session(context, 'auto', endpoint='vad', pcm=struct.pack('<h', 8192) * 16000)


@when('Enter finishes Whistle while VAD is enabled')
def enter_vad(context):
    worker_session(context, 'finish', endpoint='vad')


@when('Enter finishes a real worker with a pending speech tail')
def enter(context):
    worker_session(context, 'finish')


@when('Escape cancels a real batch worker')
def escape(context):
    worker_session(context, 'cancel')


@when('Enter finishes an unresponsive speech worker')
def timeout(context):
    worker_session(context, 'timeout')


@then('batch recognition was not finalized')
def not_finalized(context):
    assert not context.did_finalize


BROWSER = {'content': '', 'tool_calls': [{'id':'browser', 'function': {'name':'launch', 'arguments':'{"target":"browser"}'}}]}


def brain_turn(context, small_responses, *, tool_only=False, larger=True, large_responses=None, text='open the browser', small_selection='routed', large_selection='routed'):
    cfg = context.cfg
    cfg.router.backend = 'keyword'
    cfg.small_brain = LlmConfig(backend='needle-cactus' if tool_only else 'llama-server', model_id='small', tool_selection=small_selection)
    cfg.large_brain = LlmConfig(model_id='large', tool_selection=large_selection) if larger else None
    small = Mock(tool_only=tool_only)
    small.ready.return_value = True
    small.respond.side_effect = small_responses
    large = Mock(tool_only=False)
    large.ready.return_value = True
    large.respond.side_effect = large_responses or [{'content':'Larger answer.'}]
    context.engine_requests = []
    context.engine_tools = []
    def factory(spec, **_):
        return small if spec.model_id == 'small' else large
    def record(messages, tools):
        context.engine_requests.append(deepcopy(messages))
        context.engine_tools.append(deepcopy(tools))
        item = next(large_script)
        if isinstance(item, Exception):
            raise item
        return item
    large_script = iter(large_responses or [{'content':'Larger answer.'}])
    large.respond.side_effect = record
    with patch('agavai.harness.engine.create_brain', side_effect=factory), tool_patch('agavai.harness.engine.call_tool', return_value='Opened browser.') as tool:
        context.reply = run_turn(text, cfg, context.harness.output, context=context.harness.context)
    context.small_engine, context.large_engine = small, large
    context.executed_tools = tool.call_count


@when('the small engine handles a browser request')
def small_success(context):
    brain_turn(context, [BROWSER], tool_only=True)


@then('only the small engine and the browser tool run')
def only_small(context):
    context.small_engine.respond.assert_called_once()
    context.large_engine.ready.assert_not_called()
    context.large_engine.respond.assert_not_called()
    assert context.executed_tools == 1 and context.reply == 'Opened browser.'


@when('the small engine returns "{outcome}" for an unsupported request')
def unsupported(context, outcome):
    responses = {'empty': {'content':''}, 'unsupported': {'unsupported':'No tool'},
                 'runtime error': LlmError('native failure'),
                 'explicit escalation': {'tool_calls':[{'function': {'name':'escalate_to_larger_model','arguments':'{"reason":"unsupported"}'}}]}}
    brain_turn(context, [responses[outcome]])


@then('the larger engine answers with the same request history')
def larger_answer(context):
    context.small_engine.respond.assert_called_once()
    context.large_engine.respond.assert_called_once()
    assert context.reply == 'Larger answer.'
    assert any(m.get('content') == 'open the browser' for m in context.engine_requests[0])
    assert context.executed_tools == 0


@when('Needle cannot match "{text}" and a larger brain is configured')
def needle_fallback(context, text):
    context.fallback_request = text
    brain_turn(context, [{'unsupported':'No matching tool call'}], tool_only=True, text=text, small_selection='all')


@then('Needle offers the full allowlist and Qwen offers only "{schemas}" before answering')
def needle_fallback_answer(context, schemas):
    from agavai.tools import OPENAPI_TOOLS
    if context.fallback_request == 'What is the capital of France?':
        context.small_engine.respond.assert_not_called()
        assert context.reply == 'Larger answer.' and context.executed_tools == 0
        assert [item['function']['name'] for item in context.engine_tools[0]] == ['show_answer']
        return
    context.small_engine.respond.assert_called_once()
    messages, offered = context.small_engine.respond.call_args.args
    assert [item['function']['name'] for item in offered] == [item['function']['name'] for item in OPENAPI_TOOLS] + ['request_confirmation']
    assert [item['function']['name'] for item in context.engine_tools[0]] == ([] if schemas == 'none' else schemas.split(','))
    assert 'escalate_to_larger_model' not in messages[0]['content']
    context.large_engine.respond.assert_called_once()
    history = context.engine_requests[0]
    assert [m['content'] for m in history if m['role'] == 'user'] == [context.fallback_request]
    assert not any(m['role'] == 'tool' or m.get('tool_calls') for m in history)
    assert context.reply == 'Larger answer.' and context.executed_tools == 0


@when('the only brain engine returns an empty response')
def empty_only(context):
    brain_turn(context, [{'content':''}], larger=False)


@then('the reply does not claim completion')
def failure_not_success(context):
    assert 'could not handle' in context.reply and context.reply != 'Done.'


@when('Needle cannot match "{text}" and no larger brain is configured')
def needle_no_match(context, text):
    brain_turn(context, [{'unsupported':'No matching tool call'}], tool_only=True, larger=False, text=text)


@then('the reply explains the limitation and suggests a desktop request')
def useful_unsupported(context):
    assert context.reply == 'I could not handle that request. Try asking me to open an app or find a file.'
    assert context.executed_tools == 0
    assert context.ui.data['error'] == context.reply
    context.large_engine.respond.assert_not_called()


@when('I replay recorded speech and silence through the installed "{mode}" Whistle listener')
def native_vad(context, mode):
    import wave
    from agavai.asr import StreamingRecognizer
    root = installed_cactus()
    cfg = Config()
    cfg.asr.backend, cfg.asr.endpoint, cfg.asr.mode = 'whistle-cactus', 'vad', mode
    cfg.asr.model_path, cfg.asr.runtime_library, cfg.asr.venv = root/'whistle.cact', root/'libneedle.so', root/'venv'
    cfg.asr.max_utterance_secs = 15
    cfg.vad.max_record_ms = 15000
    with wave.open(str(Path(__file__).resolve().parents[1]/'fixtures/asr-sentence.wav')) as audio:
        pcm = audio.readframes(audio.getnframes()) + bytes(1500 * 32)
    capture = directory(context) / 'recorded.pcm'
    capture.write_bytes(pcm)
    spawn = subprocess.Popen
    def popen(argv, **kwargs):
        if argv[0] == 'parec':
            return spawn([sys.executable, '-c', CAPTURE, str(capture)], **kwargs)
        return spawn(argv, **kwargs)
    with patch('agavai.asr.subprocess.Popen', side_effect=popen):
        stream = StreamingRecognizer(cfg)
        try:
            context.endpoint_events = list(stream.events(lambda _: None))
        finally:
            stream.close()
    from evals.voice import recognize
    wav_path = capture.with_suffix('.wav')
    with wave.open(str(wav_path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(pcm)
    context.endpoint_replay = recognize(cfg, [{'id':'fixture', 'path':str(wav_path)}])


@then('one final transcript includes the full recorded request without Enter')
def native_vad_final(context):
    finals = [text for kind, text in context.endpoint_events if kind == 'eou']
    assert len(finals) == 1, context.endpoint_events
    assert 'meeting notes' in finals[0].lower() and 'open the document' in finals[0].lower(), finals
    commits = context.endpoint_replay['clips'][0]['commits']
    assert len(commits) == 1 and commits[0]['text'] == finals[0], commits


@when('the small engine launches the browser then escalates')
def after_tool(context):
    brain_turn(context, [BROWSER, {'content':''}], large_responses=[BROWSER, {'content':'Already opened.'}], small_selection='all')


@then('the browser is launched once despite the larger engine repeating its call')
def once_only(context):
    assert context.executed_tools == 1
    assert any(m['role'] == 'tool' for m in context.engine_requests[0])
    assert context.reply == 'Already opened.'


@when('the small engine requests a browser launch without required arguments')
def bad_args(context):
    malformed = deepcopy(BROWSER)
    malformed['tool_calls'][0]['function']['arguments'] = '{}'
    brain_turn(context, [malformed], tool_only=True, small_selection='all')


@then('no desktop tool is executed')
def no_tool(context):
    assert context.executed_tools == 0
    assert 'Missing required' in context.reply


@when('Needle reports an ungrounded date in a tool argument')
def ungrounded(context):
    from agavai.needle_worker import normalize
    context.needle_result = normalize({'type':'call', 'function_calls':[{'name':'reminder','arguments':{'date':'2099'}}], 'validation':{'ungrounded':['reminder.date']}})


@then('the Needle response is unsupported')
def unsupported_needle(context):
    assert context.needle_result.get('unsupported')


def installed_cactus():
    value = os.environ.get('AGAVAI_CACTUS_TEST_DIR')
    if not value:
        raise AssertionError('Set AGAVAI_CACTUS_TEST_DIR to the directory provisioned by scripts/setup-cactus.sh')
    return Path(value).resolve()


@when('I replay the speech fixture through the installed "{mode}" Whistle worker')
def native_speech(context, mode):
    import time
    import wave
    from agavai.asr import worker_settings
    from agavai.worker import WorkerProcess
    root = installed_cactus()
    cfg = Config().asr
    cfg.backend, cfg.endpoint, cfg.mode = 'whistle-cactus', 'manual', mode
    cfg.model_path, cfg.runtime_library, cfg.venv = root/'whistle.cact', root/'libneedle.so', root/'venv'
    worker = WorkerProcess([str(cfg.venv/'bin/python'), str(Path(__file__).resolve().parents[2]/'src/agavai/asr_worker.py'), json.dumps(worker_settings(cfg))])
    with wave.open(str(Path(__file__).resolve().parents[1]/'fixtures/asr-sentence.wav')) as audio:
        pcm = audio.readframes(audio.getnframes())
    def send(kind, uid, data=b''):
        worker.send(struct.pack('>cI', kind, uid) + data)
    def terminal(kind, uid):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            event = worker.receive(.1)
            if event and event.get('kind') == kind:
                assert event['utterance_id'] == uid, event
                return event
        raise AssertionError('Native worker timed out')
    context.native_transcripts = []
    try:
        assert worker.receive(20)['kind'] == 'ready'
        send(b'S', 1)
        send(b'A', 1, pcm[:32000])
        send(b'C', 1)
        terminal('cancelled', 1)
        for uid in [2, 3]:
            send(b'S', uid)
            for at in range(0, len(pcm), 3200):
                send(b'A', uid, pcm[at:at+3200])
            send(b'F', uid)
            context.native_transcripts.append(terminal('final', uid)['text'])
    finally:
        worker.close()


@then('both finalized transcripts contain the meeting notes and document request')
def native_transcripts(context):
    assert len(context.native_transcripts) == 2
    for text in context.native_transcripts:
        assert 'meeting notes' in text.lower() and 'open the document' in text.lower(), text
    assert context.native_transcripts[0] == context.native_transcripts[1], context.native_transcripts


@when('I ask the installed Needle engine to open a browser and explain physics')
def native_brain(context):
    from agavai.brain import create_brain, close_brains
    from agavai.heads import schemas_for_heads
    root = installed_cactus()
    cfg = LlmConfig(backend='needle-cactus', venv=root/'venv', model_path=root/'needle3.cact', runtime_library=root/'libneedle.so', timeout_secs=20)
    try:
        brain = create_brain(cfg, chat=None, health=None)
        def respond(text):
            return brain.respond([{'role':'system','content':'Choose the matching tool. Do not invent arguments.'}, {'role':'user','content':text}], schemas_for_heads(['launch'], limit=8))
        context.native_call = respond('open the browser')
        context.native_unsupported = respond('explain quantum mechanics')
    finally:
        close_brains()


@then('the native tool call targets the browser and the explanation escalates')
def native_call(context):
    fn = context.native_call['tool_calls'][0]['function']
    assert fn['name'] == 'launch' and json.loads(fn['arguments']) == {'target':'browser'}, fn
    assert context.native_unsupported.get('unsupported')


@when('I inspect the llama launcher for role "{role}"')
def launcher(context, role):
    from agavai.config import dump_llm_env
    context.launcher = dump_llm_env(load_config(context.engine_path), role)


@then('the launcher contains "{setting}"')
def launcher_setting(context, setting):
    assert setting in context.launcher, context.launcher


@when('both configured brain engines fail')
def both_fail(context):
    brain_turn(context, [LlmError('small failure')], large_responses=[LlmError('larger failure')])


@then('each brain was attempted once and the failure is visible')
def bounded_failure(context):
    context.small_engine.respond.assert_called_once()
    context.large_engine.respond.assert_called_once()
    assert context.reply == 'larger failure' and context.executed_tools == 0


@when('Enter finalizes a real batch speech worker')
def batch_enter(context):
    context.finalizing_phases = []
    original = context.ui.transcribing
    def transcribing():
        original()
        context.finalizing_phases.append(context.ui.data['phase'])
    with patch.object(context.ui, 'transcribing', side_effect=transcribing):
        worker_session(context, 'batch_finish')


@then('the batch worker was finalized while the UI was transcribing')
def batch_phase(context):
    assert context.did_finalize and context.finalizing_phases == ['transcribing']


@when('I register and select an additional speech adapter')
def register_speech(context):
    from dataclasses import asdict
    from agavai.speech_backends import SPEECH_BACKENDS, create_backend
    from agavai.asr import worker_settings
    class Adapter:
        partials, native_endpoint = False, True
        def __init__(self, cfg, on_event):
            self.cfg = cfg
        @staticmethod
        def validate_selection(cfg):
            pass
        @staticmethod
        def settings(cfg):
            return asdict(cfg)
    path = directory(context) / 'config.toml'
    path.write_text('[asr]\nbackend="registered-speech"\n')
    with patch.dict(SPEECH_BACKENDS, {'registered-speech':Adapter}):
        cfg = load_config(path)
        context.registered_settings = worker_settings(cfg.asr)
        context.registered_speech = isinstance(create_backend(cfg.asr, None), Adapter)


@then('configuration and the speech factory use that adapter')
def registered_speech(context):
    assert context.registered_speech and context.registered_settings['backend'] == 'registered-speech'


@when('I register and select an additional brain adapter')
def register_brain(context):
    from agavai.brain import BRAIN_BACKENDS
    class Adapter:
        tool_only = False
        def __init__(self, cfg, chat, health):
            pass
        def ready(self):
            return True
        def respond(self, messages, tools):
            return {'content':'Registered engine answer.'}
    path = directory(context) / 'config.toml'
    path.write_text('[brain.small]\nbackend="registered-brain"\nmodel_path="/fixture"\n')
    with patch.dict(BRAIN_BACKENDS, {'registered-brain':Adapter}):
        cfg = load_config(path)
        cfg.router.backend = 'keyword'
        with patch('agavai.harness.engine.chat') as chat, patch('agavai.harness.engine.health') as health:
            context.reply = run_turn('hello', cfg, context.harness.output, context=context.harness.context)
            context.used_llama = chat.called or health.called


@then('its answer completes without invoking llama-server')
def registered_brain(context):
    assert context.reply == 'Registered engine answer.' and not context.used_llama


@when('I evaluate the browser task using the installed Needle engine')
def native_eval(context):
    evaluate_native_case(context, 'desktop.launch.browser', 'routed')


@when('I evaluate the volume task using full-tool Needle')
def native_all_eval(context):
    evaluate_native_case(context, 'desktop.volume.up', 'all')


def evaluate_native_case(context, case_id, selection):
    from agavai.brain import close_brains
    from evals.cases import load_cases
    from evals.runner import run_case
    root = installed_cactus()
    cfg = Config()
    cfg.router.backend = 'keyword'
    cfg.small_brain = LlmConfig(backend='needle-cactus', venv=root/'venv', model_path=root/'needle3.cact', runtime_library=root/'libneedle.so', timeout_secs=20, tool_selection=selection)
    try:
        case = next(case for case in load_cases() if case.id == case_id)
        context.native_evaluation = run_case(case, cfg, set())
    finally:
        close_brains()


@then('the simulated browser task succeeds and its model exchange is recorded')
def native_eval_record(context):
    result = context.native_evaluation
    assert result['outcome'] == 'done', result
    exchanges = result['turns'][0]['model']
    assert len(exchanges) == 1 and exchanges[0]['backend'] == 'needle-cactus', exchanges
    assert exchanges[0]['tool_calls'][0]['name'] == 'launch', exchanges


@then('the simulated volume increases with all tools offered and no routing')
def native_all_eval_record(context):
    from agavai.tools import OPENAPI_TOOLS
    result = context.native_evaluation
    assert result['outcome'] == 'done', result
    turn = result['turns'][0]
    assert turn['heads'] == [] and len(turn['model']) == 1, turn
    assert turn['model'][0]['offered'] == [t['function']['name'] for t in OPENAPI_TOOLS] + ['request_confirmation']
    assert turn['model'][0]['tool_calls'][0]['name'] == 'set_volume'


@when('the recognizer replaces a partial with an empty final transcript')
def empty_final(context):
    from agavai.harness.session import _await_utterance
    stream = Mock()
    stream.events.return_value = iter([('interim', 'open the browser'), ('eou', '')])
    with patch('agavai.harness.session.prepare_listen'), patch('agavai.harness.session.cue_listen'), patch('agavai.harness.session.finish'):
        outcome, text = _await_utterance(context.cfg, context.harness.output, stream, fresh=True,
                                        stop_requested=lambda:False, cancel_requested=lambda:False)
    assert outcome == 'ignore' and not text
    context.submit_count = 0


@when('I use "{speech}" with "{agent}" and "{policy}" tools through "{router}"')
def mixed_roles(context, speech, agent, policy, router):
    path = directory(context) / 'config.toml'
    endpoint = 'native' if speech == 'parakeet-onnx' else 'manual'
    path.write_text(f'''[asr]
backend = "{speech}"
endpoint = "{endpoint}"
[router]
backend = "{router}"
max_tools = 2
[brain.small]
backend = "{agent}"
model_path = "/fixture"
tool_selection = "{policy}"
''')
    cfg = load_config(path)
    full = policy == 'all' or router == 'none'
    call = {'tool_calls':[{'id':'agents','function':{'name':'list_agents','arguments':'{}'}}]} if full else BROWSER
    brain = Mock(tool_only=agent == 'needle-cactus')
    brain.ready.return_value = True
    context.mixed_offers = []
    def respond(messages, tools):
        context.mixed_offers.append(deepcopy(tools))
        return next(responses)
    responses = iter([call, {'content':'Finished.'}])
    brain.respond.side_effect = respond
    with patch('agavai.harness.engine.create_brain', return_value=brain), patch('agavai.harness.engine.select_head_ids', return_value=['launch']) as route, tool_patch('agavai.harness.engine.call_tool', return_value='Finished.') as tool:
        context.reply = run_turn('inspect local agents' if full else 'open the browser', cfg, context.harness.output, context=context.harness.context)
    context.mixed_route_calls = route.call_count
    context.mixed_tool_calls = tool.call_args_list
    assert cfg.asr.backend == speech and cfg.small_brain.backend == agent


@then('the agent uses "{scope}" schemas with "{routing:d}" router calls')
def mixed_roles_result(context, scope, routing):
    from agavai.tools import OPENAPI_TOOLS
    assert context.mixed_route_calls == routing
    expected = [t['function']['name'] for t in OPENAPI_TOOLS] if scope == 'all' else ['launch']
    for tools in context.mixed_offers:
        assert [t['function']['name'] for t in tools] == expected + ['request_confirmation']
        confirmation = tools[-1]['function']['parameters']['properties']['name']['enum']
        assert confirmation == expected
    assert len(context.mixed_tool_calls) == 1 and context.reply == 'Finished.'
    assert context.mixed_tool_calls[0].args[0] == ('list_agents' if scope == 'all' else 'launch')


@when('full-tool Needle proposes an agent listing for confirmation')
def all_tools_confirmation(context):
    context.cfg.router.max_tools = 1
    proposal = {'tool_calls':[{'id':'confirm','function':{'name':'request_confirmation','arguments':json.dumps({'name':'list_agents','arguments':{},'question':'List local agents?'})}}]}
    brain_turn(context, [proposal], tool_only=True, small_selection='all')


@then('no tool runs until Yes and the confirmed agent listing runs once')
def all_tools_confirmed(context):
    assert context.executed_tools == 0
    assert context.harness.context.pending_action.name == 'list_agents'
    with patch('agavai.harness.engine.create_brain') as brain, tool_patch('agavai.harness.engine.call_tool', return_value='Agents listed.') as tool:
        reply = run_turn('yes', context.cfg, context.harness.output, context=context.harness.context, continue_conversation=True)
    brain.assert_not_called()
    tool.assert_called_once_with('list_agents', '{}', context.cfg)
    assert reply == 'Agents listed.' and context.harness.context.pending_action is None


@when('a routed small agent fails with full-tool fallback configured')
def all_tools_fallback(context):
    brain_turn(context, [LlmError('small failed')], large_selection='all')


@then('the fallback receives the full allowlist and no further escalation tool')
def all_tools_fallback_result(context):
    from agavai.tools import OPENAPI_TOOLS
    assert [t['function']['name'] for t in context.engine_tools[0]] == [t['function']['name'] for t in OPENAPI_TOOLS] + ['request_confirmation']
    assert 'escalate_to_larger_model' not in context.engine_requests[0][0]['content']
    assert context.reply == 'Larger answer.' and context.executed_tools == 0


@when('full-tool Needle requests an unknown shell tool')
def unknown_all_tool(context):
    brain_turn(context, [{'tool_calls':[{'function':{'name':'shell','arguments':'{}'}}]}], tool_only=True, small_selection='all')


@then('the unknown tool is rejected without executing anything')
def unknown_all_tool_result(context):
    assert context.executed_tools == 0
    assert 'unavailable in this turn: shell' in context.reply


@when('I select Needle routing with "{speech}" and a "{policy}" "{agent_backend}" agent')
def needle_routed_agent(context, speech, policy, agent_backend):
    path = directory(context) / 'config.toml'
    path.write_text(f'''[asr]
backend = "{speech}"
endpoint = "{'native' if speech == 'parakeet-onnx' else 'manual'}"
[router]
backend = "needle-cactus"
fallback = "none"
timeout_secs = 7
max_tools = 2
[router.needle]
model = "needle3"
model_path = "/routing/needle.cact"
runtime_library = "/routing/libneedle.so"
venv = "/routing/venv"
max_tokens = 128
[brain.small]
backend = "{agent_backend}"
model = "qwen3-4b-instruct"
model_path = "/agent/model"
tool_selection = "{policy}"
''')
    cfg = load_config(path)
    router = Mock()
    router.respond.return_value = {'tool_calls': [{'function': {'name': 'set_volume', 'arguments': '{"action":"lower"}'}}]}
    agent = Mock(tool_only=agent_backend == 'needle-cactus')
    agent.ready.return_value = True
    agent.respond.side_effect = [
        {'tool_calls': [{'id':'volume', 'function': {'name':'set_volume', 'arguments':'{"action":"raise"}'}}]},
        {'content': 'Volume increased.'},
    ]
    with patch('agavai.router.create_brain', return_value=router) as factory, patch('agavai.harness.engine.create_brain', return_value=agent), tool_patch('agavai.harness.engine.call_tool', return_value='Volume increased.') as tool:
        context.reply = run_turn('increase playback level', cfg, context.harness.output, context=context.harness.context)
    context.routing_cfg, context.routing_policy = cfg, policy
    context.routing_factory, context.routing_model = factory, router
    context.routing_agent, context.routing_actions = agent, tool


@then('the router only selects schemas and the agent owns the executed arguments')
def needle_routed_agent_result(context):
    from agavai.tools import OPENAPI_TOOLS
    cfg, policy = context.routing_cfg, context.routing_policy
    model = cfg.router.needle
    assert model.backend == 'needle-cactus' and model.model_id == 'needle3'
    assert str(model.model_path) == '/routing/needle.cact'
    assert str(model.runtime_library) == '/routing/libneedle.so' and str(model.venv) == '/routing/venv'
    assert model.max_tokens == 128 and model.timeout_secs == cfg.router.timeout_secs == 7
    assert cfg.small_brain.model_path != model.model_path
    if policy == 'routed':
        context.routing_factory.assert_called_once_with(model, chat=None, health=None)
        assert context.routing_model.respond.call_args.args[1] == OPENAPI_TOOLS
    else:
        context.routing_factory.assert_not_called()
        context.routing_model.respond.assert_not_called()
    for request in context.routing_agent.respond.call_args_list:
        offered = [t['function']['name'] for t in request.args[1]]
        expected = ['set_volume'] if policy == 'routed' else [t['function']['name'] for t in OPENAPI_TOOLS]
        assert offered == expected + ['request_confirmation'], offered
        assert 'routing candidates' not in json.dumps(request.args[0])
    context.routing_actions.assert_called_once()
    name, args, _ = context.routing_actions.call_args.args
    assert name == 'set_volume'
    assert (json.loads(args) if isinstance(args, str) else args) == {'action': 'raise'}


@when('I evaluate installed Needle as a router for a simulated Qwen agent')
def native_needle_router_eval(context):
    from agavai.brain import close_brains
    from evals.cases import load_cases
    from evals.runner import run_case
    root = installed_cactus()
    cfg = Config()
    cfg.router.backend = 'needle-cactus'
    cfg.router.fallback = 'none'
    cfg.router.timeout_secs = 20
    cfg.router.needle = LlmConfig(backend='needle-cactus', model_id='needle3', venv=root/'venv',
                                 model_path=root/'needle3.cact', runtime_library=root/'libneedle.so', timeout_secs=20)
    replies = iter([
        {'tool_calls':[{'id':'volume', 'function':{'name':'set_volume', 'arguments':'{"action":"raise"}'}}]},
        {'content':'Volume increased.'},
    ])
    try:
        case = next(c for c in load_cases() if c.id == 'desktop.volume.up')
        with patch('evals.runner.real_chat', side_effect=lambda *a, **k: next(replies)), patch('evals.runner.health', return_value=True):
            context.native_evaluation = run_case(case, cfg, set())
    finally:
        close_brains()


@then('the evaluator separates native routing from agent calls and executes only the agent action')
def native_needle_router_eval_result(context):
    from agavai.tools import OPENAPI_TOOLS
    result = context.native_evaluation
    assert result['outcome'] == 'done', result
    turn = result['turns'][0]
    assert turn['heads'] == [['audio']], turn
    route, *agent = turn['model']
    assert route['kind'] == 'routing' and route['backend'] == 'needle-cactus' and route['seconds'] > 0, route
    assert route['offered'] == [t['function']['name'] for t in OPENAPI_TOOLS]
    assert all(m['kind'] == 'action' and m['backend'] == 'llama-server' for m in agent), agent
    assert len(turn['tools']) == 1 and json.loads(turn['tools'][0]['arguments']) == {'action': 'raise'}, turn


SHARED_NEEDLE_AGENT = '''[brain.small]
backend = "needle-cactus"
model = "needle3"
model_path = "/cactus/needle3.cact"
runtime_library = "/cactus/libneedle.so"
venv = "/cactus/venv"
tool_selection = "{policy}"
'''


@when('Needle is both router and agent through "{router_config}" with "{policy}" tools')
def needle_router_and_agent(context, router_config, policy):
    router = '[router]\nbackend = "needle-cactus"\nfallback = "keyword"\ntimeout_secs = 7\n'
    if router_config == 'same paths':
        router += ('[router.needle]\nmodel_path = "/cactus/needle3.cact"\n'
                   'runtime_library = "/cactus/libneedle.so"\nvenv = "/cactus/venv"\n')
    path = directory(context) / 'config.toml'
    path.write_text(router + SHARED_NEEDLE_AGENT.format(policy=policy))
    cfg = load_config(path)
    needle = Mock(tool_only=True)
    needle.ready.return_value = True
    needle.respond.return_value = {'tool_calls': [{'id': 'volume', 'function': {'name': 'set_volume', 'arguments': '{"action":"raise"}'}}]}
    with patch('agavai.router.create_brain') as router_factory, \
            patch('agavai.harness.engine.create_brain', return_value=needle), \
            tool_patch('agavai.harness.engine.call_tool', return_value='Volume raised.') as tool:
        context.reply = run_turn('turn the volume up', cfg, context.harness.output, context=context.harness.context)
    context.both = SimpleNamespace(cfg=cfg, config=router_config, needle=needle, router=router_factory, tool=tool)


@then('one Needle inference offered the full allowlist and no separate routing ran')
def needle_router_and_agent_result(context):
    from agavai.tools import OPENAPI_TOOLS
    both = context.both
    if both.config == 'shared':
        assert both.cfg.router.needle.model_path == both.cfg.small_brain.model_path
        assert both.cfg.router.needle.timeout_secs == 7 and both.cfg.small_brain.timeout_secs != 7
    both.router.assert_not_called()
    both.needle.respond.assert_called_once()
    offered = [t['function']['name'] for t in both.needle.respond.call_args.args[1]]
    assert offered == [t['function']['name'] for t in OPENAPI_TOOLS] + ['request_confirmation'], offered
    both.tool.assert_called_once()
    assert both.tool.call_args.args[0] == 'set_volume' and context.reply == 'Volume raised.'
    assert {'stage': 'Router', 'detail': 'combined with Needle inference'} in context.ui.data['execution']


@when('self-routed Needle cannot match "{text}" and routed Qwen is configured')
def needle_router_and_agent_escalates(context, text):
    path = directory(context) / 'config.toml'
    path.write_text('[router]\nbackend = "needle-cactus"\nfallback = "keyword"\nmax_tools = 8\n'
                    + SHARED_NEEDLE_AGENT.format(policy='routed') + '''[brain.large]
backend = "llama-server"
model = "qwen3-4b-instruct"
model_path = "/models/qwen.gguf"
port = 19000
tool_selection = "routed"
''')
    cfg = load_config(path)
    needle = Mock(tool_only=True)
    needle.ready.return_value = True
    needle.respond.return_value = {'unsupported': 'No matching tool call'}
    qwen = Mock(tool_only=False)
    qwen.ready.return_value = True
    offers = []
    replies = iter([
        {'tool_calls': [{'id': 'volume', 'function': {'name': 'set_volume', 'arguments': '{"action":"raise"}'}}]},
        {'content': 'Volume raised.'},
    ])

    def qwen_respond(messages, tools):
        offers.append([t['function']['name'] for t in tools])
        return next(replies)

    qwen.respond.side_effect = qwen_respond
    brains = {'needle-cactus': needle, 'llama-server': qwen}
    with patch('agavai.router.create_brain') as router_factory, \
            patch('agavai.harness.engine.create_brain', side_effect=lambda tier, **_: brains[tier.backend]), \
            tool_patch('agavai.harness.engine.call_tool', return_value='Volume raised.') as tool:
        context.reply = run_turn(text, cfg, context.harness.output, context=context.harness.context)
    context.both = SimpleNamespace(cfg=cfg, text=text, needle=needle, offers=offers, router=router_factory, tool=tool)


@then('Qwen is offered only the keyword "{head}" tools and Needle ran once')
def needle_router_and_agent_escalation_result(context, head):
    from agavai.heads import schemas_for_heads
    from agavai.router import KeywordRouter
    both = context.both
    assert KeywordRouter().select(both.text) == [head]
    both.router.assert_not_called()
    both.needle.respond.assert_called_once()
    expected = [t['function']['name'] for t in schemas_for_heads([head], limit=both.cfg.router.max_tools - 1)]
    assert both.offers == [expected + ['request_confirmation']] * 2, both.offers
    both.tool.assert_called_once()
    assert both.tool.call_args.args[0] == 'set_volume' and context.reply == 'Volume raised.'
    assert [row['detail'] for row in context.ui.data['execution'] if row['stage'] == 'Router'] == [
        'combined with Needle inference', f'keyword fallback after combined Needle · heads: {head}']
    assert context.ui.data['model_id'] == 'qwen3-4b-instruct'
