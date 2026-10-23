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

from behave import given, when, then

from agavai.config import Config, LlmConfig, load_config
from agavai.llm import LlmError
from agavai.orchestrator import run_turn
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
        'zero deadline': '[asr]\nfinish_timeout_secs=0',
        'unknown brain': '[brain.small]\nbackend="unknown"\nmodel_path="/m"',
        'missing brain model': '[brain.small]\nbackend="needle-cactus"',
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
    assert c.asr.backend == 'whistle-cactus' and c.asr.endpoint == 'manual'
    assert str(c.asr.venv) == '/speech'
    assert c.small_brain.backend == 'needle-cactus' and str(c.small_brain.venv) == '/brain'
    assert c.large_brain.port == 19000
    assert c.tts.venv != c.asr.venv


@then('engine configuration fails with "{message}"')
def bad_config(context, message):
    assert message.lower() in (context.engine_error or '').lower(), context.engine_error


class FakeWhistle:
    def __init__(self, **_):
        self.cancelled = 0

    def stream(self, chunks):
        try:
            for chunk in chunks:
                assert isinstance(chunk, array.array) and chunk.typecode == 'f'
                yield {'text': 'word', 'pending': 'pending'}
        except GeneratorExit:
            self.cancelled += 1
            raise
        yield {'text': 'tail', 'pending': ''}

    def transcribe(self, samples):
        assert len(samples) == 33600
        return {'text': 'word word word tail'}


def whistle(context, mode):
    context.partials = []
    cfg = SimpleNamespace(mode=mode, chunk_ms=1000, model_path='fixture', runtime_library='fixture')
    with patch.dict(sys.modules, needle=SimpleNamespace(Whistle=FakeWhistle)), patch("agavai.cactus_runtime.prepare"):
        return WhistleBackend(cfg, lambda kind, text: context.partials.append((kind, text)))


@when('a "{mode}" Whistle adapter receives two chunks and a short tail')
def feed_whistle(context, mode):
    backend = whistle(context, mode)
    for packet in (bytes(11000), bytes(29000), bytes(27200)):
        backend.feed(packet)
    context.final_text = backend.finish()


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
while header := sys.stdin.buffer.read(4):
    frame = sys.stdin.buffer.read(struct.unpack('>I', header)[0])
    kind, uid = struct.unpack('>cI', frame[:5])
    if kind == b'F':
        open(sys.argv[1], 'w').write('finished')
        if sys.argv[2] != 'timeout':
            print(json.dumps({'kind':'final','utterance_id':uid,'text':'open the browser'}), flush=True)
    elif kind == b'C':
        print(json.dumps({'kind':'cancelled','utterance_id':uid}), flush=True)
'''
CAPTURE = '''
import sys,time
while True:
    sys.stdout.buffer.write(bytes(640)); sys.stdout.buffer.flush(); time.sleep(.02)
'''


def worker_session(context, mode):
    from agavai.__main__ import listen_session, _cancel_path
    cfg = context.cfg
    cfg.asr.backend = 'whistle-cactus'
    cfg.asr.endpoint = 'manual'
    cfg.asr.mode = 'batch' if mode in {'cancel', 'batch_finish'} else 'streaming'
    cfg.asr.model_path = context.runtime_dir / 'whistle.cact'
    cfg.asr.runtime_library = context.runtime_dir / 'libneedle.so'
    cfg.asr.model_path.touch()
    cfg.asr.runtime_library.touch()
    cfg.asr.venv = Path(sys.executable).resolve().parents[1]
    cfg.asr.finish_timeout_secs = .2
    marker = context.runtime_dir / 'finished'
    spawn = subprocess.Popen
    def popen(argv, **kwargs):
        if argv[0] == 'parec':
            return spawn([sys.executable, '-c', CAPTURE], **kwargs)
        return spawn([sys.executable, '-c', WORKER, str(marker), mode], **kwargs)
    stopped = False
    def level(*_):
        nonlocal stopped
        if not stopped:
            stopped = True
            if mode == 'cancel':
                _cancel_path(cfg).touch()
            os.kill(os.getpid(), signal.SIGTERM)
    def submitted(*args, **kwargs):
        from agavai.ui import cancel_ui
        cancel_ui(cfg)
        return 'Browser opened.'
    with patch('agavai.asr.subprocess.Popen', side_effect=popen), patch('agavai.asr.shutil.which', return_value='parec'), patch.object(context.ui, 'level', side_effect=level), patch('agavai.__main__._run_stop_body', side_effect=submitted) as submit, patch('agavai.__main__.prepare_listen'), patch('agavai.__main__.cue_listen'), patch('agavai.__main__.finish'), patch('agavai.__main__._publish_pid'), patch('agavai.tts.sweep_playback_wavs'):
        listen_session(cfg, context.ui)
        context.submit_count = submit.call_count
        context.submit_calls = submit.call_args_list
        if submit.called:
            context.submitted_line = submit.call_args.kwargs['text']
    context.did_finalize = marker.exists()


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


def brain_turn(context, small_responses, *, tool_only=False, larger=True, large_responses=None):
    cfg = context.cfg
    cfg.router.backend = 'keyword'
    cfg.small_brain = LlmConfig(backend='needle-cactus' if tool_only else 'llama-server', model_id='small')
    cfg.large_brain = LlmConfig(model_id='large') if larger else None
    small = Mock(tool_only=tool_only)
    small.ready.return_value = True
    small.respond.side_effect = small_responses
    large = Mock(tool_only=False)
    large.ready.return_value = True
    large.respond.side_effect = large_responses or [{'content':'Larger answer.'}]
    context.engine_requests = []
    def factory(spec, **_):
        return small if spec.model_id == 'small' else large
    def record(messages, tools):
        context.engine_requests.append(deepcopy(messages))
        item = next(large_script)
        if isinstance(item, Exception):
            raise item
        return item
    large_script = iter(large_responses or [{'content':'Larger answer.'}])
    large.respond.side_effect = record
    with patch('agavai.orchestrator.create_brain', side_effect=factory), patch('agavai.orchestrator.call_tool', return_value='Opened browser.') as tool:
        context.reply = run_turn('open the browser', cfg, context.ui)
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


@when('the only brain engine returns an empty response')
def empty_only(context):
    brain_turn(context, [{'content':''}], larger=False)


@then('the reply does not claim completion')
def failure_not_success(context):
    assert 'could not handle' in context.reply and context.reply != 'Done.'


@when('the small engine launches the browser then escalates')
def after_tool(context):
    brain_turn(context, [BROWSER, {'content':''}], large_responses=[BROWSER, {'content':'Already opened.'}])


@then('the browser is launched once despite the larger engine repeating its call')
def once_only(context):
    assert context.executed_tools == 1
    assert any(m['role'] == 'tool' for m in context.engine_requests[0])
    assert context.reply == 'Already opened.'


@when('the small engine requests a browser launch without required arguments')
def bad_args(context):
    malformed = deepcopy(BROWSER)
    malformed['tool_calls'][0]['function']['arguments'] = '{}'
    brain_turn(context, [malformed], tool_only=True)


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
        with patch('agavai.orchestrator.chat') as chat, patch('agavai.orchestrator.health') as health:
            context.reply = run_turn('hello', cfg, context.ui)
            context.used_llama = chat.called or health.called


@then('its answer completes without invoking llama-server')
def registered_brain(context):
    assert context.reply == 'Registered engine answer.' and not context.used_llama


@when('I evaluate the browser task using the installed Needle engine')
def native_eval(context):
    from agavai.brain import close_brains
    from evals.cases import load_cases
    from evals.runner import run_case
    root = installed_cactus()
    cfg = Config()
    cfg.router.backend = 'keyword'
    cfg.small_brain = LlmConfig(backend='needle-cactus', venv=root/'venv', model_path=root/'needle3.cact', runtime_library=root/'libneedle.so', timeout_secs=20)
    try:
        case = next(case for case in load_cases() if case.id == 'desktop.launch.browser')
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


@when('the recognizer replaces a partial with an empty final transcript')
def empty_final(context):
    from agavai.__main__ import _await_utterance
    stream = Mock()
    stream.events.return_value = iter([('interim', 'open the browser'), ('eou', '')])
    with patch('agavai.__main__.prepare_listen'), patch('agavai.__main__.cue_listen'), patch('agavai.__main__.finish'):
        outcome, text = _await_utterance(context.cfg, context.ui, stream, fresh=True,
                                        stop_requested=lambda:False, cancel_requested=lambda:False)
    assert outcome == 'ignore' and not text
    context.submit_count = 0
