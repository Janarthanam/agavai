"""Turn stored observations into the report data file, RUN_DIR/report.json.

Scores are recomputed from observations with the current graders every time,
so a grader fix needs no new model run; the eval version records which
graders produced the numbers.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

from evals.cases import AREA_TITLES, AREAS, DERIVED, MEASURED, SECTION_AREA, TITLES, Case, load_cases
from evals.graders import DONE, HARMFUL, HONEST, PROPOSED_RULES, REPLY_RULES
from evals.measure import reliability_item
from evals.runner import regrade
from evals.voice import regrade_voice

EVAL_DIR = Path(__file__).parent
SCORED = {DONE, HONEST, HARMFUL}

# Which tool head would serve a change in an area. Used only by the routing diagnostic.
AREA_HEAD = {
    "audio": "audio", "bluetooth": "audio", "display.brightness": "system", "display.nightlight": "appearance",
    "system": "system", "theme": "appearance", "wallpaper": "wallpaper", "reminders": "reminders",
    "notifications": "reminders", "windows": "windows", "workspace": "windows", "focus": "windows",
    "fullscreen": "windows", "launched": "launch", "urls": "launch", "pickers": "launch", "screenshots": "capture",
}


def eval_version() -> str:
    digest = hashlib.sha256()
    for path in sorted([*EVAL_DIR.glob("cases/*.toml"), *EVAL_DIR.glob("world/*.toml"), EVAL_DIR / "graders.py",
                        EVAL_DIR / "budgets.toml", EVAL_DIR / "voice.py", EVAL_DIR / "bindings" / "desktop.py"]):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def clustered_se(values: list[int], clusters: list[str]) -> float:
    """Standard error of a mean of 0/1 outcomes, clustered by intent (Miller, 2024)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    sums: dict[str, float] = {}
    for value, cluster in zip(values, clusters):
        sums[cluster] = sums.get(cluster, 0.0) + (value - mean)
    return math.sqrt(sum(s * s for s in sums.values())) / n * 100


def section_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [i for i in items if i["outcome"] in SCORED]
    n = len(scored)
    if not n:
        return {"score": None, "n": 0, "done": 0, "honest": 0, "harmful": 0, "harm_rate": None, "se": None}
    done = sum(i["outcome"] == DONE for i in scored)
    harmful = sum(i["outcome"] == HARMFUL for i in scored)
    return {
        "score": round(100 * done / n, 1),
        "n": n,
        "done": done,
        "honest": sum(i["outcome"] == HONEST for i in scored),
        "harmful": harmful,
        "harm_rate": round(100 * harmful / n, 1),
        "se": round(clustered_se([int(i["outcome"] == DONE) for i in scored], [i.get("cluster") or i["id"] for i in scored]), 1),
    }


def _trim_turn(obs: dict[str, Any]) -> dict[str, Any]:
    return {
        "say": obs["say"],
        "heard": obs.get("heard"),
        "reply": obs["reply"],
        "grade": obs.get("grade"),
        "changes": obs.get("changes", []),
        "shown": [s for s in obs.get("shown", []) if not s.startswith("/")][:12],
        "model_calls": len(obs.get("model", [])),
        "context": obs.get("context"),
        "heads": obs.get("heads", []),
        "tools": [{"name": t["name"], "arguments": t["arguments"], "result": t["result"][:240]} for t in obs.get("tools", [])],
        "seconds": obs.get("seconds"),
        "rules": obs.get("rules", {}),
        "error": obs.get("error"),
        "outbound": obs.get("outbound", []),
    }


def case_items(cases: list[Case], results: dict[str, dict[str, Any]], shipped_caps: set[str]) -> list[dict[str, Any]]:
    items = []
    for case in cases:
        result = results.get(case.id)
        base = {"id": case.id, "section": case.section, "needs": case.needs, "shipped": case.shipped(shipped_caps),
                "cluster": case.cluster, "says": [t["say"] for t in case.turns], "note": case.note}
        if result is None:
            items.append({**base, "outcome": "not_run", "reason": "no result in this run", "turns": []})
            continue
        result = regrade(case, result)
        items.append({**base, "outcome": result["outcome"], "reason": result["reason"],
                      "seconds": result.get("seconds"), "turns": [_trim_turn(t) for t in result.get("turns", [])]})
    return items


def efficiency_items(cases: list[Case], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {c.id: c for c in cases}
    out = []
    for item in items:
        if item["outcome"] != DONE:
            continue
        case = by_id[item["id"]]
        over = []
        for turn, obs in zip(case.turns, item["turns"]):
            continuing = obs["context"] is not None
            default = (2 if len(turn.get("checks", [])) <= 1 else 3) if turn["kind"] == "act" else 2
            bound = turn.get("max_model_calls", default + (1 if continuing else 0))
            if obs["model_calls"] > bound:
                over.append(f"{obs['model_calls']} model calls for {turn['say']!r}, bound {bound}")
        out.append({"id": f"efficiency.{item['id']}", "case": item["id"], "needs": item["needs"], "shipped": item["shipped"],
                    "cluster": item["cluster"], "outcome": DONE if not over else HONEST, "reason": over[0] if over else "within bound"})
    return out


def reply_contract_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out, counts = [], {rule: {"passed": 0, "total": 0, "counted": rule in REPLY_RULES, "label": {**REPLY_RULES, **PROPOSED_RULES}[rule]}
                       for rule in [*REPLY_RULES, *PROPOSED_RULES]}
    replies = [(item["id"], i, t["reply"], t["rules"], item["needs"], item["shipped"]) for item in items for i, t in enumerate(item["turns"]) if t.get("reply")]
    for index, (case_id, turn, reply, rules, needs, shipped) in enumerate(replies):
        for rule, ok in rules.items():
            counts[rule]["total"] += 1
            counts[rule]["passed"] += int(ok)
        broken = [REPLY_RULES[r] for r in REPLY_RULES if not rules.get(r, True)]
        proposed = [PROPOSED_RULES[r] for r in PROPOSED_RULES if not rules.get(r, True)]
        out.append({"id": f"reply.{case_id}.{turn}", "case": case_id, "needs": needs, "shipped": shipped, "reply": reply,
                    "outcome": DONE if not broken else HONEST, "reason": "; ".join(broken) if broken else "fit to speak",
                    "proposed_broken": proposed})
    return out, counts


def routing_diagnostic(cases: list[Case], items: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {c.id: c for c in cases}
    rows = []
    for item in items:
        if not item["shipped"] or item["outcome"] not in SCORED or not item["turns"]:
            continue
        case = by_id[item["id"]]
        turn, obs = case.turns[0], item["turns"][0]
        offered = set(obs["heads"][0]) if obs["heads"] else set()
        if turn["kind"] == "act":
            needed = set()
            for spec in turn.get("checks", []):
                path = spec["path"]
                head = AREA_HEAD.get(path) or AREA_HEAD.get(".".join(path.split(".")[:2])) or AREA_HEAD.get(path.split(".")[0])
                if head:
                    needed.add(head)
            if not needed:
                continue
            ok = needed <= offered
            rows.append({"case": item["id"], "say": turn["say"], "needed": sorted(needed), "offered": sorted(offered), "ok": ok})
        elif turn["kind"] == "ignore":
            rows.append({"case": item["id"], "say": turn["say"], "needed": [], "offered": sorted(offered), "ok": not offered})
    ok = sum(r["ok"] for r in rows)
    return {"title": "Routing", "question": "Were the needed tools offered on the first step, and none for speech not meant for Agavai?",
            "score": round(100 * ok / len(rows), 1) if rows else None, "n": len(rows), "misses": [r for r in rows if not r["ok"]]}


def context_diagnostic(cases: list[Case], items: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {c.id: c for c in cases}
    rows = []
    for item in items:
        if item["outcome"] not in SCORED:
            continue
        for turn, obs in zip(by_id[item["id"]].turns, item["turns"]):
            if "context" in turn:
                rows.append({"case": item["id"], "say": turn["say"], "expected": turn["context"], "got": obs["context"], "ok": obs["context"] == turn["context"]})
    ok = sum(r["ok"] for r in rows)
    return {"title": "Context decision", "question": "Did the local model call a follow-up a follow-up, and a new topic new?",
            "score": round(100 * ok / len(rows), 1) if rows else None, "n": len(rows), "misses": [r for r in rows if not r["ok"]]}


def _area_scores(sections: list[dict[str, Any]], key: str, *, measured: bool) -> list[dict[str, Any]]:
    out = []
    for area, ids in AREAS.items():
        values = [s[key] for s in sections if s["id"] in ids and s[key] is not None and (measured or s["kind"] != "measured")]
        out.append({"id": area, "score": round(statistics.mean(values), 1) if values else None, "sections": len(values)})
    return out


def _total(areas: list[dict[str, Any]]) -> float | None:
    values = [a["score"] for a in areas if a["score"] is not None]
    return round(statistics.mean(values), 1) if values else None


def build_report(run_dir: Path) -> dict[str, Any]:
    meta = _read_json(run_dir / "meta.json")
    voice = regrade_voice(_read_json(run_dir / "voice.json"))
    measure = _read_json(run_dir / "measure.json")
    if measure.get("reliability"):
        by_id = {c.id: c for c in load_cases()}
        measure["reliability"] = [reliability_item(r["id"], [regrade(by_id[r["id"]], x) for x in r.get("results", [])]) if r.get("results") else r
                                  for r in measure["reliability"]]
    shipped_caps = set(meta.get("shipped_capabilities", []))
    cases = load_cases()
    results = {r["id"]: r for r in _read_jsonl(run_dir / "cases.jsonl")}
    items = case_items(cases, results, shipped_caps)

    section_items: dict[str, list[dict[str, Any]]] = {s: [] for s in SECTION_AREA}
    for item in items:
        section_items[item["section"]].append(item)
    section_items["efficiency"] = efficiency_items(cases, items)
    spoken = voice.get("spoken_tasks", [])
    reply_items, rule_counts = reply_contract_items(items)
    section_items["reply_contract"] = reply_items
    for key in ("hearing", "turn_taking", "speech_output"):
        section_items[key] = [{**v, "needs": [], "shipped": True, "cluster": v.get("text", v["id"])} for v in voice.get(key, [])]
    section_items["spoken_tasks"] = [
        {"id": s["id"], "case": s["case"], "needs": [], "shipped": True, "cluster": s["case"], "outcome": s["outcome"],
         "reason": s["reason"], "heard": s["heard"], "committed_by": s.get("committed_by"), "reply": s["reply"]}
        for s in spoken
    ]
    for key in ("speed", "interruption", "reliability"):
        section_items[key] = [{**{k: v for k, v in m.items() if k != "results"}, "needs": m.get("needs", []), "shipped": not m.get("needs"), "cluster": m["id"]}
                              for m in measure.get(key, [])]

    sections = []
    for section, area in SECTION_AREA.items():
        its = section_items.get(section, [])
        kind = "measured" if section in MEASURED else "derived" if section in DERIVED else "exact"
        stats = section_stats(its)
        shipped = section_stats([i for i in its if i.get("shipped")])
        sections.append({
            "id": section, "title": TITLES[section], "area": area, "kind": kind,
            **stats,
            "shipped_score": shipped["score"], "shipped_n": shipped["n"], "shipped_se": shipped["se"],
            "excluded": sum(i["outcome"] == "excluded" for i in its),
            "not_run": sum(i["outcome"] == "not_run" for i in its),
            "not_built": sum(1 for i in its if not i.get("shipped") and i["outcome"] in SCORED),
            "unscored_reason": "No footprint budgets are set." if section == "footprint" else ("Not run in this run." if not its else None),
            "items": its,
        })

    areas = []
    for with_measured in (True, False):
        assistant = _area_scores(sections, "score", measured=with_measured)
        shipped = _area_scores(sections, "shipped_score", measured=with_measured)
        areas.append((assistant, shipped))
    (assistant_all, shipped_all), (assistant_exact, shipped_exact) = areas
    area_rows = [
        {"id": a["id"], "title": AREA_TITLES[a["id"]], "score": a["score"], "shipped_score": s["score"],
         "score_exact": e["score"], "shipped_score_exact": se["score"], "sections": AREAS[a["id"]]}
        for a, s, e, se in zip(assistant_all, shipped_all, assistant_exact, shipped_exact)
    ]

    harmful = []
    for section in sections:
        for item in section["items"]:
            if item["outcome"] == HARMFUL:
                turn = next((t for t in item.get("turns", []) if (t.get("grade") or {}).get("outcome") == HARMFUL), None)
                harmful.append({"id": item["id"], "section": section["id"], "area": section["area"], "shipped": item.get("shipped"),
                                "reason": item["reason"], "say": turn["say"] if turn else None, "reply": turn["reply"] if turn else item.get("reply")})

    capabilities = {}
    for case in cases:
        for need in case.needs:
            capabilities.setdefault(need, 0)
            capabilities[need] += 1
    all_scored = [i for i in items if i["outcome"] in SCORED]
    outbound = [o for i in items for t in i["turns"] for o in t["outbound"]]
    started = meta.get("started")
    return {
        "schema": 1,
        "title": "Agavai assistant eval",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "eval_version": eval_version(),
        "run": {
            "id": run_dir.name,
            "started": started,
            "finished_cases": meta.get("finished_cases"),
            "fingerprint": meta.get("fingerprint", {}),
            "canary": meta.get("canary", {}),
            "shipped_capabilities": sorted(shipped_caps),
            "stages": {"cases": bool(results), "voice": bool(voice), "measure": bool(measure)},
        },
        "totals": {
            "assistant": {"score": _total(assistant_all), "without_measured": _total(assistant_exact)},
            "shipped": {"score": _total(shipped_all), "without_measured": _total(shipped_exact)},
            "harmful": len(harmful),
            "harmful_shipped": sum(1 for h in harmful if h["shipped"]),
            "cases": len(cases),
            "cases_scored": len(all_scored),
            "cases_shipped": sum(1 for i in all_scored if i["shipped"]),
            "excluded": sum(i["outcome"] == "excluded" for i in items),
            "invalid": sum(i["outcome"] == "invalid" for i in items),
            "outbound_connections": len(outbound),
        },
        "areas": area_rows,
        "sections": sections,
        "harmful": harmful,
        "reply_rules": rule_counts,
        "diagnostics": {"routing": routing_diagnostic(cases, items), "context": context_diagnostic(cases, items)},
        "capabilities": [{"id": cap, "built": cap in shipped_caps, "cases": count} for cap, count in sorted(capabilities.items(), key=lambda kv: -kv[1])],
        "footprint": measure.get("footprint", {}),
        "voice": {"recognizer": voice.get("recognizer"), "clips": voice.get("clips", [])},
        "measure_samples": measure.get("samples", {}),
        "invalid": [{"id": i["id"], "reason": i["reason"]} for i in items if i["outcome"] == "invalid"],
    }


def write_report(run_dir: Path) -> Path:
    report = build_report(run_dir)
    path = run_dir / "report.json"
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def regrade_run(run_dir: Path) -> None:
    cases = {c.id: c for c in load_cases()}
    path = run_dir / "cases.jsonl"
    results = [regrade(cases[r["id"]], r) if r["id"] in cases else r for r in _read_jsonl(path)]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")


def diff(before: Path, after: Path) -> str:
    a, b = json.loads(before.read_text()), json.loads(after.read_text())
    lines = []
    if a["eval_version"] != b["eval_version"]:
        lines.append(f"eval versions differ ({a['eval_version']} vs {b['eval_version']}); scores are not comparable")
    outcome = lambda report: {i["id"]: i["outcome"] for s in report["sections"] for i in s["items"]}
    old, new = outcome(a), outcome(b)
    fixed = sorted(k for k in old.keys() & new.keys() if old[k] != DONE and new[k] == DONE)
    broke = sorted(k for k in old.keys() & new.keys() if old[k] == DONE and new[k] != DONE)
    lines.append(f"assistant {a['totals']['assistant']['score']} -> {b['totals']['assistant']['score']}; shipped {a['totals']['shipped']['score']} -> {b['totals']['shipped']['score']}")
    lines.append(f"fixed ({len(fixed)}): " + ", ".join(fixed))
    lines.append(f"broke ({len(broke)}): " + ", ".join(broke))
    return "\n".join(lines)
