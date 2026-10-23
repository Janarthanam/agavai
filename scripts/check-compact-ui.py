#!/usr/bin/env python3
"""Check the actual overlay in an isolated Quickshell instance on Wayland.

Pass scenario names (compact, canvas-focus, recording) to run only those.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import wave

root = Path(__file__).resolve().parents[1]
scenarios = sys.argv[1:] or ['compact', 'canvas-focus', 'recording']
shell = Path('/usr/share/omarchy/shell')
env = os.environ.copy()
# Keep logs and snapshots isolated while connecting to the current compositor.
display = Path(env['WAYLAND_DISPLAY'])
if not display.is_absolute():
    display = Path(env['XDG_RUNTIME_DIR']) / display
with tempfile.TemporaryDirectory(prefix='agavai-compact-') as directory:
    runtime = Path(directory)
    for module in ('Commons', 'Ui'):
        (runtime / module).symlink_to(shell / module, target_is_directory=True)
    (runtime / 'Assistant').symlink_to(root / 'plugin', target_is_directory=True)
    (runtime / 'shell.qml').write_text((root / 'features/support/compact-ui.qml').read_text())
    # Playback needs the session's audio server; the recording played back is silent.
    env.update(PIPEWIRE_RUNTIME_DIR=env['XDG_RUNTIME_DIR'], PULSE_SERVER=f"unix:{env['XDG_RUNTIME_DIR']}/pulse/native")
    folder = runtime / 'Recordings' / '2026-10-23 20.17 Recording'
    folder.mkdir(parents=True)
    with wave.open(str(folder / 'audio.wav'), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(bytes(2 * 16000 * 2))
    segments = [{'id': 1, 'start_ms': 0, 'end_ms': 900, 'live': 'the canary ships on thursday'},
                {'id': 2, 'start_ms': 1000, 'end_ms': 1900, 'live': 'widen it on monday'}]
    (folder / 'recording.json').write_text(json.dumps({
        'title': 'Recording', 'started': '2026-10-23T20:17:00', 'status': 'ready', 'audio': 'audio.wav',
        'duration_ms': 2000, 'segments': segments, 'marks': [{'at_ms': 1500, 'label': ''}], 'pauses': []}))
    # The overlay's commands reach this stub, never a real recording.
    stub_log = runtime / 'agavai-commands.log'
    (runtime / 'bin').mkdir()
    (runtime / 'bin' / 'agavai').write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{stub_log}"\n')
    (runtime / 'bin' / 'agavai').chmod(0o755)
    env.update(XDG_RUNTIME_DIR=directory, WAYLAND_DISPLAY=str(display), QT_QPA_PLATFORM='wayland',
               PATH=f"{runtime / 'bin'}:{env['PATH']}", AGAVAI_UI_RECORDING=str(folder))
    for scenario in scenarios:
        env['AGAVAI_UI_CHECK'] = scenario
        result = subprocess.run(['quickshell', '-p', str(runtime / 'shell.qml'), '--no-color'],
                                env=env, text=True, capture_output=True, timeout=20)
        output = result.stdout + result.stderr
        if result.returncode or 'COMPACT_UI_PASS' not in output or 'COMPACT_UI_FAIL' in output:
            raise SystemExit(f'{scenario}:\n{output}')
    commands = stub_log.read_text().splitlines() if stub_log.is_file() else []
    expected = ['record pause', 'record mark', f'recording correct {folder} 1 The canary ships on Thursday.']
    if 'recording' in scenarios and [c for c in commands if c.startswith(('record ', 'recording '))] != expected:
        raise SystemExit(f'recording: the overlay ran {commands}, expected {expected}')
    print(', '.join(scenarios) + ': ' if sys.argv[1:] else '', end='')
    print('Compact native UI: focus, a canvas that stays up when another window takes focus, recording, review, and corrections, corner geometry for every placement, fixed orb, snapshots, minimize, and dismissal passed.')
