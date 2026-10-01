from __future__ import annotations

import os
import tempfile
from pathlib import Path

from behave import given, then, when

from agavai.config import dump_llm_env, load_config, set_model_id


def _cfg_dir(context) -> Path:
    if not getattr(context, "tmp", None):
        context.tmp = Path(tempfile.mkdtemp())
        context.config_path = context.tmp / "config.toml"
    return context.tmp


def _write(context, text: str) -> None:
    _cfg_dir(context)
    context.config_path.write_text(text)


@given("an empty agavai config")
def step_empty(context):
    _cfg_dir(context)
    # missing file is empty config


@given("a config with model \"qwen3-4b-instruct\"")
def step_default_id(context):
    _write(context, '[llm]\nmodel = "qwen3-4b-instruct"\n')


@given('a config that defines model "{mid}" at "{filename}" with ctx {ctx:d} and {ngl:d} gpu layers')
def step_named(context, mid, filename, ctx, ngl):
    d = _cfg_dir(context)
    gguf = d / filename
    gguf.write_bytes(b"x")
    _write(
        context,
        "[llm]\n"
        f'model = "{mid}"\n'
        f"[llm.models.{mid}]\n"
        f'path = "{gguf}"\n'
        f"ctx_size = {ctx}\n"
        f"n_gpu_layers = {ngl}\n",
    )
    context.gguf = gguf


@given('a config with model "qwen3-4b-instruct" and model_path "{filename}"')
def step_override(context, filename):
    d = _cfg_dir(context)
    gguf = d / filename
    gguf.write_bytes(b"x")
    _write(
        context,
        "[llm]\n"
        'model = "qwen3-4b-instruct"\n'
        f'model_path = "{gguf}"\n',
    )
    context.gguf = gguf


@given('a config that defines model "{mid}" at "{filename}"')
def step_simple_named(context, mid, filename):
    d = _cfg_dir(context)
    gguf = d / filename
    gguf.write_bytes(b"x")
    _write(
        context,
        "[llm]\n"
        f'model = "{mid}"\n'
        f"[llm.models.{mid}]\n"
        f'path = "{gguf}"\n',
    )
    context.gguf = gguf


@given('a config with model "qwen3-4b-instruct" and an extra model "{mid}" at "{filename}"')
def step_extra(context, mid, filename):
    d = _cfg_dir(context)
    gguf = d / filename
    gguf.write_bytes(b"x")
    _write(
        context,
        "[llm]\n"
        'model = "qwen3-4b-instruct"\n'
        'model_path = "/old.gguf"\n'
        'host = "127.0.0.1"\n'
        f"[llm.models.{mid}]\n"
        f'path = "{gguf}"\n',
    )
    context.gguf = gguf


@given('environment AGAVAI_MODEL points at "{filename}"')
def step_env(context, filename):
    d = _cfg_dir(context)
    gguf = d / filename
    gguf.write_bytes(b"x")
    old = os.environ.get("AGAVAI_MODEL")
    os.environ["AGAVAI_MODEL"] = str(gguf)

    def restore():
        if old is None:
            os.environ.pop("AGAVAI_MODEL", None)
        else:
            os.environ["AGAVAI_MODEL"] = old

    context.add_cleanup(restore)
    context.gguf = gguf


@when("I load the config")
def step_load(context):
    context.cfg = load_config(context.config_path)


@when('I set the model id to "{mid}"')
def step_set(context, mid):
    context.cfg = set_model_id(mid, context.config_path)


@when("I dump llm env")
def step_dump(context):
    context.cfg = load_config(context.config_path)
    context.llm_env = dump_llm_env(context.cfg)


@given('a config with vad backend "{backend}" and silence window {ms:d} ms')
def step_vad(context, backend, ms):
    _write(context, f'[vad]\nbackend = "{backend}"\nsilence_ms = {ms}\n')


@given("a config with an unknown vad key")
def step_vad_unknown(context):
    _write(context, "[vad]\nquantum_flux = 42\n")


@then('the model id should be "{mid}"')
def step_id(context, mid):
    assert context.cfg.llm.model_id == mid, context.cfg.llm.model_id


@then('the model path should end with "{suffix}"')
def step_path_end(context, suffix):
    path = str(context.cfg.llm.model_path)
    assert path.endswith(suffix), path


@then("ctx size should be {n:d}")
def step_ctx(context, n):
    assert context.cfg.llm.ctx_size == n


@then("n gpu layers should be {n:d}")
def step_ngl(context, n):
    assert context.cfg.llm.n_gpu_layers == n


@then("the model path should be marked overridden")
def step_over(context):
    assert context.cfg.llm.path_overridden


@then('the config file should set model to "{mid}"')
def step_file_has(context, mid):
    body = context.config_path.read_text()
    needle = f'model = "{mid}"'
    assert needle in body, body


@then('the config file should not contain "{text}"')
def step_file_not(context, text):
    body = context.config_path.read_text()
    assert text not in body, body


@then('setting the model id to "{mid}" should fail')
def step_fail(context, mid):
    try:
        set_model_id(mid, context.config_path)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


@then('the llm env should contain "{text}"')
def step_env_has(context, text):
    assert text in context.llm_env, context.llm_env


@given('a config with asr device "{device}"')
def step_asr(context, device):
    _write(context, f'[asr]\ndevice = "{device}"\n')


@then('the asr device should be "{device}"')
def step_asr_device(context, device):
    assert context.cfg.asr.device == device, context.cfg.asr.device


@then("vad should be enabled")
def step_vad_enabled(context):
    assert context.cfg.vad.enabled is True, context.cfg.vad


@then('the vad backend should be "{backend}"')
def step_vad_backend(context, backend):
    assert context.cfg.vad.backend == backend, context.cfg.vad.backend


@then("the vad silence window should be {ms:d} ms")
def step_vad_silence(context, ms):
    assert context.cfg.vad.silence_ms == ms, context.cfg.vad.silence_ms
