#!/usr/bin/env python3
"""Thin, crash-proof entry point for the plan-comparison skill.

All real work happens in sk_entry.py. This wrapper never propagates an
exception to the harness: on any failure it still writes a structured
result.json (with every output_contract key present) and exits 0.
"""

import json
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _option(argv, names, default=None):
    for index, arg in enumerate(argv):
        for name in names:
            if arg == name and index + 1 < len(argv):
                return argv[index + 1]
            if arg.startswith(name + "="):
                return arg.split("=", 1)[1]
    return default


def _case_path(argv):
    case = _option(argv, ("--case", "--case-path"))
    if case:
        return case
    source = _option(argv, ("--input", "--input-dir"), "/input")
    if source and os.path.isfile(source):
        return source
    candidate = os.path.join(source or "/input", "case.json")
    return candidate


def _write_fallback(argv, error_name):
    out = _option(argv, ("--out", "--output", "--result"), "/app/output/result.json")
    if os.path.isdir(out) or out.endswith(("/", "\\")) or not out.lower().endswith(".json"):
        out = os.path.join(out, "result.json")
    case = {}
    try:
        with open(_case_path(argv), "r", encoding="utf-8-sig") as handle:
            loaded = json.load(handle)
            if isinstance(loaded, dict):
                case = loaded
    except (OSError, ValueError):
        case = {}
    spec = case.get("output_contract")
    keys = list(spec.keys()) if isinstance(spec, dict) else spec if isinstance(spec, list) else []
    result = {
        "case_id": case.get("case_id") if isinstance(case, dict) else None,
        "status": "failed",
        "error": error_name,
        "candidates": [],
        "comparison_table": [],
        "scores": {},
        "ranking": [],
        "recommendation": None,
        "costs": [],
        "feasibility": [],
        "risks": [],
        "sensitivity": {},
        "missing_data": [],
        "conflicts": [],
        "evidence": [],
        "uncertainty": [{"issue": "entry point failed before comparison",
                         "impact": "no result was computed",
                         "handling": "structured failure result written; no data invented"}],
        "run_log": [{"step": "wrapper_fallback", "detail": error_name}],
        "summary": {"candidates": 0, "status": "failed"},
        "errors": [error_name],
        "contract_extras": {},
    }
    canonical = ("candidates", "comparison_table", "scores", "ranking", "recommendation",
                 "costs", "feasibility", "risks", "sensitivity", "missing_data",
                 "conflicts", "evidence", "uncertainty", "summary")
    for key in keys:
        if key in ("case_id", "status") or key in result:
            continue
        hint = str(spec.get(key)).lower() if isinstance(spec, dict) else ""
        result[key] = [] if ("array" in hint or "list" in hint) else None
        result["contract_extras"][key] = {"mapped": False, "note": "wrapper fallback"}
    for key in canonical:
        result.setdefault(key, [] if key not in ("scores", "sensitivity") else {})
    review = ("# 运行复核 run-review\n\n入口异常（%s），未生成比较结果。\n" % error_name)
    out_dir = os.path.dirname(os.path.abspath(out))
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        with open(os.path.join(out_dir, "run-review.md"), "w", encoding="utf-8") as handle:
            handle.write(review)
    except OSError:
        pass


def main():
    argv = list(sys.argv[1:])
    try:
        import sk_entry
        return sk_entry.main(argv)
    except BaseException as exc:
        _write_fallback(argv, type(exc).__name__)
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaseException:
        sys.exit(0)
