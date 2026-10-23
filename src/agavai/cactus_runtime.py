"""Use installed Cactus artifacts only; provisioning belongs to setup."""
import os


def prepare(library):
    os.environ["NEEDLE_TELEMETRY"] = "0"
    os.environ["NEEDLE3_LIB_PATH"] = str(library)
    from needle.agent import fetch

    def missing(*args, **kwargs):
        raise RuntimeError("Cactus runtime/artifact unavailable or incompatible. Run scripts/setup-cactus.sh; runtime downloads are disabled.")

    fetch.fetch_library = missing
    fetch.fetch_weights = missing
