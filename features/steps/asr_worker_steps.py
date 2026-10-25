from pathlib import Path
import os
import subprocess

from behave import when, then

from agavai.config import load_config


def _check(context, mode):
    cfg = load_config()
    root = Path(__file__).resolve().parents[2]
    model = os.environ.get("AGAVAI_ASR_TEST_MODEL_DIR", str(cfg.asr.model_dir))
    context.worker_check = subprocess.run(
        [str(cfg.asr.venv / "bin" / "python"), str(root / "features" / "support" / "asr_checks.py"), mode, model],
        capture_output=True,
        text=True,
        timeout=60,
    )


@when("I check the streaming frontend against a whole-waveform spectrogram")
def frontend(context):
    _check(context, "frontend")


@when("I check the streaming frontend with short audio tails")
def tails(context):
    _check(context, "tails")


@when("I replay the ASR speech fixture with different packet sizes")
def speech(context):
    _check(context, "speech")


@when("I replay the ASR speech fixture in two successive turns")
def reset(context):
    _check(context, "reset")


@when("I replay the ASR speech fixture after initial silence")
def silence(context):
    _check(context, "silence")


@when("I replay the ASR speech fixture as one continuous recording")
def continuous(context):
    _check(context, "continuous")


@then("the ASR worker check passes")
def checked(context):
    result = context.worker_check
    assert result.returncode == 0, result.stdout + result.stderr


@when("I replay speech through recording capture with Whistle selected for the assistant")
def recording_capture(context):
    _check(context, "recording")
