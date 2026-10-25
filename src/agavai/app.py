"""The desktop launcher opens the same single overlay used by the shortcut."""
import logging
import sys

from agavai.ui import summon_overlay
from agavai.config import load_config
from agavai.__main__ import read_listener, start_session

log = logging.getLogger(__name__)


def run() -> int:
    cfg = load_config()
    if summon_overlay():
        # A leftover "listening" state with no process must not block a new session.
        started = read_listener(cfg) is None and start_session(cfg)
        log.info("invoke summoned the overlay; started_session=%s", started)
        return 0
    log.error("overlay could not be summoned; no session started")
    print("Could not open Agavai. Ensure the Omarchy shell and janar.agavai plugin are running.", file=sys.stderr)
    return 1
