#!/usr/bin/env python3
"""Check the actual overlay in an isolated Quickshell instance on Wayland."""
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
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
    env.update(XDG_RUNTIME_DIR=directory, WAYLAND_DISPLAY=str(display), QT_QPA_PLATFORM='wayland')
    result = subprocess.run(['quickshell', '-p', str(runtime / 'shell.qml'), '--no-color'],
                            env=env, text=True, capture_output=True, timeout=20)
    output = result.stdout + result.stderr
    if result.returncode or 'COMPACT_UI_PASS' not in output or 'COMPACT_UI_FAIL' in output:
        raise SystemExit(output)
    print('Compact native UI: focus, geometry, snapshots, minimize, and dismissal passed.')
