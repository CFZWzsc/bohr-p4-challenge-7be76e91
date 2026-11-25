#!/usr/bin/env python3
"""Deterministic fair-comparison bench for the candidate-plan comparison skill.

For every case in bench/cases the harness runs the skill once through
scripts/run_skill.py, then compares the reported winner and the reported
missing-data cells against a fixed gold standard in bench/gold.  A naive
baseline that ignores budgets, lead times, resource availability and missing
data is evaluated on exactly the same case file.

Outputs (both byte-stable across runs):
    bench/bench_metrics.json
    bench/bench_report.md

Standard library only.  No network, no timestamps, no absolute paths in the
artefacts.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUBMISSION = HERE.parent
CASES_DIR = HERE / "cases"
GOLD_DIR = HERE / "gold"
SKILL_SCRIPT = SUBMISSION / "scripts" / "run_skill.py"
METRICS_PATH = HERE / "bench_metrics.json"
REPORT_PATH = HERE / "bench_report.md"


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def numeric(value, default=None):
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def naive_baseline(case):
    """Pick the largest objective_fit, ignoring every hard constraint.

    Ties fall back to the lexicographically smaller candidate id so the rule
    is fully deterministic.  The baseline emits no missing-data cells.
    """
    candidates = [item for item in case.get("candidates") or [] if isinstance(item, dict)]
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda item: (-(numeric(item.get("objective_fit"), -1.0)), str(item.get("id"))),
    )
    return ranked[0].get("id")


def run_skill(case_path):
    """Run one skill invocation in an isolated copy of the case directory.

    The engine discovers material files in the directory that contains the
    case file, so each case is staged alone as <tmp>/input/case.json.  This
    keeps cases from leaking into one another and keeps the run deterministic.
    """
    with tempfile.TemporaryDirectory(prefix="plancompare-bench-") as tmp:
        stage_dir = Path(tmp) / "input"
        stage_dir.mkdir()
        staged_case = stage_dir / "case.json"
        shutil.copyfile(case_path, staged_case)
        out_path = Path(tmp) / "output" / "result.json"
        work_dir = Path(tmp) / "work"
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONHASHSEED"] = "0"
        completed = subprocess.run(
            [sys.executable, str(SKILL_SCRIPT),
             "--case", str(staged_case),
             "--out", str(out_path),
             "--work", str(work_dir)],
            cwd=str(SUBMISSION),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "run_skill.py exited with %d: %s"
                % (completed.returncode, (completed.stderr or "").strip()[:400])
            )
        if not out_path.is_file():
            raise RuntimeError("run_skill.py produced no result.json: %s"
                               % (completed.stderr or "").strip()[:400])
        return load_json(out_path)


def missing_cells(result):
    cells = set()
    for entry in result.get("missing_data") or []:
        if isinstance(entry, dict):
            candidate = entry.get("candidate")
            field = entry.get("field")
            if candidate is not None and field is not None:
                cells.add("%s:%s" % (candidate, field))
    return cells


def collect_cases():
    case_paths = sorted(CASES_DIR.glob("*.json"), key=lambda path: path.name)
    if not case_paths:
        raise RuntimeError("no case files found under bench/cases")
    pairs = []
    for case_path in case_paths:
        gold_path = GOLD_DIR / case_path.name
        if not gold_path.is_file():
            raise RuntimeError("missing gold standard for %s" % case_path.name)
        case = load_json(case_path)
        gold = load_json(gold_path)
        if not case.get("case_id") or case.get("case_id") != gold.get("case_id"):
            raise RuntimeError("case_id mismatch between %s and its gold file"
                               % case_path.name)
        if not gold.get("winner"):
            raise RuntimeError("gold standard without a winner: %s" % gold_path.name)
        pairs.append((case_path, case, gold))
    return pairs


def evaluate():
    rows = []
    for case_path, case, gold in collect_cases():
        result = run_skill(case_path)
        recommendation = result.get("recommendation") or {}
        skill_winner = recommendation.get("selected")
        baseline_winner = naive_baseline(case)
        detected = missing_cells(result)
        expected = set(gold.get("missing_or_unsupported") or [])
        rows.append({
            "case_id": case.get("case_id"),
            "case_sha256": file_sha256(case_path),
            "gold_winner": gold.get("winner"),
            "skill_winner": skill_winner,
            "skill_status": result.get("status"),
            "skill_winner_correct": skill_winner == gold.get("winner"),
            "baseline_winner": baseline_winner,
            "baseline_winner_correct": baseline_winner == gold.get("winner"),
            "skill_missing_detected": len(detected),
            "baseline_missing_detected": 0,
            "gold_missing_expected": len(expected),
            "skill_missing_matches_gold": detected == expected,
            "skill_missing": sorted(detected),
            "gold_missing": sorted(expected),
        })
    totals = {
        "cases": len(rows),
        "skill_winner_correct": sum(1 for row in rows if row["skill_winner_correct"]),
        "baseline_winner_correct": sum(1 for row in rows if row["baseline_winner_correct"]),
        "skill_missing_detected": sum(row["skill_missing_detected"] for row in rows),
        "baseline_missing_detected": sum(row["baseline_missing_detected"] for row in rows),
        "skill_missing_exact_cases": sum(1 for row in rows if row["skill_missing_matches_gold"]),
        "all_skill_runs_completed": all(row["skill_status"] == "completed" for row in rows),
    }
    checks = {
        "skill_winner_correct_gt_baseline":
            totals["skill_winner_correct"] > totals["baseline_winner_correct"],
        "skill_missing_detected_gt_zero": totals["skill_missing_detected"] > 0,
        "baseline_missing_detected_zero": totals["baseline_missing_detected"] == 0,
        "skill_missing_matches_gold_in_all_cases":
            totals["skill_missing_exact_cases"] == totals["cases"],
        "all_skill_runs_completed": totals["all_skill_runs_completed"],
    }
    metrics = {
        "bench": "plan-comparison-fair-comparison",
        "protocol": {
            "input": "each case file is copied alone into an isolated directory and both sides read the same bytes",
            "gold": "winner and missing cells are fixed in bench/gold before the run",
            "skill_command": "python scripts/run_skill.py --case <staged case.json> --out <tmp>/output/result.json --work <tmp>/work",
            "baseline_rule": "argmax candidate objective_fit; budgets, lead times, resource availability and missing data ignored",
            "baseline_missing": "the baseline always reports an empty missing list",
        },
        "cases": rows,
        "totals": totals,
        "checks": checks,
    }
    return metrics


def render_report(metrics):
    lines = []
    lines.append("# 基准对照报告：候选方案比较与选择")
    lines.append("")
    lines.append("本报告由 `bench/run_bench.py` 生成，内容固定可复现；重复运行字节一致。")
    lines.append("")
    lines.append("## 对照协议")
    lines.append("")
    lines.append("1. 每个 case 在运行前已写好金标准（`bench/gold/`），winner 由硬约束唯一确定。")
    lines.append("2. 技能侧：把该 case 单独复制到隔离目录，执行一次")
    lines.append("   `python scripts/run_skill.py --case <隔离目录>/case.json --out <临时目录>/result.json --work <临时目录>/work`。")
    lines.append("3. 基线侧：同一份 case 字节，直接取 `objective_fit` 最大的候选，忽略预算、货期、资源可用性与缺失数据。")
    lines.append("4. 两侧使用同一金标准判分，不调参、不筛选 case、不修改引擎。")
    lines.append("")
    lines.append("## 指标定义")
    lines.append("")
    lines.append("- **winner 正确**：输出的 winner 与金标准 winner 完全一致。")
    lines.append("- **缺失检出数**：`missing_data` 中 `候选:字段` 单元格的条数；基线按定义恒为 0。")
    lines.append("- **缺失集合匹配**：检出的 `候选:字段` 集合与金标准 `missing_or_unsupported` 完全一致。")
    lines.append("")
    lines.append("## 逐例结果")
    lines.append("")
    lines.append("| case | 金标准 winner | 技能 winner | 基线 winner | 技能正确 | 基线正确 | 技能缺失检出 | 基线缺失检出 | 缺失集合匹配 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for row in metrics["cases"]:
        lines.append("| %s | %s | %s | %s | %s | %s | %d | %d | %s |" % (
            row["case_id"],
            row["gold_winner"],
            row["skill_winner"],
            row["baseline_winner"],
            "是" if row["skill_winner_correct"] else "否",
            "是" if row["baseline_winner_correct"] else "否",
            row["skill_missing_detected"],
            row["baseline_missing_detected"],
            "是" if row["skill_missing_matches_gold"] else "否",
        ))
    totals = metrics["totals"]
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    lines.append("- case 数：%d" % totals["cases"])
    lines.append("- winner 正确数：技能 %d / 基线 %d" % (
        totals["skill_winner_correct"], totals["baseline_winner_correct"]))
    lines.append("- 缺失检出数：技能 %d / 基线 %d" % (
        totals["skill_missing_detected"], totals["baseline_missing_detected"]))
    lines.append("- 缺失集合与金标准完全一致的 case 数：%d / %d" % (
        totals["skill_missing_exact_cases"], totals["cases"]))
    lines.append("")
    lines.append("## 复现")
    lines.append("")
    lines.append("```bash")
    lines.append("python bench/run_bench.py")
    lines.append("```")
    lines.append("")
    lines.append("运行后在 `bench/` 生成 `bench_metrics.json` 与 `bench_report.md`；两次运行可用文件哈希比对。")
    lines.append("")
    lines.append("## 已知边界")
    lines.append("")
    lines.append("- case 均为合成数据，规模小，覆盖预算、时间窗、采购货期、关键资源缺失四类硬约束。")
    lines.append("- 每个 case 的 winner 都因其余候选违反硬约束而唯一，不检验多个 eligible 候选之间的权重排序。")
    lines.append("- 报告只记录判定结果，不评价推荐理由的文字质量。")
    lines.append("")
    return "\n".join(lines)


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main():
    metrics = evaluate()
    write_text(METRICS_PATH, json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    write_text(REPORT_PATH, render_report(metrics) + "\n")
    failed = sorted(key for key, ok in metrics["checks"].items() if not ok)
    print("cases=%d skill_correct=%d baseline_correct=%d skill_missing=%d baseline_missing=%d"
          % (metrics["totals"]["cases"],
             metrics["totals"]["skill_winner_correct"],
             metrics["totals"]["baseline_winner_correct"],
             metrics["totals"]["skill_missing_detected"],
             metrics["totals"]["baseline_missing_detected"]))
    if failed:
        print("FAILED CHECKS: %s" % ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
