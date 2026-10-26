from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from behave import given, when, then

from agavai import __version__
from agavai.config import load_config
from agavai.ui import ChatUi

ROOT = Path(__file__).resolve().parents[2]


@given('pipeline help services with "{policy}" tools, "{router}" routing and "{outcome}" primary')
def help_services(context, policy, router, outcome):
    folder = tempfile.TemporaryDirectory(prefix="agavai-help-")
    context.add_cleanup(folder.cleanup)
    context.help_dir = Path(folder.name)
    context.help_policy, context.help_router, context.help_outcome = policy, router, outcome
    context.help_requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.respond(200, {})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            context.help_requests.append((self.path, body))
            if self.path == '/jev':
                self.respond(503, {'error': 'offline fixture'})
                return
            if body['model'] == 'primary' and outcome == 'fails':
                message = {'content': ''}
            elif not any(m['role'] == 'tool' for m in body['messages']):
                message = {'tool_calls': [{'id': 'clock', 'function': {'name': 'clock_now', 'arguments': '{}'}}]}
            else:
                message = {'content': 'The time is shown.'}
            self.respond(200, {'choices': [{'message': message}]})

        def respond(self, status, body):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

    context.help_ports = []
    for _ in range(2):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        thread.start()
        context.add_cleanup(server.server_close)
        context.add_cleanup(server.shutdown)
        context.help_ports.append(server.server_port)
    # Real CLI, with no host audio or desktop commands on PATH.
    binaries = context.help_dir / 'bin'
    binaries.mkdir()
    (binaries / 'git').symlink_to(shutil.which('git'))
    context.help_env = dict(os.environ, PATH=str(binaries), XDG_RUNTIME_DIR=str(context.help_dir),
                            PYTHONPATH=str(ROOT / 'src'), AGAVAI_HELP_TEST_KEY='fixture')


@given('speech input configured as "{endpoint}"')
def help_config(context, endpoint):
    context.help_endpoint = endpoint
    path = context.help_dir / 'config.toml'
    path.write_text(f'''[asr]
backend = "{'parakeet-onnx' if endpoint == 'native' else 'whistle-cactus'}"
endpoint = "{endpoint}"
model_path = "/models/help-whistle.cact"
[router]
backend = "{context.help_router}"
fallback = "keyword"
[router.jev]
base_url = "http://127.0.0.1:{context.help_ports[0]}/jev"
api_key_env = "AGAVAI_HELP_TEST_KEY"
[brain.small]
model_path = "/models/help-primary.gguf"
alias = "primary"
port = {context.help_ports[0]}
tool_selection = "{context.help_policy}"
[brain.large]
model_path = "/models/help-fallback.gguf"
alias = "fallback"
port = {context.help_ports[1]}
[tts]
venv = "{context.help_dir}/missing-tts"
''')
    context.help_config_path = path
    context.help_env['AGAVAI_CONFIG'] = str(path)


@given('pipeline help prefers eSpeak with a runnable speech command')
def preferred_speech(context):
    path = context.help_config_path
    path.write_text(path.read_text().replace('[tts]', '[tts]\nprefer = "ESPEAK"'))
    command = context.help_dir / 'bin/espeak-ng'
    command.write_text('#!/bin/sh\nexit 0\n')
    command.chmod(0o755)


@given('an old snapshot claims a different version and pipeline')
def old_help(context):
    runtime = context.help_dir / 'agavai'
    runtime.mkdir()
    (runtime / 'ui.json').write_text(json.dumps({'version': 'obsolete', 'pipeline': [{'stage': 'obsolete'}],
                                               'execution': [{'stage': 'obsolete'}], 'model_id': 'obsolete'}))


@when('the pipeline help CLI asks for the time')
def help_ask(context):
    result = subprocess.run([sys.executable, '-m', 'agavai', 'ask', 'what time is it'],
                            env=context.help_env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    context.help_snapshot_path = context.help_dir / 'agavai/ui.json'
    context.help_snapshot = json.loads(context.help_snapshot_path.read_text())


@then('pipeline help identifies this version and the loaded stages')
def help_stages(context):
    data = context.help_snapshot
    assert data['version'].startswith(__version__ + ' · '), data
    revision = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, text=True).strip()
    assert revision in data['version'], data['version']
    stages = {row['stage']: row['detail'] for row in data['pipeline']}
    assert set(stages) == {'Input', 'Send', 'Router', 'Primary', 'Fallback', 'Actions', 'Reply'}
    assert 'help-primary.gguf' in stages['Primary'] and context.help_policy in stages['Primary']
    assert 'help-fallback.gguf' in stages['Fallback']
    assert context.help_router in stages['Router']
    assert {'vad': 'energy VAD · 900 ms quiet', 'manual': 'Enter to send', 'native': 'native end of utterance'}[context.help_endpoint] == stages['Send']
    assert data['input_mode'] == 'typed'
    assert 'obsolete' not in json.dumps(data)


@then('pipeline help execution matches the HTTP requests and completed action')
def help_execution(context):
    data = context.help_snapshot
    events = data['execution']
    requests = [body for path, body in context.help_requests if path != '/jev']
    brains = [row for row in events if row['stage'] == 'Brain']
    assert len(brains) == len(requests), (events, requests)
    for event, request in zip(brains, requests):
        assert ('help-primary.gguf' if request['model'] == 'primary' else 'help-fallback.gguf') in event['detail']
    assert any(row == {'stage': 'Action', 'detail': 'clock_now'} for row in events), events
    assert data['turns'][-1]['tools'][-1]['status'] == 'ok'
    assert data['model_id'] == ('large' if context.help_outcome == 'fails' else 'small')
    routes = [row['detail'] for row in events if row['stage'] == 'Router']
    jev_calls = [path for path, _ in context.help_requests if path == '/jev']
    if context.help_policy == 'all' or context.help_router == 'none':
        assert routes == ['bypassed · all tools'] and not jev_calls, (routes, jev_calls)
    elif context.help_router == 'jev':
        assert len(jev_calls) == len(routes) and all('jev (HTTPError) → keyword' in row for row in routes), routes
    else:
        assert routes == ['keyword → keyword · heads: reminders'], routes


@when('the pipeline help listener handles a committed request without speech assets')
def help_listener(context):
    from agavai.harness import Harness
    from agavai.harness.session import _run_stop_body
    cfg = load_config(context.help_config_path)
    cfg.runtime_dir = context.help_dir / 'agavai'
    ui = ChatUi(cfg)
    with patch.dict(os.environ, context.help_env), patch('agavai.ui.summon_overlay'):
        harness = Harness(cfg, on_event=ui.on_harness_event, should_cancel=ui.cancelled)
        ui.listening()
        _run_stop_body(cfg, harness.output, False, text='what time is it', harness=harness)
    context.help_snapshot = json.loads(ui.path.read_text())


@then('pipeline help reports notification-only speech')
def help_speech(context):
    assert context.help_snapshot['execution'][-1] == {'stage': 'Reply', 'detail': 'notification only · speech unavailable'}
    assert context.help_snapshot['input_mode'] == 'voice'


@then('pipeline help reports the preferred speech engine and fallback order')
def speech_order(context):
    data = context.help_snapshot
    assert data['execution'][-1] == {'stage': 'Reply', 'detail': 'espeak'}
    reply = next(row['detail'] for row in data['pipeline'] if row['stage'] == 'Reply')
    assert reply.startswith('espeak → kokoro → notification'), reply


@when('I inspect pipeline help in the native overlay')
def help_native(context):
    if not os.environ.get('AGAVAI_NATIVE_UI_CHECK'):
        context.scenario.skip('Set AGAVAI_NATIVE_UI_CHECK=1 on an unlocked Wayland desktop')
        return
    context.help_native = subprocess.run([sys.executable, str(ROOT / 'scripts/check-compact-ui.py')],
        env=dict(os.environ, AGAVAI_UI_HELP_SNAPSHOT=str(context.help_snapshot_path)),
        capture_output=True, text=True, timeout=60)


@then('the native help interaction checks pass')
def native_help_pass(context):
    assert context.help_native.returncode == 0, context.help_native.stdout + context.help_native.stderr
