"""The desktop launcher opens the same single overlay used by the shortcut."""
import sys

from agavai.ui import summon_overlay
from agavai.config import load_config
from agavai.state import read_state
from agavai.__main__ import start_session


def run() -> int:
    cfg = load_config()
    if summon_overlay():
        if read_state(cfg) not in {"listening", "transcribing", "thinking", "speaking"}:
            start_session(cfg, automatic=True)
        return 0
    print("Could not open Agavai. Ensure the Omarchy shell and janar.agavai plugin are running.", file=sys.stderr)
    return 1
