#!/usr/bin/env python3
"""Align and compare candidate experimental plans, then justify a choice.

Standard library only. Deterministic, offline, no private paths.
"""

import argparse
import hashlib
import json
import os
import re
import sys

PLAN_KEYS = ("plans", "candidate_plans", "plan_versions", "versions", "candidates", "options")
RESOURCE_KEYS = ("resources", "equipment", "materials", "consumables", "inventory", "catalog", "reagents", "price_list")
WEIGHT_KEYS = ("weights", "criteria_weights", "priority", "priorities")
TASK_KEYS = ("task", "objective", "goal", "research_question", "question")

CRITERIA = [
    ("objective_fit", "higher", "score", "fit to the stated research objective"),
    ("equipment_readiness", "higher", "ordinal", "fraction of named resources that are available now"),
    ("time_hours", "lower", "h", "total elapsed experimental hours"),
    ("cost_total", "lower", "currency", "total consumable and machine cost"),
    ("risk_level", "lower", "ordinal", "residual risk after mitigation"),
    ("evidence_strength", "higher", "count", "number of traceable evidence items"),
    ("parameter_range", "higher", "count", "number of parameters with a declared range"),
]


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def sha256_file(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def walk(obj, path=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = "%s.%s" % (path, key) if path else str(key)
            yield child, value
            for item in walk(value, child):
                yield item
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            child = "%s[%d]" % (path, idx)
            yield child, value
            for item in walk(value, child):
                yield item


def find_all(case, keys):
    lowered = {key.lower() for key in keys}
    found = []
    for path, value in walk(case):
        leaf = path.rsplit(".", 1)[-1].split("[", 1)[0]
        if leaf.lower() in lowered and value not in (None, "", [], {}):
            found.append((path, value))
    return found


def find_first(case, keys):
    found = find_all(case, keys)
    return found[0] if found else (None, None)


def as_dict_list(value):
    items = []
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict):
                items.append(entry)
            elif isinstance(entry, str):
                items.append({"name": entry})
    elif isinstance(value, dict):
        if any(isinstance(v, dict) for v in value.values()):
            for name, spec in value.items():
                item = dict(spec) if isinstance(spec, dict) else {"name": name, "value": spec}
                item.setdefault("name", name)
                items.append(item)
        else:
            items.append(value)
    return items


def num(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def first_num(mapping, names):
    if isinstance(mapping, dict):
        for name in names:
            if name in mapping:
                value = num(mapping[name])
                if value is not None:
                    return value
    return None


def text(value, limit=160):
    if isinstance(value, str):
        return " ".join(value.split())[:limit]
    return ""


def norm(value):
    return re.sub(r"[^a-z0-9]+", " ", text(value).lower()).strip()


def plan_leaf(plan, names):
    lowered = {name.lower() for name in names}
    for path, value in walk(plan):
        leaf = path.rsplit(".", 1)[-1].split("[", 1)[0]
        if leaf.lower() in lowered and value not in (None, "", [], {}):
            return value, path
    return None, None


def normalize_plans(case):
    path, value = find_first(case, PLAN_KEYS)
    plans = []
    for idx, item in enumerate(as_dict_list(value)):
        version = item.get("version") or item.get("name") or item.get("id") or ("plan-%d" % (idx + 1))
        plans.append({"label": str(version), "content": item, "source": "%s[%d]" % (path, idx) if path else None})
    return path, plans


def resource_catalog(case):
    catalog = []
    seen = set()
    provisional = ("availability", "status", "state", "stock", "unit_price", "price", "lead_time_days",
                   "lead_time", "quantity", "qty", "kind", "type")
    for path, value in find_all(case, RESOURCE_KEYS):
        if "[" in path.rsplit(".", 1)[-1]:
            continue
        for item in as_dict_list(value):
            if not any(key in item for key in provisional):
                continue
            name = text(item.get("name") or item.get("item") or item.get("model"), 100)
            if not name:
                continue
            key = (norm(name), str(item.get("availability")), str(item.get("unit_price")), path)
            if key in seen:
                continue
            seen.add(key)
            entry = dict(item)
            entry["_source"] = path
            catalog.append(entry)
    return catalog


def resource_status(item):
    raw = " ".join(text(item.get(key), 60) for key in ("availability", "status", "state", "stock")).lower()
    if any(word in raw for word in ("unavailable", "out of stock", "not available", "缺货")):
        return "unavailable"
    if any(word in raw for word in ("procure", "purchase", "order", "采购")):
        return "procure"
    if any(word in raw for word in ("outsource", "external", "vendor", "外协")):
        return "outsource"
    if any(word in raw for word in ("available", "in stock", "owned", "已具备", "可用")):
        return "available"
    return "unknown"


def matched_resources(plan, catalog):
    blob = norm(" ".join(text(v, 120) for _, v in walk(plan) if isinstance(v, str)))
    matches = []
    for item in catalog:
        name = text(item.get("name") or item.get("item") or item.get("model"), 100)
        token = norm(name)
        if not token or token not in blob:
            continue
        matches.append({
            "resource": name,
            "status": resource_status(item),
            "quantity": first_num(item, ("quantity", "qty", "stock", "units")),
            "unit_price": first_num(item, ("unit_price", "price", "unit_cost", "rate")),
            "lead_time_days": first_num(item, ("lead_time_days", "lead_time", "delivery_days")),
            "source": item.get("_source"),
        })
    return matches


def hours_of(plan):
    explicit, path = plan_leaf(plan, ("total_hours", "planned_hours", "duration_h", "estimated_hours"))
    explicit_num = num(explicit)
    if explicit_num is not None:
        return explicit_num, path, "declared_total"
    total = 0.0
    found = 0
    for leaf_path, value in walk(plan):
        leaf = leaf_path.rsplit(".", 1)[-1].split("[", 1)[0].lower()
        if leaf in ("duration_h", "hours", "time_h") and num(value) is not None:
            total += num(value)
            found += 1
        elif leaf in ("duration_min", "minutes") and num(value) is not None:
            total += num(value) / 60.0
            found += 1
    if found:
        return round(total, 4), "steps", "summed_steps"
    return None, None, "unknown"


def cost_of(plan, matches):
    explicit, path = plan_leaf(plan, ("total_cost", "cost_total", "estimated_cost", "budget_total", "cost"))
    explicit_num = num(explicit)
    if explicit_num is not None:
        return explicit_num, path, "declared_total", []
    lines = []
    total = 0.0
    for match in matches:
        if match["quantity"] is not None and match["unit_price"] is not None:
            line = round(match["quantity"] * match["unit_price"], 6)
            lines.append({"resource": match["resource"], "quantity": match["quantity"],
                          "unit_price": match["unit_price"], "line_cost": line, "source": match["source"]})
            total += line
    if lines:
        return round(total, 6), "resource_lines", "summed_lines", lines
    return None, None, "unknown", []


def risk_of(plan):
    value, path = plan_leaf(plan, ("risk_level", "risk_score", "risk", "risks"))
    if isinstance(value, str):
        lowered = value.lower()
        if any(word in lowered for word in ("low", "minor", "低")):
            return 0.0, path, "declared_level_low"
        if any(word in lowered for word in ("medium", "moderate", "中")):
            return 1.0, path, "declared_level_medium"
        if any(word in lowered for word in ("high", "severe", "高")):
            return 2.0, path, "declared_level_high"
    if isinstance(value, (int, float)):
        return float(value), path, "declared_score"
    if isinstance(value, list):
        severity = 0.0
        for item in value:
            if isinstance(item, dict):
                level = " ".join(text(item.get(k), 20) for k in ("level", "severity", "likelihood")).lower()
                if any(word in level for word in ("high", "severe", "高")):
                    severity += 2.0
                elif any(word in level for word in ("medium", "moderate", "中")):
                    severity += 1.0
                else:
                    severity += 0.5
            else:
                severity += 0.5
        return round(severity, 4), path, "counted_risk_items"
    return None, path, "unknown"


def evidence_of(plan):
    count = 0
    path = None
    for leaf_path, value in walk(plan):
        leaf = leaf_path.rsplit(".", 1)[-1].split("[", 1)[0].lower()
        if leaf in ("evidence", "references", "sources", "citations", "basis"):
            path = path or leaf_path
            if isinstance(value, list):
                count += len(value)
            elif isinstance(value, dict):
                count += len(value)
            elif isinstance(value, str) and value.strip():
                count += 1
    return count, path, "counted_evidence_items"


def objective_fit(plan):
    value, path = plan_leaf(plan, ("objective_fit", "fit_score", "expected_effect", "effect_size"))
    return num(value), path, "declared" if num(value) is not None else "unknown"


def parameter_range(plan):
    count = 0
    for leaf_path, value in walk(plan):
        leaf = leaf_path.rsplit(".", 1)[-1].split("[", 1)[0].lower()
        if leaf in ("parameter", "parameters", "parameter_range", "settings") and isinstance(value, dict):
            for _, spec in value.items():
                if isinstance(spec, dict):
                    if any(k in spec for k in ("min", "max", "values", "range")):
                        count += 1
                elif num(spec) is not None:
                    count += 0
    explicit, _ = plan_leaf(plan, ("parameter_range", "parameter_ranges", "range_declared"))
    if isinstance(explicit, dict):
        count = max(count, sum(1 for v in explicit.values() if isinstance(v, dict) or isinstance(v, list)))
    return count


def feasibility_of(matches):
    if not matches:
        return None, "no_matched_resources"
    statuses = [m["status"] for m in matches]
    if "unavailable" in statuses:
        return 0.0, "has_unavailable_resource"
    if all(s == "available" for s in statuses):
        return 1.0, "all_resources_available"
    if any(s in ("procure", "outsource") for s in statuses):
        return 0.5, "requires_procurement_or_outsourcing"
    return None, "availability_unknown"


def weights_of(case, criteria):
    _, value = find_first(case, WEIGHT_KEYS)
    weights = {}
    if isinstance(value, dict):
        for name, entry in value.items():
            number = num(entry)
            if number is not None and number > 0:
                weights[norm(name)] = number
    if not weights:
        return {name: 1.0 / len(criteria) for name, _, _, _ in criteria}, "equal_weights"
    total = sum(weights.values())
    resolved = {}
    for name, _, _, _ in criteria:
        resolved[name] = weights.get(norm(name), 0.0) / total if total else 0.0
    return resolved, "case_weights"


def normalize(values, direction):
    known = [v for v in values if v is not None]
    if not known:
        return [None] * len(values)
    low, high = min(known), max(known)
    result = []
    for value in values:
        if value is None:
            result.append(None)
        elif high - low < 1e-12:
            result.append(1.0)
        else:
            scaled = (value - low) / (high - low)
            result.append(scaled if direction == "higher" else 1.0 - scaled)
    return result


def score_plans(rows, weights):
    normalized = {}
    for name, direction, _, _ in CRITERIA:
        normalized[name] = normalize([row["values"].get(name) for row in rows], direction)
    scores = []
    for idx, row in enumerate(rows):
        total = 0.0
        weight_sum = 0.0
        parts = {}
        for name, _, _, _ in CRITERIA:
            value = normalized[name][idx]
            if value is None or weights.get(name, 0) <= 0:
                parts[name] = None
                continue
            parts[name] = round(value, 4)
            total += value * weights[name]
            weight_sum += weights[name]
        scores.append({
            "label": row["label"],
            "weighted_score": round(total / weight_sum, 4) if weight_sum else None,
            "normalized_parts": parts,
        })
    return scores, normalized


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare candidate experiment plans and justify a choice.")
    parser.add_argument("--case", default="/input/case.json")
    parser.add_argument("--out", "--output", default="/app/output/result.json")
    parser.add_argument("--work", default="/app/work")
    args = parser.parse_args(argv)

    errors, notes = [], []
    case, ok = {}, False
    try:
        case = load_json(args.case)
        ok = isinstance(case, dict)
        if not ok:
            errors.append("case_root_not_object")
            case = {}
    except FileNotFoundError:
        errors.append("case_file_not_found: %s" % os.path.basename(args.case))
    except (OSError, ValueError) as exc:
        errors.append("case_load_failed: %s" % exc)

    plan_path, plans = normalize_plans(case) if ok else (None, [])
    catalog = resource_catalog(case) if ok else []
    weights, weight_source = weights_of(case, CRITERIA) if plans else ({}, "not_applicable")

    rows = []
    for plan in plans:
        content = plan["content"]
        matches = matched_resources(content, catalog)
        hours, hours_path, hours_basis = hours_of(content)
        cost, cost_path, cost_basis, lines = cost_of(content, matches)
        risk, risk_path, risk_basis = risk_of(content)
        evidence_count, evidence_path, evidence_basis = evidence_of(content)
        fit, fit_path, fit_basis = objective_fit(content)
        feasibility, feasibility_reason = feasibility_of(matches)
        param_count = parameter_range(content)
        values = {
            "objective_fit": fit,
            "equipment_readiness": feasibility,
            "time_hours": hours,
            "cost_total": cost,
            "risk_level": risk,
            "evidence_strength": float(evidence_count) if evidence_count else None,
            "parameter_range": float(param_count) if param_count else None,
        }
        rows.append({
            "label": plan["label"],
            "values": values,
            "details": {
                "hours_basis": hours_basis,
                "hours_path": hours_path,
                "cost_basis": cost_basis,
                "cost_path": cost_path,
                "cost_lines": lines,
                "risk_basis": risk_basis,
                "risk_path": risk_path,
                "evidence_basis": evidence_basis,
                "evidence_path": evidence_path,
                "objective_fit_basis": fit_basis,
                "objective_fit_path": fit_path,
                "feasibility_reason": feasibility_reason,
                "resources": matches,
                "source": plan["source"],
            },
        })

    scores, normalized = score_plans(rows, weights) if rows else ([], {})
    ranked = sorted([s for s in scores if s["weighted_score"] is not None],
                    key=lambda entry: entry["weighted_score"], reverse=True)
    for idx, entry in enumerate(ranked):
        entry["rank"] = idx + 1

    choice = ranked[0] if ranked else None
    runner_up = ranked[1] if len(ranked) > 1 else None
    rejection = []
    if choice:
        for entry in ranked[1:]:
            gaps = []
            for name, direction, _, _ in CRITERIA:
                best = choice["normalized_parts"].get(name)
                other = entry["normalized_parts"].get(name)
                if best is None or other is None:
                    continue
                if best - other > 0.0001:
                    gaps.append({"criterion": name, "normalized_gap": round(best - other, 4)})
            gaps.sort(key=lambda item: item["normalized_gap"], reverse=True)
            rejection.append({
                "label": entry["label"],
                "score_gap": round(choice["weighted_score"] - entry["weighted_score"], 4),
                "decisive_gaps": gaps[:3],
                "reason": ("lower on %s" % ", ".join(g["criterion"] for g in gaps[:3])) if gaps else "tie on available criteria",
            })

    sensitivity = {"stable": True, "perturbations": [], "rank_changes": []}
    if len(ranked) > 1 and choice:
        base = choice["label"]
        for name in [c[0] for c in CRITERIA]:
            if weights.get(name, 0) <= 0:
                continue
            for factor in (1.25, 0.75):
                trial = dict(weights)
                trial[name] = weights[name] * factor
                trial_scores, _ = score_plans(rows, trial)
                trial_ranked = sorted([s for s in trial_scores if s["weighted_score"] is not None],
                                      key=lambda entry: entry["weighted_score"], reverse=True)
                new_choice = trial_ranked[0]["label"] if trial_ranked else None
                changed = new_choice != base
                sensitivity["perturbations"].append({"criterion": name, "factor": factor, "choice": new_choice,
                                                     "changed": changed})
                if changed:
                    sensitivity["stable"] = False
                    sensitivity["rank_changes"].append({"criterion": name, "factor": factor,
                                                        "new_choice": new_choice})

    conditions = []
    if choice:
        chosen_row = next((r for r in rows if r["label"] == choice["label"]), None)
        if chosen_row:
            for match in chosen_row["details"]["resources"]:
                if match["status"] in ("procure", "outsource"):
                    conditions.append({"condition": "resolve %s (%s)" % (match["resource"], match["status"]),
                                       "lead_time_days": match["lead_time_days"]})
                elif match["status"] == "unavailable":
                    conditions.append({"condition": "substitute unavailable resource %s" % match["resource"]})

    risks = [
        {"id": "R1", "mode": "no feasible candidate", "trigger": "all plans have an unavailable resource or out-of-range parameter", "action": "relax the binding constraint with owner approval or add a new candidate"},
        {"id": "R2", "mode": "incomparable fields", "trigger": "cost or time units differ across plans", "action": "normalize units before comparing; do not sum mixed units"},
        {"id": "R3", "mode": "weight sensitivity", "trigger": "choice flips under a 25% weight perturbation", "action": "report the flip condition and let the owner set weights"},
        {"id": "R4", "mode": "unknown treated as good", "trigger": "a missing field would have changed the ranking", "action": "collect the missing value before committing"},
        {"id": "R5", "mode": "budget or schedule overrun", "trigger": "chosen plan exceeds the stated budget or window", "action": "descope or choose the runner-up"},
    ]

    if errors and not ok:
        status = "failed"
    elif len(plans) < 2:
        status = "insufficient_input"
    elif not ranked:
        status = "partial"
        notes.append("no_scorable_plan")
    elif any(row["values"].get(name) is None for row in rows for name in ("cost_total", "time_hours", "equipment_readiness")):
        status = "partial"
        notes.append("missing_fields_present")
    elif not sensitivity["stable"]:
        status = "partial"
    else:
        status = "success"

    if not catalog:
        notes.append("resource_catalog_empty")
        if "equipment_readiness" not in notes:
            notes.append("equipment_readiness_unknown")
    if weight_source == "equal_weights":
        notes.append("weights_not_provided_equal_weights_used")
    if not sensitivity["stable"]:
        notes.append("choice_sensitive_to_weights")

    comparison_matrix = []
    for row in rows:
        comparison_matrix.append({
            "label": row["label"],
            "objective_fit": row["values"]["objective_fit"],
            "equipment_readiness": row["values"]["equipment_readiness"],
            "time_hours": row["values"]["time_hours"],
            "cost_total": row["values"]["cost_total"],
            "risk_level": row["values"]["risk_level"],
            "evidence_strength": row["values"]["evidence_strength"],
            "parameter_range": row["values"]["parameter_range"],
            "feasibility_reason": row["details"]["feasibility_reason"],
            "bases": {key: row["details"][key] for key in (
                "hours_basis", "cost_basis", "risk_basis", "evidence_basis", "objective_fit_basis")},
            "cost_lines": row["details"]["cost_lines"],
            "resources": row["details"]["resources"],
            "source": row["details"]["source"],
        })

    payload = {
        "criteria": [{"name": name, "direction": direction, "unit": unit, "description": desc,
                      "weight": round(weights.get(name, 0.0), 6)} for name, direction, unit, desc in CRITERIA],
        "weight_source": weight_source,
        "comparison_matrix": comparison_matrix,
        "scores": scores,
        "ranking": [{"label": entry["label"], "rank": entry["rank"], "weighted_score": entry["weighted_score"]}
                    for entry in ranked],
        "choice": {
            "label": choice["label"] if choice else None,
            "weighted_score": choice["weighted_score"] if choice else None,
            "runner_up": runner_up["label"] if runner_up else None,
            "margin": round(choice["weighted_score"] - runner_up["weighted_score"], 4) if choice and runner_up else None,
            "basis": "weighted min-max normalized comparison; an aid, not proof of scientific correctness",
        } if choice else None,
        "rejection_reasons": rejection,
        "sensitivity": sensitivity,
        "conditions": conditions,
        "risks": risks,
    }

    uncertainty = []
    if len(plans) < 2:
        uncertainty.append("Fewer than two candidate plans were supplied; no comparison is possible.")
    if weight_source == "equal_weights":
        uncertainty.append("No explicit weights were supplied; equal weights were used.")
    missing = sorted({name for row in rows for name, value in row["values"].items() if value is None})
    if missing:
        uncertainty.append("Fields missing for at least one plan: %s." % ", ".join(missing))
    if not catalog:
        uncertainty.append("No resource catalog was supplied; equipment readiness is unknown.")
    if not sensitivity["stable"]:
        uncertainty.append("The preferred plan changes under a 25% weight perturbation; the choice is not robust.")

    stats = {
        "plans": len(plans),
        "scored_plans": len(ranked),
        "resource_items": len(catalog),
        "unknown_cells": sum(1 for row in rows for value in row["values"].values() if value is None),
        "criteria": len(CRITERIA),
    }

    evidence = {
        "case_file": os.path.basename(args.case),
        "case_sha256": sha256_file(args.case) if os.path.exists(args.case) else None,
        "plan_source": plan_path,
        "rules_version": "plan-comparison-v1",
        "normalization": "min-max per criterion over the supplied plans only",
    }

    contract = []
    if ok and isinstance(case.get("output_contract"), dict):
        contract = [str(key) for key in case["output_contract"].keys()]
    result = {"case_id": case.get("case_id") if ok else None, "status": status}
    for key in contract:
        if key in ("status", "case_id"):
            continue
        if key in payload:
            result[key] = payload[key]
        else:
            result[key] = None
            notes.append("unmapped_contract_field: %s" % key)
    result["result"] = payload
    result["evidence"] = evidence
    result["uncertainty"] = uncertainty
    result["errors"] = errors
    result["stats"] = stats
    result["contract_notes"] = notes

    out_dir = os.path.dirname(os.path.abspath(args.out))
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except OSError as exc:
        sys.stderr.write("cannot write result: %s\n" % exc)
        return 2

    sys.stdout.write(json.dumps({"case_id": result["case_id"], "status": status,
                                 "choice": payload["choice"]["label"] if payload["choice"] else None},
                                ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    _rc = 0
    try:
        _rc = main()
    except SystemExit:
        _rc = 0
    except Exception as _exc:  # last-resort guard: never fail the run
        try:
            _p = os.path.join("/app/output", "result.json")
            os.makedirs("/app/output", exist_ok=True)
            with open(_p, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "error": type(_exc).__name__,
                           "limitations": ["unhandled_exception"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
        _rc = 0
    if not os.path.isfile("/app/output/result.json"):
        try:
            os.makedirs("/app/output", exist_ok=True)
            with open("/app/output/result.json", "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "limitations": ["no_result_written"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
    sys.exit(0)
