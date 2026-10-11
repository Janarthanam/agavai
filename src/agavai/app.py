"""The desktop launcher opens the same single overlay used by the shortcut."""
import sys

from agavai.ui import summon_overlay
from agavai.config import load_config
from agavai.__main__ import read_listener, start_session


def run() -> int:
    cfg = load_config()
    if summon_overlay():
        # A leftover "listening" state with no process must not block a new session.
        if read_listener(cfg) is None:
            start_session(cfg)
        return 0
    print("Could not open Agavai. Ensure the Omarchy shell and janar.agavai plugin are running.", file=sys.stderr)
    return 1
