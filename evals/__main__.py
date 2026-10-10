"""Agavai assistant eval.

    PYTHONPATH=src python -m evals run [--stage cases|voice|measure|all] [--section S] [--out DIR]
    PYTHONPATH=src python -m evals score RUN_DIR      # writes RUN_DIR/report.json
    PYTHONPATH=src python -m evals report RUN_DIR     # writes RUN_DIR/report.html from report.json
    PYTHONPATH=src python -m evals regrade RUN_DIR    # grade stored observations again
    PYTHONPATH=src python -m evals diff A/report.json B/report.json

Design: docs/eval.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from evals.bindings import desktop as desktop_binding
from evals.cases import load_cases
from evals.world import World, load_world

RESULTS = Path(__file__).with_name("results")
SHIPPED_CAPABILITIES: set[str] = set()


def _log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", file=sys.stderr, flush=True)


def _bindings() -> dict[str, dict]:
    problems = desktop_binding.self_check(lambda: World(load_world(), datetime(2026, 10, 9, 16, 45)))
    return {"desktop": {"ok": not problems, "problems": problems}}


def stage_cases(out: Path, sections: list[str]) -> int:
    from evals.runner import canary, fingerprint, pinned_config, run_case, server_ready

    cfg = pinned_config()
    if not server_ready(cfg):
        _log("llama-server is not answering; start it with: systemctl --user start agavai-llm")
        return 2
    bindings = _bindings()
    if not bindings["desktop"]["ok"]:
        _log(f"desktop binding failed its self-check: {bindings['desktop']['problems']}")
        return 2
    cases = load_cases()
    _log("canary: running three cases twice")
    problems = canary(cases, cfg, SHIPPED_CAPABILITIES)
    meta = {
        "started": datetime.now().isoformat(timespec="seconds"),
        "fingerprint": fingerprint(cfg, bindings),
        "canary": {"ok": not problems, "problems": problems},
        "shipped_capabilities": sorted(SHIPPED_CAPABILITIES),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    if problems:
        _log(f"sampling is not pinned; no score: {problems}")
        return 3
    chosen = [c for c in cases if not sections or c.section in sections]
    path = out / "cases.jsonl"
    done_ids = set()
    if path.exists():
        # Resuming keeps finished cases and runs invalid ones again: an invalid case is a harness fault.
        kept = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        kept = [r for r in kept if r["outcome"] != "invalid"]
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8")
        done_ids = {r["id"] for r in kept}
    started = time.monotonic()
    with path.open("a", encoding="utf-8") as handle:
        for index, case in enumerate(chosen, 1):
            if case.id in done_ids:
                continue
            result = run_case(case, cfg, SHIPPED_CAPABILITIES)
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            handle.flush()
            elapsed = time.monotonic() - started
            _log(f"{index}/{len(chosen)} {case.id}: {result['outcome']} ({result.get('seconds', 0)}s, {elapsed / 60:.1f} min)")
    meta["finished_cases"] = datetime.now().isoformat(timespec="seconds")
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return 0


def stage_voice(out: Path) -> int:
    from evals.voice import run_voice

    cases_path = out / "cases.jsonl"
    case_results = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()] if cases_path.exists() else []
    result = run_voice(SHIPPED_CAPABILITIES, log=_log, case_results=case_results)
    (out / "voice.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


def stage_measure(out: Path) -> int:
    from evals.measure import run_measure

    result = run_measure(out, log=_log)
    (out / "measure.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals", description="Agavai assistant eval")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--stage", choices=["cases", "voice", "measure", "all"], default="all")
    run.add_argument("--section", action="append", default=[])
    run.add_argument("--out", type=Path)
    for name in ("score", "report", "regrade"):
        sub.add_parser(name).add_argument("run_dir", type=Path)
    diff = sub.add_parser("diff")
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)
    args = parser.parse_args(argv)

    if args.cmd == "run":
        out = args.out or RESULTS / datetime.now().strftime("%Y%m%d-%H%M")
        out.mkdir(parents=True, exist_ok=True)
        _log(f"results in {out}")
        stages = ["cases", "voice", "measure"] if args.stage == "all" else [args.stage]
        for stage in stages:
            code = {"cases": lambda: stage_cases(out, args.section), "voice": lambda: stage_voice(out), "measure": lambda: stage_measure(out)}[stage]()
            if code:
                return code
        if args.stage == "all":
            from evals.scoring import write_report

            write_report(out)
            _log(f"report data: {out / 'report.json'}")
        return 0
    if args.cmd == "score":
        from evals.scoring import write_report

        write_report(args.run_dir)
        return 0
    if args.cmd == "report":
        from evals.report import write_html

        path = write_html(args.run_dir)
        _log(f"report page: {path}")
        return 0
    if args.cmd == "regrade":
        from evals.scoring import regrade_run

        regrade_run(args.run_dir)
        return 0
    if args.cmd == "diff":
        from evals.scoring import diff

        print(diff(args.before, args.after))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
