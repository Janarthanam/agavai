from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime
import json
import os
from pathlib import Path
from statistics import median
import sys

from behave import given, when, then

from agavai.brain import close_brains
from agavai.config import LlmConfig
from agavai.llm import health

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.cases import load_cases
from evals.runner import fingerprint, pinned_config, run_case


@given('local Qwen and Needle are available for comparison')
def comparison_setup(context):
    output = os.environ.get('AGAVAI_BRAIN_COMPARISON_OUT')
    if not output:
        context.scenario.skip('Set AGAVAI_BRAIN_COMPARISON_OUT to run the native comparison')
        return
    context.comparison_output = Path(output).resolve()
    assert context.comparison_output.is_relative_to(ROOT), 'Keep comparison output inside the repository'
    context.comparison_output.mkdir(parents=True, exist_ok=True)
    context.comparison_cfg = pinned_config()
    qwen = context.comparison_cfg.llm
    assert qwen.backend == 'llama-server' and health(qwen), 'Start the configured local Qwen server before comparing'
    context.comparison_qwen = replace(qwen, tool_selection='all', cache_prompt=True)
    root = Path(os.environ['AGAVAI_CACTUS_TEST_DIR']).resolve()
    context.comparison_needle = LlmConfig(
        backend='needle-cactus', model_id='needle3', venv=root / 'venv',
        model_path=root / 'needle3.cact', runtime_library=root / 'libneedle.so',
        timeout_secs=20, max_tokens=512,
    )
    context.add_cleanup(close_brains)


@given('the brain comparison includes these evaluation cases')
def comparison_cases(context):
    cases = {case.id: case for case in load_cases()}
    context.comparison_cases = [cases[row['id']] for row in context.table]


@when('I run the complete assistant with the "{profile}" brain policy')
def comparison_run(context, profile):
    cfg = context.comparison_cfg
    if profile in {'qwen-all', 'qwen-routed'}:
        selection = 'routed' if profile == 'qwen-routed' else 'all'
        cfg.small_brain = replace(context.comparison_qwen, tool_selection=selection)
        cfg.large_brain = None
    else:
        assert profile in {'needle-routed-qwen-all', 'needle-all-qwen-all'}, profile
        selection = 'routed' if profile == 'needle-routed-qwen-all' else 'all'
        cfg.small_brain = replace(context.comparison_needle, tool_selection=selection)
        cfg.large_brain = context.comparison_qwen
    cfg.router.backend, cfg.router.fallback = 'keyword', 'keyword'
    context.comparison_results = []
    started = datetime.now().astimezone().isoformat(timespec='seconds')
    metadata = fingerprint(cfg, {})
    path = context.comparison_output / f'{profile}.jsonl'
    with path.open('x', encoding='utf-8') as handle:
        for case in context.comparison_cases:
            result = run_case(case, cfg, set())
            context.comparison_results.append(result)
            handle.write(json.dumps(result, ensure_ascii=False) + '\n')
            handle.flush()
            print(f"{profile}: {case.id}: {result['outcome']} ({result['seconds']}s)", flush=True)
    turns = [turn for result in context.comparison_results for turn in result['turns']]
    summary = {
        'profile': profile, 'started': started, 'fingerprint': metadata,
        'outcomes': dict(Counter(result['outcome'] for result in context.comparison_results)),
        'cases': len(context.comparison_results), 'turns': len(turns),
        'median_turn_seconds': median(turn['seconds'] for turn in turns),
        'qwen_turns': sum(any(model['backend'] == 'llama-server' for model in turn['model']) for turn in turns),
    }
    with (context.comparison_output / f'{profile}.json').open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(summary, indent=2) + '\n')


@then('every comparison case has recorded model exchanges and a valid outcome')
def comparison_recorded(context):
    assert len(context.comparison_results) == len(context.comparison_cases)
    for result in context.comparison_results:
        assert result['outcome'] in {'done', 'honest', 'harmful'}, result
        assert result['turns'] and all(turn['model'] for turn in result['turns']), result


@then('the brain comparison made no outbound connection')
def comparison_local(context):
    for result in context.comparison_results:
        assert all(not turn['outbound'] for turn in result['turns']), result
