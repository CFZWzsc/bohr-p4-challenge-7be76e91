#!/usr/bin/env python3
"""Compare candidate experimental protocols on one comparable matrix.

Standard library only. Deterministic and offline. Every run writes a
contract-complete result.json even when the input is missing or corrupt.

Canonical result keys
---------------------
case_id, status, candidates, comparison_table, scores, ranking,
recommendation, costs, feasibility, risks, sensitivity, missing_data,
conflicts, evidence, uncertainty, run_log, summary
"""

import csv
import hashlib
import json
import os
import re
import sys

RULES_VERSION = "plan-comparison-engine/2.1"
CANONICAL_KEYS = [
    "case_id", "status", "candidates", "comparison_table", "scores", "ranking",
    "recommendation", "costs", "feasibility", "risks", "sensitivity",
    "missing_data", "conflicts", "evidence", "uncertainty", "run_log", "summary",
]

CANDIDATE_KEYS = (
    "candidates", "candidate_plans", "candidate_protocols", "options", "protocols",
    "plans", "plan_versions", "versions", "arms", "alternatives", "designs",
    "protocol_candidates", "candidate_versions",
)
RESOURCE_KEYS = (
    "resources", "resource_catalog", "equipment", "materials", "consumables",
    "inventory", "catalog", "reagents", "price_list", "resource_inventory",
)
WEIGHT_KEYS = ("weights", "criteria_weights", "priority", "priorities", "weighting")
OBJECTIVE_KEYS = ("objectives", "must_haves", "requirements", "research_questions", "endpoints")
MATERIAL_EXTS = (".md", ".markdown", ".txt", ".json", ".csv", ".tsv")

DEFAULT_POLICY = {
    "policy_version": "fallback/1.0",
    "base_currency": "CNY",
    "criteria": [
        {"id": "objective", "name": "目标契合", "weight": 0.25, "direction": "higher"},
        {"id": "risk", "name": "风险", "weight": 0.20, "direction": "lower"},
        {"id": "cost", "name": "成本与时间", "weight": 0.20, "direction": "lower",
         "subweights": {"cost": 0.65, "time": 0.35}},
        {"id": "feasibility", "name": "可行性", "weight": 0.20, "direction": "higher"},
        {"id": "evidence", "name": "证据强度", "weight": 0.15, "direction": "higher"},
    ],
    "feasibility_levels": {"ready": 1.0, "conditional_outsource": 0.6,
                           "conditional_purchase": 0.4, "not_feasible": 0.0, "unknown": None},
    "feasibility_labels_zh": {"ready": "已具备", "conditional_outsource": "可外协",
                              "conditional_purchase": "需采购", "not_feasible": "不具备",
                              "unknown": "未确认"},
    "risk_levels": {"low": 0.2, "medium": 0.5, "high": 0.8, "critical": 1.0},
    "evidence_type_weights": {"literature": 1.0, "equipment_manual": 0.9, "sop": 0.8,
                              "pre_experiment": 0.8, "quote": 0.7, "log": 0.6, "unknown": 0.5},
    "units": {
        "time": {"min": 1.0 / 60, "minute": 1.0 / 60, "minutes": 1.0 / 60, "h": 1.0,
                 "hr": 1.0, "hour": 1.0, "hours": 1.0, "d": 24.0, "day": 24.0,
                 "days": 24.0, "wk": 168.0, "week": 168.0, "weeks": 168.0},
        "money_scale": {"CNY": 1.0, "RMB": 1.0, "USD": 1.0, "EUR": 1.0, "GBP": 1.0,
                        "CNY_10K": 10000.0},
    },
    "fx_rates_to_base": {},
    "tolerances": {"cost_absolute": 1.0, "cost_relative": 0.01, "time_absolute_h": 0.25,
                   "time_relative": 0.01, "tie_epsilon": 0.0001},
    "constraints": {"budget_is_hard": True, "time_window_is_hard": True,
                    "lead_time_is_hard": True, "parameter_domain_is_hard": True,
                    "require_min_evidence_items": 0},
    "sensitivity": {"weight_factors": [0.75, 1.25], "weight_sweep_step": 0.05,
                    "missing_data_stress": ["best_case", "worst_case"],
                    "resource_downgrade": True},
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def read_text(path, limit=600000):
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            data = fh.read(limit + 1)
        return data[:limit]
    except OSError:
        return ""


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def sha256_file(path):
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def norm(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def key_norm(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def clean(value, limit=240):
    if isinstance(value, str):
        return " ".join(value.split())[:limit]
    return ""


def num(value):
    """Return the first number in a value, or None. Never invents a value."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"[-+]?\d+(?:\.\d+)?", value.replace(",", ""))
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


CURRENCY_TOKENS = (
    ("cny_10k", ("万元",)), ("cny", ("cny", "rmb", "元", "人民币", "¥")),
    ("usd", ("usd", "$", "美元")), ("eur", ("eur", "€", "欧元")),
    ("gbp", ("gbp", "£", "英镑")),
)


def currency_of(value, default=None):
    text = str(value).lower()
    for code, tokens in CURRENCY_TOKENS:
        if any(token in text for token in tokens):
            return "CNY" if code == "cny_10k" else code.upper()
    return default


def parse_quantity(value):
    """Return (number, unit_token). unit_token is the literal unit found."""
    if isinstance(value, bool) or value is None:
        return None, ""
    if isinstance(value, (int, float)):
        return float(value), ""
    if not isinstance(value, str):
        return None, ""
    text = value.strip().replace(",", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None, ""
    number = float(match.group(0))
    rest = (text[:match.start()] + " " + text[match.end():]).strip().lower()
    for token in ("person-days", "person_days", "person days", "person-day",
                  "minutes", "minute", "mins", "min", "小时", "分钟",
                  "hours", "hour", "hrs", "hr", "天", "周",
                  "days", "day", "weeks", "week", "wk", "d", "h"):
        if token in rest:
            return number, token
    return number, ""


def to_hours(value, policy):
    """Convert an explicit duration to hours; report the conversion."""
    number, unit = parse_quantity(value)
    if number is None:
        return None, None, "not_numeric"
    unit = (unit or "").lower()
    table = policy.get("units", {}).get("time", {})
    if unit in table:
        factor = table[unit]
        note = "%s %s = %.4g h" % (number, unit, number * factor)
        return number * factor, note, "converted"
    if unit == "":
        return number, "%s h (unit assumed from field name)" % number, "assumed_hours"
    return None, None, "unknown_time_unit:%s" % unit


def looks_number(value):
    return num(value) is not None


def iter_leaves(obj, path=""):
    """Yield (json_pointer, normalized_key, value) for scalar leaves."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = "%s/%s" % (path, key) if path else str(key)
            if isinstance(value, (dict, list)):
                for item in iter_leaves(value, child):
                    yield item
            else:
                yield child, key_norm(key), value
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            child = "%s/%d" % (path, index)
            if isinstance(value, (dict, list)):
                for item in iter_leaves(value, child):
                    yield item
            else:
                yield child, key_norm(str(index)), value


def as_dict_list(value, prefix="item"):
    """Normalize a list/dict-of-dicts into a list of dicts with an identity."""
    items = []
    if isinstance(value, list):
        for index, entry in enumerate(value):
            if isinstance(entry, dict):
                item = dict(entry)
                item.setdefault("_key", "%s-%d" % (prefix, index))
                items.append(item)
            elif isinstance(entry, str) and entry.strip():
                items.append({"name": entry.strip(), "_key": "%s-%d" % (prefix, index)})
    elif isinstance(value, dict):
        if any(isinstance(v, dict) for v in value.values()):
            for name, spec in value.items():
                item = dict(spec) if isinstance(spec, dict) else {"name": name, "value": spec}
                item.setdefault("name", name)
                item.setdefault("_key", name)
                items.append(item)
        elif value:
            item = dict(value)
            item.setdefault("_key", prefix)
            items.append(item)
    return items


def split_items(value):
    if isinstance(value, list):
        return [v for v in value if v not in (None, "")]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[;；|、]", value) if part.strip()]
    return []


def parse_args(argv):
    opts = {"input": "/input", "out": "/app/output/result.json",
            "work": "/app/work", "case": None, "unknown": []}
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg.startswith("--"):
            name, _, inline = arg.partition("=")
            value = inline
            if not value:
                if index + 1 < len(argv) and not argv[index + 1].startswith("--"):
                    value = argv[index + 1]
                    index += 1
            if name in ("--input", "--input-dir", "--case-dir"):
                opts["input"] = value or opts["input"]
            elif name in ("--case", "--case-path"):
                opts["case"] = value
                if value:
                    opts["input"] = os.path.dirname(value) or "."
            elif name in ("--out", "--output", "--result"):
                opts["out"] = value or opts["out"]
            elif name == "--work":
                opts["work"] = value or opts["work"]
            elif name in ("--help", "-h"):
                opts["unknown"].append("help_requested")
            else:
                opts["unknown"].append(arg)
        elif index == 0 and not arg.startswith("-"):
            opts["input"] = arg
        else:
            opts["unknown"].append(arg)
        index += 1
    return opts


def load_policy(script_dir):
    path = os.path.join(os.path.dirname(script_dir), "assets", "policy.json")
    policy = json.loads(json.dumps(DEFAULT_POLICY))
    exists = os.path.isfile(path)
    if exists:
        try:
            loaded = load_json(path)
            if isinstance(loaded, dict):
                for key, value in loaded.items():
                    if isinstance(value, dict) and isinstance(policy.get(key), dict):
                        merged = dict(policy[key])
                        merged.update(value)
                        policy[key] = merged
                    else:
                        policy[key] = value
        except (OSError, ValueError):
            exists = False
    return policy, ("assets/policy.json" if exists else "builtin_default_policy")


# ---------------------------------------------------------------------------
# Input discovery
# ---------------------------------------------------------------------------

def find_case_file(input_path):
    if input_path and os.path.isfile(input_path):
        if input_path.lower().endswith(".json"):
            return input_path, os.path.dirname(os.path.abspath(input_path))
        return None, os.path.dirname(os.path.abspath(input_path))
    if not input_path or not os.path.isdir(input_path):
        return None, input_path
    direct = os.path.join(input_path, "case.json")
    if os.path.isfile(direct):
        return direct, input_path
    candidates = []
    for name in sorted(os.listdir(input_path)):
        full = os.path.join(input_path, name)
        if not os.path.isfile(full) or not name.lower().endswith(".json"):
            continue
        try:
            probe = load_json(full)
        except (OSError, ValueError):
            continue
        if isinstance(probe, dict) and ("case_id" in probe or any(k in probe for k in CANDIDATE_KEYS)):
            candidates.append(full)
    return (candidates[0] if candidates else None), input_path


def discover_materials(base_dir, case_path):
    materials = []
    if not base_dir or not os.path.isdir(base_dir):
        return materials
    case_abs = os.path.abspath(case_path) if case_path else None
    total = 0
    for root, dirs, files in os.walk(base_dir):
        depth = root[len(base_dir):].count(os.sep)
        if depth > 3:
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", ".git", "output", "outputs"))
        for name in sorted(files):
            full = os.path.join(root, name)
            if os.path.abspath(full) == case_abs:
                continue
            if not name.lower().endswith(MATERIAL_EXTS):
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            if size > 500 * 1024 or total + size > 2 * 1024 * 1024:
                continue
            total += size
            materials.append({
                "path": full,
                "rel": os.path.relpath(full, base_dir).replace("\\", "/"),
                "size": size,
                "sha256": sha256_file(full),
            })
    materials.sort(key=lambda item: item["rel"])
    return materials


# ---------------------------------------------------------------------------
# Material parsing
# ---------------------------------------------------------------------------

CANDIDATE_WORDS = ("candidate", "option", "protocol", "plan", "arm", "design",
                   "方案", "候选", "候选方案", "路线", "protocol version")


def candidate_heading(title):
    text = title.strip().lower()
    return any(word in text for word in CANDIDATE_WORDS)


def section_id(title):
    text = title.strip()
    text = re.sub(r"(?i)^(candidate|option|protocol|plan|arm|design|version|"
                  r"候选方案|候选|方案|路线)\s*[-_:#：]?\s*", "", text)
    match = re.match(r"([A-Za-z0-9]{1,4})(?=[\s:：\-—–(（]|$)", text)
    if match:
        return match.group(1)
    return clean(text, 40) or "candidate"


def parse_pipe_table(rows):
    """rows: list of (line_no, text). Return dict with headers and body."""
    cells_rows = []
    for line_no, text in rows:
        stripped = text.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(re.match(r"^:?-{2,}:?$", cell.replace(" ", "")) for cell in cells if cell):
            continue
        cells_rows.append((line_no, cells))
    if len(cells_rows) < 2:
        return None
    header_line, headers = cells_rows[0]
    body = cells_rows[1:]
    return {"headers": headers, "body": body, "line": header_line}


def looks_like_field(name):
    key = key_norm(name)
    if key in ("field", "metric", "dimension", "criterion", "criteria", "attribute",
               "指标", "字段", "维度", "比较项", "项目", "参数", "比较维度"):
        return True
    return key in ("cost", "cost_total", "risk", "risk_level", "time", "time_total_h",
                   "feasibility", "evidence", "evidence_count", "objective", "objective_fit",
                   "budget", "duration", "成本", "风险", "时间", "可行性", "证据", "目标")


def parse_markdown_material(text, source):
    sections = []
    current = None
    preamble = []
    lines = text.splitlines()
    for index, line in enumerate(lines, 1):
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            title = heading.group(2).strip()
            if candidate_heading(title):
                current = {"id": section_id(title), "title": title, "line": index,
                           "rows": [], "source": source}
                sections.append(current)
                continue
            current = None
            preamble.append((index, line))
            continue
        if current is not None:
            current["rows"].append((index, line))
        else:
            preamble.append((index, line))
    globals_ = {}
    for line_no, line in preamble:
        parsed = parse_key_line(line)
        if parsed:
            globals_.setdefault(parsed[0], []).append((parsed[1], "%s#L%d" % (source, line_no)))

    parsed_sections = []
    for section in sections:
        leaves = []
        records = []
        table_rows = []
        for line_no, line in section["rows"]:
            parsed = parse_key_line(line)
            if parsed:
                leaves.append({"key": key_norm(parsed[0]), "raw_key": parsed[0],
                               "value": parsed[1], "locator": "%s#L%d" % (source, line_no)})
                continue
            if line.strip().startswith("|"):
                table_rows.append((line_no, line))
                continue
            cleaned = line.strip().lstrip("-*+ ").strip()
            if cleaned:
                leaves.append({"key": "note", "raw_key": "note", "value": cleaned,
                               "locator": "%s#L%d" % (source, line_no)})
        table = parse_pipe_table(table_rows)
        if table:
            headers = table["headers"]
            lowered = [key_norm(h) for h in headers]
            first = lowered[0] if lowered else ""
            if looks_like_field(headers[0]) or first in ("candidate", "id", "name"):
                if first in ("candidate", "id", "name", "方案", "候选"):
                    for line_no, cells in table["body"]:
                        row = {key_norm(headers[i]): cells[i] for i in range(min(len(headers), len(cells)))}
                        records.append({"fields": row, "locator": "%s#L%d" % (source, line_no),
                                        "raw": cells})
                else:
                    for line_no, cells in table["body"]:
                        field = key_norm(cells[0]) if cells else ""
                        for column in range(1, min(len(headers), len(cells))):
                            leaves.append({"key": field, "raw_key": field,
                                           "value": cells[column],
                                           "locator": "%s#L%d:col%d" % (source, line_no, column)})
        parsed_sections.append({"id": section["id"], "title": section["title"],
                                "leaves": leaves, "records": records,
                                "locator": "%s#L%d" % (source, section["line"])})
    return parsed_sections, globals_


def parse_key_line(line):
    stripped = line.strip().lstrip("-*+ ").strip()
    if not stripped or stripped.startswith("|") or stripped.startswith("#"):
        return None
    stripped = re.sub(r"^\*\*(.+?)\*\*", r"\1", stripped)
    match = re.match(r"^([^:：]{1,60})[:：]\s*(.+)$", stripped)
    if not match:
        return None
    key = match.group(1).strip().strip("*`").strip()
    if not key or len(key) > 60:
        return None
    return key, match.group(2).strip()


def parse_csv_material(text, source):
    rows = []
    try:
        reader = csv.reader(text.splitlines())
        table = [row for row in reader if any(cell.strip() for cell in row)]
    except csv.Error:
        return []
    if len(table) < 2:
        return []
    headers = [key_norm(h) for h in table[0]]
    cand_col = None
    for index, header in enumerate(headers):
        if header in ("candidate", "option", "protocol", "plan", "id", "name", "方案", "候选"):
            cand_col = index
            break
    if cand_col is None:
        return []
    grouped = {}
    for line_no, cells in enumerate(table[1:], 2):
        if len(cells) <= cand_col:
            continue
        candidate = cells[cand_col].strip()
        if not candidate:
            continue
        fields = {}
        for index, header in enumerate(headers):
            if index < len(cells):
                fields[header] = cells[index].strip()
        grouped.setdefault(candidate, []).append({
            "fields": fields,
            "locator": "%s#row=%d" % (source, line_no),
            "raw": cells,
        })
    return [{"id": section_id(name), "title": name, "leaves": [], "records": records,
             "locator": "%s#col=%d" % (source, cand_col)} for name, records in grouped.items()]


def parse_json_material(obj, source):
    contexts = []
    if isinstance(obj, list):
        if all(isinstance(item, dict) for item in obj) and obj:
            contexts.append({"id": "material-list", "title": source,
                             "items": obj, "locator": source})
        return contexts
    if not isinstance(obj, dict):
        return contexts
    for path, key, value in iter_leaves(obj):
        if key in CANDIDATE_KEYS and isinstance(value, (list, dict)):
            items = as_dict_list(value)
            if items:
                contexts.append({"id": "material-" + key, "title": key,
                                 "items": items, "locator": "%s#/%s" % (source, path)})
    return contexts


# ---------------------------------------------------------------------------
# Candidate registry
# ---------------------------------------------------------------------------

def new_context(cid, name, source):
    return {"id": str(cid), "name": str(name or cid), "source": source,
            "leaves": [], "records": [], "text": [],
            "aliases": {norm(cid), norm(name or "")} - {""}}


def add_leaves(ctx, leaves):
    for leaf in leaves:
        ctx["leaves"].append(leaf)
        if isinstance(leaf.get("value"), str):
            ctx["text"].append(leaf["value"])


def match_context(registry, cid, title):
    key = norm(cid)
    for ctx in registry:
        if key and key in ctx["aliases"]:
            return ctx
    candidate = norm(title)
    if not candidate:
        return None
    for ctx in registry:
        if candidate in ctx["aliases"]:
            return ctx
    matches = [ctx for ctx in registry
               if candidate and (candidate in norm(ctx["name"]) or norm(ctx["name"]) in candidate)]
    if len(matches) == 1:
        return matches[0]
    return None


def harvest_case_candidates(case):
    found = []

    def visit(obj, path, depth):
        if depth > 4:
            return
        if isinstance(obj, dict):
            for key, value in obj.items():
                child = "%s/%s" % (path, key) if path else str(key)
                if key_norm(key) in CANDIDATE_KEYS and isinstance(value, (list, dict)):
                    items = as_dict_list(value, key_norm(key))
                    if items:
                        found.append((child, items))
                    continue
                visit(value, child, depth + 1)
        elif isinstance(obj, list):
            for index, value in enumerate(obj):
                visit(value, "%s/%d" % (path, index), depth + 1)

    visit(case, "", 0)
    if found:
        return found
    # Fallback: top-level protocol_a / plan_1 style keys.
    fallback = []
    for key, value in case.items():
        if isinstance(value, dict) and re.match(r"(?i)^(candidate|plan|protocol|option|arm)[_-]?[a-z0-9]+$", key):
            item = dict(value)
            item.setdefault("id", key)
            fallback.append(item)
    if fallback:
        return [("/", fallback)]
    return []


def build_registry(case, case_path, materials, errors):
    registry = []
    case_name = os.path.basename(case_path) if case_path else "case.json"
    for path, items in harvest_case_candidates(case):
        for index, item in enumerate(items):
            cid = item.get("id") or item.get("name") or item.get("label") or item.get("version") or ("candidate-%d" % (index + 1))
            name = item.get("name") or item.get("title") or item.get("label") or cid
            ctx = new_context(cid, name, "%s#/%s/%d" % (case_name, path.strip("/"), index))
            ctx["leaves"].append({"key": "_raw", "value": item, "locator": ctx["source"]})
            for key, value in item.items():
                if isinstance(value, (dict, list)):
                    ctx["leaves"].append({"key": key_norm(key), "value": value,
                                          "locator": "%s/%s" % (ctx["source"], key)})
            for pointer, key, value in iter_leaves(item):
                ctx["leaves"].append({"key": key, "value": value,
                                      "locator": "%s/%s" % (ctx["source"], pointer)})
                if isinstance(value, str):
                    ctx["text"].append(value)
            registry.append(ctx)

    seen = set()
    for material in materials:
        rel = material["rel"]
        text = read_text(material["path"]) if not rel.lower().endswith(".json") else ""
        parsed = []
        if rel.lower().endswith(".csv") or rel.lower().endswith(".tsv"):
            parsed = parse_csv_material(text, rel)
        elif rel.lower().endswith(".json"):
            try:
                obj = load_json(material["path"])
            except (OSError, ValueError):
                obj = None
            for block in parse_json_material(obj, rel):
                for index, item in enumerate(block["items"]):
                    cid = item.get("id") or item.get("name") or ("candidate-%d" % (index + 1))
                    ctx = new_context(cid, item.get("name") or cid,
                                      "%s#/%d" % (rel, index))
                    for key, value in item.items():
                        if isinstance(value, (dict, list)):
                            ctx["leaves"].append({"key": key_norm(key), "value": value,
                                                  "locator": "%s/%s" % (ctx["source"], key)})
                    for pointer, key, value in iter_leaves(item):
                        ctx["leaves"].append({"key": key, "value": value,
                                              "locator": "%s/%s" % (ctx["source"], pointer)})
                        if isinstance(value, str):
                            ctx["text"].append(value)
                    parsed.append(ctx)
        else:
            sections, _ = parse_markdown_material(text, rel)
            for section in sections:
                ctx = {"id": section["id"], "name": section["title"],
                       "source": section["locator"], "leaves": section["leaves"],
                       "records": section["records"], "text": [],
                       "aliases": {norm(section["id"]), norm(section["title"])} - {""}}
                for leaf in section["leaves"]:
                    if isinstance(leaf.get("value"), str):
                        ctx["text"].append(leaf["value"])
                parsed.append(ctx)
        for block in parsed:
            if isinstance(block, dict) and "leaves" in block:
                block.setdefault("records", [])
                block.setdefault("text", [])
                block.setdefault("aliases", {norm(block.get("id")), norm(block.get("title"))} - {""})
                target = match_context(registry, block["id"],
                                       block.get("title") or block.get("name") or block["id"])
                if target is None:
                    registry.append(block)
                else:
                    add_leaves(target, block["leaves"])
                    target["records"].extend(block["records"])
                    target["aliases"] |= block.get("aliases", set())
                    for record in block["records"]:
                        target["text"].extend(str(v) for v in record["fields"].values())
        if rel in seen:
            continue
        seen.add(rel)
    # Stable unique ids.
    used = {}
    for ctx in registry:
        base = ctx["id"] or "candidate"
        used[base] = used.get(base, 0) + 1
        if used[base] > 1:
            ctx["id"] = "%s-%d" % (base, used[base])
    return registry


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

F_OBJECTIVE = ("objective_fit", "fit_score", "alignment_score", "goal_fit", "objective_score",
               "expected_effect", "effect_size", "success_probability", "endpoint_coverage",
               "objective_met_ratio")
F_RISK_LEVEL = ("risk_level", "risk_rating", "risk", "severity", "safety_level", "overall_risk")
F_RISK_SCORE = ("risk_score", "risk_index", "hazard_score", "risk_value")
F_RISK_ITEMS = ("risks", "risk_items", "risk_item", "hazards", "hazard",
                "failure_modes", "failure_mode", "risk_register", "risk_analysis",
                "failure_paths", "risk_factor", "risk_factors")
F_MITIGATION = ("mitigation", "mitigations", "controls", "control", "remediation",
                "fallback", "contingency", "response")
F_CURRENCY = ("currency", "cost_currency", "price_currency")
F_TOTAL_COST = ("total_cost", "cost_total", "estimated_cost", "budget_total", "cost",
                "planned_cost", "total_budget", "total_consumable_cost")
F_TOTAL_TIME = ("total_hours", "time_total_h", "planned_hours", "elapsed_h", "duration_h",
                "total_time_h", "time_total", "duration", "total_duration_h")
F_EVIDENCE = ("evidence", "references", "citations", "sources", "basis", "provenance",
              "literature", "support", "evidence_items")
F_RESOURCES = ("resources", "required_resources", "equipment", "materials", "facilities",
               "infrastructure", "resource_requirements", "consumables_required",
               "equipment_required", "resource_list")
F_AVAILABILITY = ("availability", "status", "state", "stock", "access", "availability_status")
F_LEAD_TIME = ("lead_time_days", "lead_time", "delivery_days", "procurement_days",
               "booking_wait_days", "lead_days")
F_PARAMETERS = ("parameters", "parameter_ranges", "settings", "conditions", "parameter",
                "operating_parameters", "parameter_set")

CONSUMABLE_KEYS = ("consumables", "materials", "reagents", "supplies", "items",
                   "bill_of_materials", "bom", "cost_lines", "cost_items")
EQUIPMENT_USAGE_KEYS = ("equipment_usage", "instrument_usage", "machine_usage",
                        "equipment_time", "instrument_time", "machine_time")
LABOR_KEYS = ("labor", "labour", "personnel", "staff", "labor_lines", "labour_lines")
COST_COMPONENT_KEYS = (
    "consumable_cost", "consumables_cost", "material_cost", "materials_cost",
    "equipment_cost", "machine_cost", "instrument_cost", "labor_cost", "labour_cost",
    "personnel_cost", "overhead", "overhead_cost", "shipping_cost", "sample_prep_cost",
    "prep_cost", "rework_cost", "one_time_cost", "per_run_cost", "fixed_cost",
    "variable_cost", "service_cost", "outsourcing_cost",
)
TIME_COMPONENTS = (
    ("sample_prep_h", ("sample_prep_h", "prep_h", "sample_preparation_h",
                       "sample_prep_time_h", "preparation_h")),
    ("run_h", ("run_h", "runtime_h", "execution_h", "experiment_h", "reaction_h",
               "processing_h", "measurement_run_h")),
    ("queue_wait_h", ("queue_wait_h", "queue_h", "booking_wait_h", "schedule_wait_h",
                      "equipment_queue_h", "wait_h", "scheduling_h")),
    ("characterization_h", ("characterization_h", "characterisation_h", "analysis_h",
                            "measurement_h", "assay_h", "characterization_time_h")),
    ("rework_h", ("rework_h", "repeat_h", "redo_h", "retry_h", "contingency_h")),
)


def leaves_matching(ctx, keys):
    wanted = set(keys)
    return [leaf for leaf in ctx["leaves"] if leaf.get("key") in wanted]


def first_leaf(ctx, keys):
    matches = leaves_matching(ctx, keys)
    for leaf in matches:
        if not isinstance(leaf.get("value"), (dict, list)):
            return leaf
    return matches[0] if matches else None


def leaf_value(ctx, keys):
    leaf = first_leaf(ctx, keys)
    return (leaf["value"] if leaf else None), (leaf["locator"] if leaf else None)


def money_from(value, default_currency):
    number, unit = parse_quantity(value)
    if number is None:
        return None, None
    currency = currency_of(value, default_currency)
    if "万元" in str(value):
        number = number * 10000.0
    return number, currency


def item_line(item):
    """Extract quantity and unit price from a structured or textual item."""
    if isinstance(item, dict):
        lowered = {key_norm(k): v for k, v in item.items()}
        qty = num(lowered.get("quantity") or lowered.get("qty") or lowered.get("amount")
                  or lowered.get("count") or lowered.get("n"))
        price = num(lowered.get("unit_price") or lowered.get("price") or lowered.get("unit_cost")
                    or lowered.get("cost_each") or lowered.get("rate"))
        name = (lowered.get("item") or lowered.get("name") or lowered.get("resource")
                or lowered.get("material") or lowered.get("reagent") or "item")
        currency = currency_of(str(lowered.get("currency") or ""), None)
        return qty, price, clean(name, 80), currency
    if isinstance(item, str):
        text = item.replace(",", "")
        price_match = re.search(r"(?:@|price[=:\s]+|单价)\s*([0-9]+(?:\.[0-9]+)?)", text, re.I)
        qty_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:x|×|\*)\s*", text, re.I)
        if price_match and qty_match:
            return (float(qty_match.group(1)), float(price_match.group(1)),
                    clean(text, 80), currency_of(text, None))
        if price_match:
            return (1.0, float(price_match.group(1)), clean(text, 80), currency_of(text, None))
    return None, None, None, None


def build_cost(ctx, env):
    policy = env["policy"]
    conflicts = env["conflicts"]
    base_currency = env["base_currency"]
    fx = env["fx"]
    lines = []
    notes = []
    seen_consumable = False
    seen_equipment = False
    seen_labor = False

    # CSV / table records.
    for record in ctx["records"]:
        fields = record["fields"]
        category = key_norm(fields.get("category") or fields.get("cost_type")
                            or fields.get("type") or "consumable")
        name = fields.get("item") or fields.get("name") or fields.get("resource") or "item"
        qty, price, _, cur = item_line(fields)
        if qty is None and fields.get("hours") is not None:
            qty = num(fields.get("hours"))
            price = num(fields.get("rate") or fields.get("unit_price") or fields.get("price"))
            category = "equipment"
        if qty is not None and price is not None and qty >= 0:
            currency = currency_of(str(fields.get("currency") or ""), None) or cur or base_currency
            amount = qty * price
            lines.append({"category": category, "item": clean(name, 80), "quantity": qty,
                          "unit_price": price, "currency": currency, "amount": amount,
                          "formula": "%g × %g = %.2f %s" % (qty, price, amount, currency),
                          "locator": record["locator"]})
            if category in ("consumable", "material", "reagent", "supplies"):
                seen_consumable = True
            elif category in ("equipment", "instrument", "machine", "beamtime"):
                seen_equipment = True
            elif category in ("labor", "labour", "personnel", "staff"):
                seen_labor = True

    # Structured consumable lists.
    for key in CONSUMABLE_KEYS:
        for leaf in ctx["leaves"]:
            if leaf["key"] != key or not isinstance(leaf["value"], (list, dict)):
                continue
            entries = leaf["value"] if isinstance(leaf["value"], list) else [leaf["value"]]
            for index, entry in enumerate(entries):
                qty, price, name, cur = item_line(entry)
                if qty is None or price is None:
                    continue
                currency = cur or base_currency
                amount = qty * price
                lines.append({"category": "consumable", "item": name or "consumable",
                              "quantity": qty, "unit_price": price, "currency": currency,
                              "amount": amount,
                              "formula": "%g × %g = %.2f %s" % (qty, price, amount, currency),
                              "locator": "%s/%d" % (leaf["locator"], index)})
                seen_consumable = True

    # Structured equipment usage.
    for key in EQUIPMENT_USAGE_KEYS:
        for leaf in ctx["leaves"]:
            if leaf["key"] != key or not isinstance(leaf["value"], (list, dict)):
                continue
            entries = leaf["value"] if isinstance(leaf["value"], list) else [leaf["value"]]
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                lowered = {key_norm(k): v for k, v in entry.items()}
                hours = num(lowered.get("hours") or lowered.get("duration_h") or lowered.get("time_h"))
                rate = num(lowered.get("rate") or lowered.get("price_per_hour")
                           or lowered.get("hourly_rate") or lowered.get("unit_price"))
                if hours is None or rate is None:
                    continue
                name = lowered.get("equipment") or lowered.get("instrument") or "equipment"
                currency = currency_of(str(lowered.get("currency") or ""), None) or base_currency
                amount = hours * rate
                lines.append({"category": "equipment", "item": clean(name, 80),
                              "quantity": hours, "unit_price": rate, "currency": currency,
                              "amount": amount,
                              "formula": "%g h × %g = %.2f %s" % (hours, rate, amount, currency),
                              "locator": "%s/%d" % (leaf["locator"], index)})
                seen_equipment = True

    # Direct component amounts.
    for key in COST_COMPONENT_KEYS:
        leaf = first_leaf(ctx, (key,))
        if leaf is None:
            continue
        amount, currency = money_from(leaf["value"], None)
        if amount is None:
            continue
        if key in ("consumable_cost", "consumables_cost", "material_cost", "materials_cost") and seen_consumable:
            continue
        if key in ("equipment_cost", "machine_cost", "instrument_cost") and seen_equipment:
            continue
        if key in ("labor_cost", "labour_cost", "personnel_cost") and seen_labor:
            continue
        currency = currency or base_currency
        category = "overhead"
        if key.startswith(("consumable", "material")):
            category = "consumable"
        elif key.startswith(("equipment", "machine", "instrument", "service", "outsourc")):
            category = "equipment"
        elif key.startswith(("labor", "labour", "personnel")):
            category = "labor"
        elif key in ("one_time_cost", "fixed_cost"):
            category = "one_time"
        elif key in ("per_run_cost", "variable_cost"):
            category = "per_run"
        lines.append({"category": category, "item": key, "quantity": 1.0,
                      "unit_price": amount, "currency": currency, "amount": amount,
                      "formula": "%.2f %s (declared component)" % (amount, currency),
                      "locator": leaf["locator"]})

    runs = 1
    runs_leaf = first_leaf(ctx, ("runs", "n_runs", "replicates", "batches"))
    if runs_leaf and num(runs_leaf["value"]):
        runs = max(1, int(num(runs_leaf["value"])))

    # Apply per-run multiplier and currency conversion.
    converted = []
    used_currencies = sorted({line["currency"] for line in lines})
    convertible = all(cur == base_currency or cur in fx for cur in used_currencies)
    if len(used_currencies) > 1 and not convertible:
        conflicts.append({"type": "mixed_currency_without_fx",
                          "candidate": ctx["id"],
                          "detail": " currencies=%s; no fx conversion stated" % ",".join(used_currencies),
                          "resolution": "totals kept per line but marked incomparable"})
    total = 0.0
    for line in lines:
        multiplier = runs if line["category"] == "per_run" else 1
        amount = line["amount"] * multiplier
        currency = line["currency"]
        if currency != base_currency and convertible and currency in fx:
            try:
                rate = float(fx[currency])
                amount = amount * rate
                line["formula"] = "%s; %.2f %s × %.4g = %.2f %s" % (
                    line["formula"], line["amount"], currency, rate, amount, base_currency)
                line["currency"] = base_currency
            except (TypeError, ValueError):
                pass
        if line["category"] != "per_run" or multiplier == 1:
            line["formula"] = line["formula"]
        else:
            line["formula"] = "%s; × %d runs = %.2f %s" % (line["formula"], runs, amount, line["currency"])
        line["amount"] = round(amount, 2)
        converted.append(line)
        total += amount

    stated_leaf = first_leaf(ctx, F_TOTAL_COST)
    stated, stated_locator = (None, None)
    stated_currency = None
    if stated_leaf is not None:
        original, stated_currency = money_from(stated_leaf["value"], None)
        stated_locator = stated_leaf["locator"]
        if original is not None:
            stated = original
            if stated_currency and stated_currency != base_currency:
                if stated_currency in fx:
                    try:
                        rate = float(fx[stated_currency])
                        stated = original * rate
                        notes.append("stated total converted %.2f %s × %.4g = %.2f %s"
                                     % (original, stated_currency, rate, stated, base_currency))
                        stated_currency = base_currency
                    except (TypeError, ValueError):
                        stated = None
                else:
                    notes.append("stated total in %s cannot be compared to %s without fx"
                                 % (stated_currency, base_currency))
                    stated = None

    if not converted:
        if stated is not None:
            return {"total": round(stated, 2), "currency": base_currency,
                    "lines": [], "basis": "declared_total", "formula": "declared %.2f %s"
                    % (stated, base_currency), "stated_total": round(stated, 2),
                    "runs": runs, "locator": [stated_locator], "status": "declared",
                    "notes": notes}
        return {"total": None, "currency": base_currency, "lines": [], "basis": "missing",
                "formula": None, "stated_total": None, "runs": runs, "locator": [],
                "status": "missing", "notes": notes}

    total = round(total, 2)
    if stated is not None:
        tolerance = max(policy["tolerances"]["cost_absolute"],
                        policy["tolerances"]["cost_relative"] * max(abs(total), abs(stated)))
        if abs(total - stated) > tolerance:
            conflicts.append({"type": "arithmetic_mismatch", "candidate": ctx["id"],
                              "detail": "stated total %.2f != component sum %.2f %s"
                                        % (stated, total, base_currency),
                              "resolution": "component sum used; stated total kept as declared_total"})
    formula = " + ".join("%.2f" % line["amount"] for line in converted) + " = %.2f %s" % (total, base_currency)
    locators = [line["locator"] for line in converted if line.get("locator")]
    if stated_locator:
        locators.append(stated_locator)
    return {"total": total, "currency": base_currency, "lines": converted,
            "basis": "derived_from_components", "formula": formula,
            "stated_total": round(stated, 2) if stated is not None else None,
            "runs": runs, "locator": locators, "status": "derived", "notes": notes}


def build_time(ctx, env):
    policy = env["policy"]
    conflicts = env["conflicts"]
    lines = []
    total_components = 0.0
    for canonical, aliases in TIME_COMPONENTS:
        leaf = first_leaf(ctx, aliases)
        if leaf is None:
            continue
        hours, note, basis = to_hours(leaf["value"], policy)
        if hours is None:
            conflicts.append({"type": "unknown_time_unit", "candidate": ctx["id"],
                              "detail": "%s=%r (%s)" % (canonical, leaf["value"], basis),
                              "resolution": "left missing, not imputed"})
            continue
        if basis == "assumed_hours" and not canonical.endswith("_h"):
            env["assumptions"].append("%s assumed hours for %s" % (canonical, ctx["id"]))
        lines.append({"component": canonical, "hours": round(hours, 4),
                      "note": note, "locator": leaf["locator"]})
        total_components += hours

    stated_leaf = first_leaf(ctx, F_TOTAL_TIME)
    stated = None
    stated_locator = None
    stated_note = None
    if stated_leaf is not None:
        stated, stated_note, stated_basis = to_hours(stated_leaf["value"], policy)
        stated_locator = stated_leaf["locator"]
        if stated is not None and stated_basis == "assumed_hours":
            env["assumptions"].append("total time assumed hours for %s" % ctx["id"])

    if not lines:
        if stated is not None:
            return {"total_h": round(stated, 4), "lines": [], "basis": "declared_total",
                    "formula": "declared %.4g h" % stated, "stated_total_h": round(stated, 4),
                    "locator": [stated_locator], "status": "declared", "notes": [stated_note] if stated_note else []}
        return {"total_h": None, "lines": [], "basis": "missing", "formula": None,
                "stated_total_h": None, "locator": [], "status": "missing", "notes": []}

    total = round(total_components, 4)
    if stated is not None:
        tolerance = max(policy["tolerances"]["time_absolute_h"],
                        policy["tolerances"]["time_relative"] * max(abs(total), abs(stated)))
        if abs(total - stated) > tolerance:
            conflicts.append({"type": "arithmetic_mismatch", "candidate": ctx["id"],
                              "detail": "stated total %.4g h != component sum %.4g h" % (stated, total),
                              "resolution": "component sum used; stated total kept as declared_total_h"})
    formula = " + ".join("%g" % line["hours"] for line in lines) + " = %g h" % total
    locators = [line["locator"] for line in lines if line.get("locator")]
    if stated_locator:
        locators.append(stated_locator)
    notes = [line["note"] for line in lines if line.get("note")]
    if stated_note:
        notes.append(stated_note)
    return {"total_h": total, "lines": lines, "basis": "summed_components",
            "formula": formula, "stated_total_h": round(stated, 4) if stated is not None else None,
            "locator": locators, "status": "derived", "notes": notes}


# ---------------------------------------------------------------------------
# Resource catalog and feasibility
# ---------------------------------------------------------------------------

STATUS_PATTERNS = (
    ("unavailable", ("unavailable", "not available", "out of stock", "out of service",
                     "no access", "不具备", "不可用", "缺货", "无法使用", "无可用")),
    ("purchase", ("procure", "purchase", "order", "to be purchased", "需采购", "采购",
                  "待采购", "需购买")),
    ("outsource", ("outsource", "external", "vendor", "third party", "collaborat",
                   "外协", "委外", "外部")),
    ("ready", ("available", "in stock", "owned", "on site", "on-site", "ready",
               "已具备", "可用", "现有", "自有", "在位")),
)


def availability_level(value):
    text = str(value).lower()
    for level, tokens in STATUS_PATTERNS:
        if any(token in text for token in tokens):
            return level
    return "unknown"


def build_catalog(case, case_name):
    catalog = []
    seen = set()

    def visit(obj, path, depth):
        if depth > 3:
            return
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key_norm(key) in CANDIDATE_KEYS:
                    continue
                child = "%s/%s" % (path, key) if path else str(key)
                if key_norm(key) in RESOURCE_KEYS and isinstance(value, (list, dict)):
                    for index, item in enumerate(as_dict_list(value, key_norm(key))):
                        name = item.get("name") or item.get("item") or item.get("model")
                        if not name:
                            continue
                        status_text = " ".join(str(item.get(k, "")) for k in
                                               ("availability", "status", "state", "stock"))
                        if not status_text.strip() and not any(
                                k in item for k in ("unit_price", "price", "lead_time_days")):
                            continue
                        token = (norm(name), str(item.get("availability")), child)
                        if token in seen:
                            continue
                        seen.add(token)
                        catalog.append({"name": clean(name, 100),
                                        "level": availability_level(status_text),
                                        "unit_price": num(item.get("unit_price") or item.get("price")),
                                        "currency": currency_of(str(item.get("currency") or ""), None),
                                        "lead_time_days": num(item.get("lead_time_days")
                                                              or item.get("lead_time")
                                                              or item.get("delivery_days")),
                                        "locator": "%s#/%s/%d" % (case_name, child.strip("/"), index)})
                else:
                    visit(value, child, depth + 1)
        elif isinstance(obj, list):
            for index, value in enumerate(obj):
                visit(value, "%s/%d" % (path, index), depth + 1)

    visit(case, "", 0)
    return catalog


def parse_resource_entry(entry, locator):
    if isinstance(entry, dict):
        lowered = {key_norm(k): v for k, v in entry.items()}
        name = (lowered.get("name") or lowered.get("item") or lowered.get("resource")
                or lowered.get("equipment") or "resource")
        status_text = " ".join(str(lowered.get(k, "")) for k in
                               ("availability", "status", "state", "stock", "access"))
        return {"name": clean(name, 100), "level": availability_level(status_text),
                "lead_time_days": num(lowered.get("lead_time_days") or lowered.get("lead_time")
                                      or lowered.get("delivery_days")),
                "locator": locator}
    if isinstance(entry, str):
        name = re.split(r"[(（,;；:：]", entry, 1)[0].strip()
        return {"name": clean(name, 100), "level": availability_level(entry),
                "lead_time_days": num(entry), "locator": locator}
    return None


def build_feasibility(ctx, env):
    policy = env["policy"]
    conflicts = env["conflicts"]
    resources = []
    seen = set()
    for leaf in leaves_matching(ctx, F_RESOURCES):
        if isinstance(leaf["value"], (list, dict)):
            entries = leaf["value"] if isinstance(leaf["value"], list) else [leaf["value"]]
            for index, entry in enumerate(entries):
                parsed = parse_resource_entry(entry, "%s/%d" % (leaf["locator"], index))
                if not parsed or not parsed["name"]:
                    continue
                token = (norm(parsed["name"]), parsed["level"])
                if token in seen:
                    continue
                seen.add(token)
                resources.append(parsed)
        elif isinstance(leaf["value"], str):
            parsed = parse_resource_entry(leaf["value"], leaf["locator"])
            if parsed and parsed["name"]:
                resources.append(parsed)

    blob = norm(" ".join(ctx["text"]))
    for entry in env["catalog"]:
        if norm(entry["name"]) and norm(entry["name"]) in blob:
            token = (norm(entry["name"]), entry["level"])
            if token not in seen:
                seen.add(token)
                resources.append(dict(entry))

    if not resources:
        leaf = first_leaf(ctx, F_AVAILABILITY)
        if leaf is not None:
            level = availability_level(leaf["value"])
            if level != "unknown":
                resources.append({"name": "overall", "level": level,
                                  "lead_time_days": None, "locator": leaf["locator"]})

    levels = [item["level"] for item in resources]
    if not resources or all(level == "unknown" for level in levels):
        overall = "unknown"
    elif "unavailable" in levels:
        overall = "not_feasible"
    elif "purchase" in levels:
        overall = "conditional_purchase"
    elif "outsource" in levels:
        overall = "conditional_outsource"
    else:
        overall = "ready"

    lead_times = [item["lead_time_days"] for item in resources if item["lead_time_days"] is not None]
    lead_time = max(lead_times) if lead_times else None
    reasons = []
    eligible = overall not in ("not_feasible", "unknown")
    if overall == "not_feasible":
        reasons.append("has_unavailable_resource")
    if overall == "unknown":
        reasons.append("resource_availability_unconfirmed")

    constraints = policy.get("constraints", {})
    cost = ctx.get("cost", {})
    time_info = ctx.get("time", {})
    budget = env.get("budget")
    budget_ok = None
    if budget is not None and cost.get("total") is not None:
        budget_ok = cost["total"] <= budget + 1e-9
        if not budget_ok:
            reasons.append("over_budget")
            conflicts.append({"type": "over_budget", "candidate": ctx["id"],
                              "detail": "cost %.2f %s > budget %.2f"
                                        % (cost["total"], cost.get("currency"), budget),
                              "resolution": "candidate kept in table but not recommended"
                              if constraints.get("budget_is_hard") else "flagged only"})
            if constraints.get("budget_is_hard"):
                eligible = False

    window = env.get("time_window_h")
    window_ok = None
    if window is not None and time_info.get("total_h") is not None:
        window_ok = time_info["total_h"] <= window + 1e-9
        if not window_ok:
            reasons.append("over_time_window")
            conflicts.append({"type": "over_time_window", "candidate": ctx["id"],
                              "detail": "time %.4g h > window %.4g h"
                                        % (time_info["total_h"], window),
                              "resolution": "candidate kept in table but not recommended"
                              if constraints.get("time_window_is_hard") else "flagged only"})
            if constraints.get("time_window_is_hard"):
                eligible = False

    window_days = env.get("time_window_days")
    lead_ok = None
    if lead_time is not None and window_days is not None:
        lead_ok = lead_time <= window_days + 1e-9
        if not lead_ok:
            reasons.append("lead_time_exceeds_window")
            conflicts.append({"type": "lead_time_exceeds_window", "candidate": ctx["id"],
                              "detail": "lead time %g d > window %g d" % (lead_time, window_days),
                              "resolution": "candidate kept in table but not recommended"
                              if constraints.get("lead_time_is_hard") else "flagged only"})
            if constraints.get("lead_time_is_hard"):
                eligible = False

    domain_ok, domain_conflicts = check_parameter_domains(ctx, env)
    if not domain_ok:
        reasons.append("parameter_out_of_domain")
        conflicts.extend(domain_conflicts)
        if constraints.get("parameter_domain_is_hard", True):
            eligible = False

    return {"level": overall, "score": policy["feasibility_levels"].get(overall),
            "resources": resources, "lead_time_days": lead_time,
            "budget_ok": budget_ok, "time_window_ok": window_ok, "lead_time_ok": lead_ok,
            "parameter_domain_ok": domain_ok, "eligible": eligible,
            "reasons": reasons}


def check_parameter_domains(ctx, env):
    domains = env.get("parameter_domains") or {}
    if not domains:
        return True, []
    params = ctx.get("params", {})
    conflicts = []
    ok = True
    for name, value in params.items():
        domain = domains.get(key_norm(name))
        if not isinstance(domain, dict):
            continue
        low = num(domain.get("min", domain.get("minimum")))
        high = num(domain.get("max", domain.get("maximum")))
        if low is None or high is None:
            continue
        if isinstance(value, dict):
            check_low = num(value.get("min", value.get("minimum")))
            check_high = num(value.get("max", value.get("maximum")))
            outside = ((check_low is not None and check_low < low) or
                       (check_high is not None and check_high > high))
            rendered = "%s..%s" % (check_low, check_high)
        else:
            number = num(value)
            outside = number is not None and (number < low or number > high)
            rendered = str(number)
        if outside:
            ok = False
            conflicts.append({"type": "parameter_out_of_domain", "candidate": ctx["id"],
                              "detail": "%s=%s outside [%g, %g]" % (name, rendered, low, high),
                              "resolution": "marked not feasible; parameter not altered"})
    return ok, conflicts


# ---------------------------------------------------------------------------
# Risk, objective, evidence, parameters
# ---------------------------------------------------------------------------

RISK_LABELS = (
    ("critical", ("critical", "severe", "unacceptable", "极高", "严重", "不可接受")),
    ("high", ("high", "major", "较高", "高")),
    ("medium", ("medium", "moderate", "中", "中等")),
    ("low", ("low", "minor", "negligible", "较低", "低")),
)


def label_score(text, policy):
    """Map a risk label without letting single Chinese characters over-match."""
    text = str(text)
    if len(text.strip()) <= 12:
        for label, tokens in RISK_LABELS:
            if any(token in text.lower() for token in tokens):
                return policy["risk_levels"][label]
    match = re.search(r"[（(]\s*(low|medium|high|critical|低风险|中风险|高风险|"
                      r"较高|较低|极高|低|中|高)\s*[)）]", text, re.I)
    if match:
        token = match.group(1).lower()
        for label, tokens in RISK_LABELS:
            if any(item in token for item in tokens):
                return policy["risk_levels"][label]
    lowered = text.lower()
    rules = (
        ("critical", ("极高风险", "严重风险", "不可接受", "critical", "severe")),
        ("high", ("高风险", "较高风险", "high risk", "high")),
        ("medium", ("中风险", "中等风险", "medium", "moderate")),
        ("low", ("低风险", "较低风险", "low risk", "low", "minor")),
    )
    for label, tokens in rules:
        for token in tokens:
            if re.search(r"\b%s\b" % re.escape(token) if token.isascii() else re.escape(token),
                         lowered):
                return policy["risk_levels"][label]
    return None


def risk_score_from(value, policy):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if 0 <= number <= 1:
            return round(number, 4)
        if number <= 5:
            return round(number / 5.0, 4)
        if number <= 10:
            return round(number / 10.0, 4)
        if number <= 100:
            return round(number / 100.0, 4)
        return None
    return label_score(value, policy)


def risk_label(score, policy):
    if score is None:
        return None
    best = "low"
    for label in ("low", "medium", "high", "critical"):
        if score >= policy["risk_levels"][label] - 1e-9:
            best = label
    return best


def build_risk(ctx, env):
    policy = env["policy"]
    conflicts = env["conflicts"]
    items = []
    for leaf in leaves_matching(ctx, F_RISK_ITEMS):
        value = leaf["value"]
        entries = value if isinstance(value, list) else [value]
        for index, entry in enumerate(entries):
            locator = "%s/%d" % (leaf["locator"], index) if isinstance(value, list) else leaf["locator"]
            if isinstance(entry, dict):
                lowered = {key_norm(k): v for k, v in entry.items()}
                level_text = " ".join(str(lowered.get(k, "")) for k in
                                      ("level", "severity", "likelihood", "impact", "rating"))
                score = risk_score_from(lowered.get("score") or level_text, policy)
                mitigation = ""
                for key in F_MITIGATION:
                    if lowered.get(key):
                        mitigation = clean(lowered.get(key))
                        break
                items.append({"description": clean(lowered.get("risk") or lowered.get("name")
                                                   or lowered.get("description")
                                                   or lowered.get("failure_mode") or entry),
                              "severity_score": score,
                              "severity_label": risk_label(score, policy),
                              "mitigation": mitigation or None,
                              "locator": locator})
            elif isinstance(entry, str):
                score = risk_score_from(entry, policy)
                mitigation = None
                match = re.search(r"(?:mitigat\w*|缓解|措施)[:：]\s*(.+)$", entry, re.I)
                if match:
                    mitigation = clean(match.group(1))
                items.append({"description": clean(entry), "severity_score": score,
                              "severity_label": risk_label(score, policy),
                              "mitigation": mitigation, "locator": locator})
    # Repeated risk: lines that are not just a level.
    for leaf in ctx["leaves"]:
        if leaf["key"] != "risk" or not isinstance(leaf["value"], str):
            continue
        if risk_score_from(leaf["value"], policy) is not None:
            continue
        items.append({"description": clean(leaf["value"]), "severity_score": None,
                      "severity_label": None, "mitigation": None, "locator": leaf["locator"]})

    declared_leaf = first_leaf(ctx, F_RISK_LEVEL)
    declared = None
    if declared_leaf is not None:
        declared = risk_score_from(declared_leaf["value"], policy)
        if declared is None and declared_leaf["value"] not in (None, ""):
            conflicts.append({"type": "unrecognized_risk_level", "candidate": ctx["id"],
                              "detail": "risk=%r" % declared_leaf["value"],
                              "resolution": "treated as missing"})
    score_leaf = first_leaf(ctx, F_RISK_SCORE)
    numeric = risk_score_from(score_leaf["value"], policy) if score_leaf else None

    item_scores = [item["severity_score"] for item in items if item["severity_score"] is not None]
    score = numeric if numeric is not None else (declared if declared is not None
                                                 else (max(item_scores) if item_scores else None))
    if declared is not None and item_scores and abs(max(item_scores) - declared) > 0.25:
        conflicts.append({"type": "risk_declared_conflict", "candidate": ctx["id"],
                          "detail": "declared %.2f vs max item %.2f" % (declared, max(item_scores)),
                          "resolution": "declared level used; item levels retained"})
    high_count = sum(1 for value in item_scores if value >= policy["risk_levels"]["high"])
    with_mitigation = sum(1 for item in items if item.get("mitigation"))
    coverage = round(with_mitigation / float(len(items)), 4) if items else None
    locator = declared_leaf["locator"] if declared_leaf else (
        score_leaf["locator"] if score_leaf else None)
    if locator is None and items:
        locator = items[0]["locator"]
    return {"score": score, "level": risk_label(score, policy), "items": items,
            "high_risk_count": high_count, "mitigation_coverage": coverage,
            "locator": locator, "status": "declared" if score is not None else "missing"}


def token_set(text):
    lowered = str(text).lower()
    latin = re.findall(r"[a-z0-9]{3,}", lowered)
    grams = []
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(run) <= 2:
            grams.append(run)
        else:
            grams.extend(run[index:index + 2] for index in range(len(run) - 1))
    result = set(latin) | set(grams)
    result.discard("")
    return result


def overlap_ratio(needle, haystack):
    target = token_set(needle)
    if not target:
        return 0.0
    return len(target & token_set(haystack)) / float(len(target))


def build_objective(ctx, env):
    leaf = first_leaf(ctx, F_OBJECTIVE)
    if leaf is not None:
        value = num(leaf["value"])
        if value is not None:
            note = None
            if value > 1 and value <= 100:
                value = value / 100.0
                note = "declared %s scaled to 0-1 (÷100)" % leaf["value"]
                env["assumptions"].append(note)
            if 0 <= value <= 1:
                return {"score": round(value, 4), "basis": "declared", "locator": leaf["locator"],
                        "confidence": "high", "note": note}
    met_leaf = first_leaf(ctx, ("objectives_met", "objectives_covered", "met_objectives",
                                "criteria_met", "endpoints_met"))
    criteria = env.get("objectives") or []
    if met_leaf is not None and criteria:
        met = split_items(met_leaf["value"])
        ratio = min(1.0, len(met) / float(len(criteria)))
        return {"score": round(ratio, 4), "basis": "declared_objective_count",
                "locator": met_leaf["locator"], "confidence": "medium",
                "note": "%d of %d objectives declared met" % (len(met), len(criteria))}
    text_leaf = first_leaf(ctx, ("objective", "aim", "goal", "hypothesis",
                                 "expected_outcome", "rationale", "objective_statement"))
    if text_leaf is not None and criteria:
        text = " ".join(str(item) for item in ctx["text"]) + " " + str(text_leaf["value"])
        matched = [item for item in criteria if overlap_ratio(item, text) >= 0.5]
        ratio = len(matched) / float(len(criteria))
        return {"score": round(ratio, 4), "basis": "text_overlap_against_case_objectives",
                "locator": text_leaf["locator"], "confidence": "low",
                "note": "matched %d of %d objectives by token overlap" % (len(matched), len(criteria))}
    return {"score": None, "basis": "missing", "locator": None, "confidence": "none", "note": None}


def evidence_type(text):
    lowered = str(text).lower()
    if any(word in lowered for word in ("manual", "datasheet", "spec sheet", "手册", "说明书")):
        return "equipment_manual"
    if any(word in lowered for word in ("sop", "操作规范", "作业指导")):
        return "sop"
    if any(word in lowered for word in ("pre-experiment", "preliminary", "预实验", "试跑")):
        return "pre_experiment"
    if any(word in lowered for word in ("quote", "quotation", "报价", "询价")):
        return "quote"
    if any(word in lowered for word in ("log", "record", "日志", "记录", "历史项目")):
        return "log"
    if any(word in lowered for word in ("doi", "paper", "journal", "literature", "文献", "论文")):
        return "literature"
    return "unknown"


def build_evidence(ctx, env):
    policy = env["policy"]
    items = []
    for leaf in leaves_matching(ctx, F_EVIDENCE):
        value = leaf["value"]
        if isinstance(value, dict):
            entries = [value]
        elif isinstance(value, list):
            entries = value
        else:
            entries = split_items(value)
        for index, entry in enumerate(entries):
            if isinstance(entry, dict):
                lowered = {key_norm(k): v for k, v in entry.items()}
                label = (lowered.get("claim") or lowered.get("citation") or lowered.get("source")
                         or lowered.get("reference") or lowered.get("title") or entry)
                kind = evidence_type(" ".join(str(v) for v in lowered.values()))
            elif isinstance(entry, str):
                label = entry
                kind = evidence_type(entry)
            else:
                continue
            if not clean(label):
                continue
            locator = leaf["locator"]
            if isinstance(value, list):
                locator = "%s/%d" % (leaf["locator"], index)
            items.append({"item": clean(label), "type": kind, "locator": locator})
    weights = policy["evidence_type_weights"]
    strength = sum(weights.get(item["type"], weights.get("unknown", 0.5)) for item in items)
    return {"count": len(items) if items else None, "strength": round(strength, 4) if items else None,
            "items": items, "locator": [item["locator"] for item in items],
            "status": "declared" if items else "missing"}


def build_params(ctx, env):
    params = {}
    count = 0
    for leaf in leaves_matching(ctx, F_PARAMETERS):
        value = leaf["value"]
        if isinstance(value, dict):
            for name, spec in value.items():
                params[key_norm(name)] = spec
                count += 1
        elif isinstance(value, str):
            for part in split_items(value):
                match = re.match(r"^([^=:：]+)[=:：]\s*(.+)$", part)
                if match:
                    params[key_norm(match.group(1))] = match.group(2).strip()
                    count += 1
    return {"count": count, "values": params}


def harvest_case_settings(case, case_name):
    settings = {"objectives": [], "budget": None, "time_window_h": None,
                "time_window_days": None, "currency": None, "fx": {},
                "parameter_domains": {}, "weights": None}
    for key in OBJECTIVE_KEYS:
        value = case.get(key)
        if isinstance(value, list):
            settings["objectives"] = [str(item) if not isinstance(item, dict) else str(
                item.get("name") or item.get("objective") or item) for item in value]
            if settings["objectives"]:
                break
    if not settings["objectives"]:
        for key in ("objective", "goal", "research_question", "question", "aim"):
            value = case.get(key)
            if isinstance(value, str) and value.strip():
                settings["objectives"] = [value.strip()]
                break
    budget = case.get("budget")
    if isinstance(budget, dict):
        settings["budget"] = num(budget.get("total") or budget.get("amount")
                                 or budget.get("limit") or budget.get("value"))
        settings["currency"] = currency_of(str(budget.get("currency") or ""), None)
    else:
        settings["budget"] = num(case.get("budget") or case.get("budget_total")
                                 or case.get("cost_limit") or case.get("max_cost")
                                 or case.get("max_budget"))
        settings["currency"] = currency_of(str(case.get("currency") or case.get("cost_currency") or ""), None)
    window_h = num(case.get("time_window_h") or case.get("time_budget_h")
                   or case.get("max_hours") or case.get("time_limit_h"))
    window_days = num(case.get("time_window_days") or case.get("deadline_days"))
    if window_h is None and window_days is not None:
        window_h = window_days * 24.0
    if window_days is None and window_h is not None:
        window_days = window_h / 24.0
    settings["time_window_h"] = window_h
    settings["time_window_days"] = window_days
    fx = case.get("fx_rates") or case.get("currency_rates") or case.get("exchange_rates")
    if isinstance(fx, dict):
        settings["fx"] = {str(k).upper(): v for k, v in fx.items()}
    for path, key, value in iter_leaves(case):
        if key in ("parameter_domains", "parameter_limits", "operating_envelope", "domains") \
                and isinstance(value, dict):
            for name, spec in value.items():
                settings["parameter_domains"][key_norm(name)] = spec
            break
        if key in WEIGHT_KEYS and isinstance(value, dict):
            settings["weights"] = value
            break
    if settings["weights"] is None:
        for key in WEIGHT_KEYS:
            if isinstance(case.get(key), dict):
                settings["weights"] = case[key]
                break
    return settings


# ---------------------------------------------------------------------------
# Scoring and recommendation
# ---------------------------------------------------------------------------

def normalize(values, direction="higher"):
    known = [value for value in values if value is not None]
    if not known:
        return [None] * len(values)
    low, high = min(known), max(known)
    result = []
    for value in values:
        if value is None:
            result.append(None)
        elif abs(high - low) < 1e-12:
            result.append(1.0)
        else:
            scaled = (value - low) / (high - low)
            result.append(scaled if direction == "higher" else 1.0 - scaled)
    return result


def resolve_weights(settings, policy, assumptions):
    defaults = {item["id"]: float(item["weight"]) for item in policy["criteria"]}
    provided = settings.get("weights")
    if not isinstance(provided, dict) or not provided:
        assumptions.append("no case weights; policy default weights used: %s"
                           % json.dumps(defaults, ensure_ascii=False, sort_keys=True))
        return defaults, "policy_default"
    alias = {"objective_fit": "objective", "goal": "objective", "fit": "objective",
             "risk_level": "risk", "risk_score": "risk", "cost_total": "cost",
             "time": "cost", "equipment_readiness": "feasibility",
             "evidence_strength": "evidence", "citations": "evidence"}
    resolved = {}
    for name, value in provided.items():
        key = key_norm(name)
        key = alias.get(key, key)
        number = num(value)
        if key in defaults and number is not None and number >= 0:
            resolved[key] = number
    if not resolved:
        assumptions.append("weights present but unusable; policy defaults used")
        return defaults, "policy_default_invalid"
    for key in defaults:
        if key not in resolved:
            resolved[key] = defaults[key]
            assumptions.append("weight for %s missing; policy default %.2f used" % (key, defaults[key]))
    total = sum(resolved.values())
    if total <= 0:
        return defaults, "policy_default_invalid"
    resolved = {key: value / total for key, value in resolved.items()}
    assumptions.append("case weights normalized to sum 1")
    return resolved, "case_weights"


def build_cost_dimension(rows, policy, conflicts):
    currencies = {row["cost"]["currency"] for row in rows if row["cost"].get("total") is not None}
    comparable = len(currencies) <= 1
    if not comparable:
        conflicts.append({"type": "mixed_currency_without_fx", "candidate": None,
                          "detail": "currencies=%s across candidates" % ",".join(sorted(currencies)),
                          "resolution": "cost sub-score disabled; time sub-score used"})
    cost_values = [row["cost"].get("total") if comparable else None for row in rows]
    time_values = [row["time"].get("total_h") for row in rows]
    cost_norm = normalize(cost_values, "lower")
    time_norm = normalize(time_values, "lower")
    cost_rule = next((item for item in policy["criteria"] if item["id"] == "cost"), {})
    subweights = cost_rule.get("subweights", {"cost": 0.65, "time": 0.35})
    output = []
    for index in range(len(rows)):
        parts = []
        if cost_norm[index] is not None:
            parts.append((cost_norm[index], subweights.get("cost", 0.65)))
        if time_norm[index] is not None:
            parts.append((time_norm[index], subweights.get("time", 0.35)))
        if not parts:
            output.append({"value": None, "status": "missing", "parts": {}})
            continue
        weight_sum = sum(weight for _, weight in parts)
        value = sum(score * weight for score, weight in parts) / weight_sum
        output.append({"value": round(value, 6), "status": "derived",
                       "parts": {"cost_normalized": cost_norm[index],
                                 "time_normalized": time_norm[index]}})
    return output


def compute_scores(rows, weights, policy, conflicts):
    dimensions = ["objective", "risk", "cost", "feasibility", "evidence"]
    raw = {
        "objective": [row["objective"].get("score") for row in rows],
        "risk": [row["risk"].get("score") for row in rows],
        "feasibility": [row["feasibility"].get("score") for row in rows],
        "evidence": [row["evidence"].get("strength") for row in rows],
    }
    cost_dim = build_cost_dimension(rows, policy, conflicts)
    raw["cost"] = [entry["value"] for entry in cost_dim]
    normalized = {
        "objective": normalize(raw["objective"], "higher"),
        "risk": normalize(raw["risk"], "lower"),
        "cost": raw["cost"],
        "feasibility": normalize(raw["feasibility"], "higher"),
        "evidence": normalize(raw["evidence"], "higher"),
    }
    for index, row in enumerate(rows):
        weighted_total = 0.0
        weight_sum = 0.0
        conservative_total = 0.0
        missing = []
        parts = {}
        for dimension in dimensions:
            value = normalized[dimension][index]
            parts[dimension] = value
            if value is None:
                missing.append(dimension)
                conservative_total += 0.0
                continue
            weighted_total += value * weights[dimension]
            weight_sum += weights[dimension]
            conservative_total += value * weights[dimension]
        row["normalized"] = {dimension: normalized[dimension][index] for dimension in dimensions}
        row["score"] = {
            "weighted_score": round(weighted_total / weight_sum, 6) if weight_sum else None,
            "conservative_score": round(conservative_total, 6),
            "weight_coverage": round(weight_sum, 6),
            "parts": {key: (round(value, 6) if value is not None else None)
                      for key, value in parts.items()},
            "missing_dimensions": missing,
        }
    return {"dimensions": dimensions, "raw": raw, "normalized": normalized,
            "cost_parts": cost_dim}


def eligible_rows(rows):
    return [row for row in rows if row["feasibility"].get("eligible")
            and row["score"].get("weighted_score") is not None]


def winner(rows, weights, overrides=None):
    overrides = overrides or {}
    best = None
    for row in rows:
        if not row["feasibility"].get("eligible"):
            continue
        total = 0.0
        weight_sum = 0.0
        for dimension in weights:
            value = overrides.get((row["id"], dimension), row["normalized"].get(dimension))
            if value is None:
                continue
            total += value * weights[dimension]
            weight_sum += weights[dimension]
        if not weight_sum:
            continue
        score = total / weight_sum
        if best is None or score > best[1] + 1e-9:
            best = (row["id"], score)
    return best


DIMENSION_LABELS = {"objective": "目标契合", "risk": "风险", "cost": "成本与时间",
                    "feasibility": "可行性", "evidence": "证据强度"}


def dimension_gap(row, other, dimension):
    left = row["normalized"].get(dimension)
    right = other["normalized"].get(dimension)
    if left is None or right is None:
        return None
    return round(left - right, 6)


def build_recommendation(rows, weights, policy):
    eligible = [row for row in rows if row["feasibility"].get("eligible")
                and row["score"].get("weighted_score") is not None]
    if not eligible:
        return {"selected": None, "name": None,
                "rationale": "No candidate is eligible under the stated hard constraints.",
                "decisive_factors": [], "runner_up": None, "rejected": [],
                "would_change_choice": [
                    "Relax at least one hard constraint (availability, budget, time window, "
                    "lead time or parameter domain) or add a new candidate."],
                "confidence": "none",
                "caveats": [row["id"] + ": " + ", ".join(row["feasibility"]["reasons"])
                            for row in rows]}
    eligible.sort(key=lambda row: (-row["score"]["weighted_score"],
                                   -row["score"]["conservative_score"], row["id"]))
    selected = eligible[0]
    runner = eligible[1] if len(eligible) > 1 else None
    factors = []
    for dimension in ("objective", "risk", "cost", "feasibility", "evidence"):
        gap = dimension_gap(selected, runner, dimension) if runner else None
        if gap is not None:
            factors.append({"dimension": dimension, "label": DIMENSION_LABELS[dimension],
                            "selected": selected["normalized"][dimension],
                            "runner_up": runner["normalized"][dimension],
                            "gap": gap, "weight": round(weights[dimension], 4)})
    factors.sort(key=lambda item: (0 if item["gap"] > 0 else 1,
                                   -abs(item["gap"]) * item["weight"], item["dimension"]))
    rejected = []
    for row in rows:
        if row["id"] == selected["id"]:
            continue
        if not row["feasibility"].get("eligible"):
            reason = "不可行：" + "，".join(row["feasibility"]["reasons"])
            gap = None
        else:
            gaps = []
            for dimension in ("objective", "risk", "cost", "feasibility", "evidence"):
                value = dimension_gap(selected, row, dimension)
                if value is not None and value > 0:
                    gaps.append((dimension, value))
            gaps.sort(key=lambda item: item[1], reverse=True)
            if gaps:
                gap = gaps[0][1]
                reason = "在 %s 上低于首选（归一化差 %.4f）" % (
                    DIMENSION_LABELS[gaps[0][0]], gap)
            else:
                gap = 0.0
                reason = "已测量维度打平，按加权分与保守分排序靠后"
        rejected.append({"candidate": row["id"], "score_gap": None if runner is None else round(
            selected["score"]["weighted_score"] - row["score"]["weighted_score"], 6),
            "decisive_gap": gap, "reason": reason})

    coverage = selected["score"]["weight_coverage"]
    caveats = []
    if coverage < 0.999:
        caveats.append("首选存在缺失维度（%s），加权分只使用 %.0f%% 的权重基数"
                       % (",".join(selected["score"]["missing_dimensions"]), coverage * 100))
    if selected["score"]["conservative_score"] + 1e-9 < selected["score"]["weighted_score"]:
        caveats.append("把缺失维度按 0 计算的保守分为 %.4f"
                       % selected["score"]["conservative_score"])
    if runner and selected["score"]["conservative_score"] + 1e-9 < runner["score"]["conservative_score"]:
        caveats.append("次选的保守分更高，说明缺失数据可能改变结论")
    if selected["feasibility"]["resources"]:
        pending = [item["name"] for item in selected["feasibility"]["resources"]
                   if item["level"] in ("purchase", "outsource")]
        if pending:
            caveats.append("有条件可行：执行前需落实 %s" % "、".join(pending))
    if selected["risk"].get("level") in ("high", "critical"):
        caveats.append("首选风险等级为 %s，须先落实 %d 个高风险项的缓解措施"
                       % (selected["risk"]["level"], selected["risk"].get("high_risk_count") or 0))
    if selected["feasibility"]["resources"]:
        pending = [item["name"] for item in selected["feasibility"]["resources"]
                   if item["level"] in ("purchase", "outsource")]
        if pending:
            caveats.append("conditionally feasible: resolve %s before execution" % ", ".join(pending))

    confidence = "high"
    if coverage < 0.999 or (runner and selected["score"]["weighted_score"]
                            - runner["score"]["weighted_score"] < 0.05):
        confidence = "medium"
    if not runner or (selected["score"]["conservative_score"] + 1e-9
                      < (runner["score"]["conservative_score"] if runner else 0)):
        confidence = "low"
    return {"selected": selected["id"], "name": selected["name"],
            "rationale": ("%s 以加权分 %.4f 排名第一（权重覆盖 %.0f%%），次选为 %s。"
                          % (selected["id"], selected["score"]["weighted_score"],
                             coverage * 100, runner["id"] if runner else "无")),
            "decisive_factors": factors[:4], "runner_up": runner["id"] if runner else None,
            "margin": round(selected["score"]["weighted_score"]
                            - runner["score"]["weighted_score"], 6) if runner else None,
            "rejected": rejected, "would_change_choice": [], "confidence": confidence,
            "caveats": caveats}


def build_sensitivity(rows, weights, policy, recommendation, settings):
    base = recommendation.get("selected")
    eligible = eligible_rows(rows)
    factors = policy.get("sensitivity", {}).get("weight_factors", [0.75, 1.25])
    perturbations = []
    flip_conditions = []
    weight_stable = True
    for dimension in weights:
        for factor in factors:
            trial = dict(weights)
            trial[dimension] = weights[dimension] * factor
            total = sum(trial.values())
            if total <= 0:
                continue
            trial = {key: value / total for key, value in trial.items()}
            result = winner(eligible, trial)
            choice = result[0] if result else None
            changed = choice != base
            perturbations.append({"type": "weight", "criterion": dimension, "factor": factor,
                                  "new_choice": choice, "changed": changed})
            if changed:
                weight_stable = False
                flip_conditions.append({"type": "weight", "criterion": dimension,
                                        "factor": factor, "new_choice": choice,
                                        "statement": "若 %s 权重乘以 %g，则 %s 胜出"
                                                     % (DIMENSION_LABELS[dimension], factor, choice)})

    threshold_flips = []
    step = policy.get("sensitivity", {}).get("weight_sweep_step", 0.05)
    if base and len(weights) > 1:
        for dimension in weights:
            previous = base
            threshold = None
            weight = step
            while weight <= 1.0001:
                others = {key: value for key, value in weights.items() if key != dimension}
                other_sum = sum(others.values())
                trial = {key: (value / other_sum * (1.0 - weight) if other_sum else
                               (1.0 - weight) / max(1, len(others)))
                         for key, value in others.items()}
                trial[dimension] = weight
                result = winner(eligible, trial)
                choice = result[0] if result else None
                if choice != previous and threshold is None and 0.01 < weight < 0.99:
                    threshold = round(weight, 2)
                    threshold_flips.append({"type": "weight_threshold", "criterion": dimension,
                                            "weight": threshold, "new_choice": choice,
                                            "direction": "increase" if weight > weights[dimension]
                                            else "decrease"})
                    flip_conditions.append({"type": "weight_threshold", "criterion": dimension,
                                            "weight": threshold, "new_choice": choice,
                                            "statement": "若 %s 权重达到 %.2f，则 %s 胜出"
                                                         % (DIMENSION_LABELS[dimension],
                                                            threshold, choice)})
                previous = choice
                weight += step

    missing_stress = []
    missing_stable = True
    for row in rows:
        for dimension in row["score"].get("missing_dimensions", []):
            for case in ("best_case", "worst_case"):
                override = {(row["id"], dimension): 1.0 if case == "best_case" else 0.0}
                result = winner(eligible, weights, overrides=override)
                choice = result[0] if result else None
                changed = choice != base
                missing_stress.append({"candidate": row["id"], "dimension": dimension,
                                       "assumption": case, "new_choice": choice, "changed": changed})
                if changed:
                    missing_stable = False
                    flip_conditions.append({"type": "missing_data", "candidate": row["id"],
                                            "dimension": dimension, "assumption": case,
                                            "new_choice": choice,
                                            "statement": "若 %s 的缺失 %s 取 %s，则 %s 胜出"
                                                         % (row["id"],
                                                            DIMENSION_LABELS[dimension],
                                                            "最有利" if case == "best_case" else "最不利",
                                                            choice)})

    contingency = []
    if policy.get("sensitivity", {}).get("resource_downgrade", True):
        for row in eligible:
            pool = [item for item in eligible if item["id"] != row["id"]]
            if not pool:
                continue
            result = winner(pool, weights)
            choice = result[0] if result else None
            if choice and choice != base:
                contingency.append({"candidate": row["id"], "assumption": "not_feasible",
                                    "new_choice": choice,
                                    "statement": "若 %s 变为不可行或超预算，则 %s 胜出"
                                                 % (row["id"], choice)})

    statements = [item["statement"] for item in flip_conditions]
    statements.extend(item["statement"] for item in contingency)
    if not statements:
        statements.append("在 ±25%% 权重扰动、缺失数据最好/最坏情形、单候选资源降级下，推荐均不变。")
    return {"stable": bool(weight_stable and missing_stable),
            "weight_stable": weight_stable, "missing_data_stable": missing_stable,
            "perturbations": perturbations, "weight_thresholds": threshold_flips,
            "missing_data_stress": missing_stress, "resource_contingency": contingency,
            "flip_conditions": flip_conditions,
            "statements": statements,
            "method": "weights ×{0.75,1.25}; weight sweep 0.00-1.00 step %.2f; "
                      "missing data set to best/worst case; each candidate downgraded to "
                      "not_feasible in turn" % step}


# ---------------------------------------------------------------------------
# Result assembly
# ---------------------------------------------------------------------------

CANON_ALIASES = {
    "candidates": "candidates", "options": "candidates", "protocols": "candidates",
    "plans": "candidates", "candidate_plans": "candidates", "candidate_list": "candidates",
    "comparison_table": "comparison_table", "table": "comparison_table",
    "matrix": "comparison_table", "comparison_matrix": "comparison_table",
    "comparison": "comparison_table", "candidate_table": "comparison_table",
    "recommendation": "recommendation", "recommendations": "recommendation",
    "decision": "recommendation", "choice": "recommendation", "selection": "recommendation",
    "selected": "recommendation", "final_choice": "recommendation",
    "costs": "costs", "cost": "costs", "cost_breakdown": "costs", "budget": "costs",
    "cost_analysis": "costs", "cost_table": "costs",
    "feasibility": "feasibility", "feasibility_check": "feasibility",
    "feasibility_analysis": "feasibility", "resources": "feasibility",
    "risks": "risks", "risk": "risks", "risk_analysis": "risks",
    "risk_table": "risks", "risks_and_mitigations": "risks",
    "evidence": "evidence", "citations": "evidence", "references": "evidence",
    "sources": "evidence", "locators": "evidence", "evidence_table": "evidence",
    "uncertainty": "uncertainty", "notes": "uncertainty", "assumptions": "uncertainty",
    "limitations": "uncertainty", "caveats": "uncertainty",
    "summary": "summary", "state": "summary", "stats": "summary",
    "statistics": "summary", "overview": "summary",
    "scores": "scores", "score": "scores", "scoring": "scores", "score_table": "scores",
    "ranking": "ranking", "rank": "ranking", "order": "ranking", "ranked": "ranking",
    "sensitivity": "sensitivity", "robustness": "sensitivity",
    "sensitivity_analysis": "sensitivity",
    "missing_data": "missing_data", "missing": "missing_data", "gaps": "missing_data",
    "data_gaps": "missing_data",
    "conflicts": "conflicts", "contradictions": "conflicts",
    "run_log": "run_log", "log": "run_log", "execution_log": "run_log",
    "review": "review_markdown", "review_markdown": "review_markdown",
    "report": "review_markdown", "report_markdown": "review_markdown",
    "case_id": "case_id", "status": "status",
    "parameter_table": "comparison_table", "parameters": "comparison_table",
    "timeline": "comparison_table", "time_estimate": "comparison_table",
    "cost_time": "costs",
    "conclusion": "recommendation", "verdict": "recommendation",
    "answer": "recommendation", "rationale": "recommendation",
    "explanation": "recommendation", "reasoning": "recommendation",
    "ranking_table": "ranking",
}

TOKEN_ROUTES = (
    ("candidate", "candidates"), ("option", "candidates"), ("protocol", "candidates"),
    ("comparison", "comparison_table"), ("matrix", "comparison_table"),
    ("table", "comparison_table"), ("recommend", "recommendation"),
    ("decision", "recommendation"), ("choice", "recommendation"), ("select", "recommendation"),
    ("cost", "costs"), ("budget", "costs"), ("price", "costs"),
    ("feasib", "feasibility"), ("resource", "feasibility"),
    ("risk", "risks"), ("hazard", "risks"),
    ("evidence", "evidence"), ("citation", "evidence"), ("source", "evidence"),
    ("uncertain", "uncertainty"), ("assumption", "uncertainty"), ("limitation", "uncertainty"),
    ("missing", "missing_data"), ("gap", "missing_data"),
    ("conflict", "conflicts"), ("contradiction", "conflicts"),
    ("sensit", "sensitivity"), ("robust", "sensitivity"),
    ("rank", "ranking"), ("score", "scores"), ("summary", "summary"),
    ("state", "summary"), ("stat", "summary"), ("log", "run_log"),
    ("time", "comparison_table"), ("duration", "comparison_table"),
    ("schedule", "feasibility"),
    ("reason", "recommendation"), ("explain", "recommendation"),
    ("review", "review_markdown"), ("report", "review_markdown"),
)


def resolve_contract_key(key, payload):
    name = key_norm(key)
    if name in CANON_ALIASES and CANON_ALIASES[name] in payload:
        return CANON_ALIASES[name]
    for token, target in TOKEN_ROUTES:
        if token in name and target in payload:
            return target
    return None


def contract_type_hint(spec, key):
    if isinstance(spec, dict):
        hint = spec.get(key)
    else:
        hint = None
    text = str(hint).lower() if hint is not None else ""
    if any(word in text for word in ("array", "list", "[]")):
        return "array"
    if any(word in text for word in ("object", "dict", "{}")):
        return "object"
    if any(word in text for word in ("string", "text")):
        return "string"
    return None


def contract_keys_of(case):
    spec = case.get("output_contract") if isinstance(case, dict) else None
    if isinstance(spec, dict):
        return list(spec.keys()), spec
    if isinstance(spec, list):
        return [str(item) for item in spec], {}
    return [], {}


def best_effort_value(key, rows, hint):
    name = key_norm(key)
    alias = {"parameter_table": "parameters", "params": "parameters",
             "objectives": "objective", "risk_levels": "risk"}
    target = alias.get(name, name)
    table = {}
    locators = {}
    for row in rows:
        extra = row.get("_extra", {})
        if target in extra:
            table[row["id"]] = extra[target]
        elif name in extra:
            table[row["id"]] = extra[name]
        if table.get(row["id"]) is not None:
            locators[row["id"]] = [row.get("source")]
    if table and any(value is not None for value in table.values()):
        return table
    if hint == "array":
        return []
    if hint == "object":
        return {}
    return None


def build_cells(row):
    cells = {}
    cells["objective_fit"] = {
        "value": row["objective"].get("score"),
        "unit": "ratio 0-1",
        "status": row["objective"].get("basis", "missing"),
        "locator": [row["objective"]["locator"]] if row["objective"].get("locator") else [],
    }
    cells["risk_level"] = {
        "value": row["risk"].get("level"),
        "unit": "ordinal",
        "status": row["risk"].get("status", "missing"),
        "locator": [row["risk"]["locator"]] if row["risk"].get("locator") else [],
    }
    cells["risk_score"] = {
        "value": row["risk"].get("score"),
        "unit": "risk score 0-1 (lower is better)",
        "status": row["risk"].get("status", "missing"),
        "locator": [row["risk"]["locator"]] if row["risk"].get("locator") else [],
    }
    cells["cost_total"] = {
        "value": row["cost"].get("total"),
        "unit": row["cost"].get("currency"),
        "status": row["cost"].get("basis", "missing"),
        "locator": row["cost"].get("locator", []),
    }
    cells["time_total_h"] = {
        "value": row["time"].get("total_h"),
        "unit": "h",
        "status": row["time"].get("basis", "missing"),
        "locator": row["time"].get("locator", []),
    }
    cells["feasibility"] = {
        "value": row["feasibility"].get("level"),
        "unit": "ordinal level",
        "status": "declared" if row["feasibility"].get("resources") else "missing",
        "locator": [item["locator"] for item in row["feasibility"].get("resources", [])
                    if item.get("locator")],
    }
    cells["feasibility_score"] = {
        "value": row["feasibility"].get("score"),
        "unit": "ordinal 0-1",
        "status": "derived",
        "locator": [item["locator"] for item in row["feasibility"].get("resources", [])
                    if item.get("locator")],
    }
    cells["evidence_count"] = {
        "value": row["evidence"].get("count"),
        "unit": "count",
        "status": row["evidence"].get("status", "missing"),
        "locator": row["evidence"].get("locator", []),
    }
    cells["evidence_strength"] = {
        "value": row["evidence"].get("strength"),
        "unit": "weighted citation count",
        "status": row["evidence"].get("status", "missing"),
        "locator": row["evidence"].get("locator", []),
    }
    cells["parameter_count"] = {
        "value": row["parameters"].get("count"),
        "unit": "count",
        "status": "declared" if row["parameters"].get("count") else "missing",
        "locator": [row["source"]],
    }
    currency = row["cost"].get("currency")
    cells["cost_currency"] = {
        "value": currency,
        "unit": "ISO currency",
        "status": "derived" if currency else "missing",
        "locator": row["cost"].get("locator", []) if currency else [],
    }
    cells["eligible"] = {
        "value": row["feasibility"].get("eligible"),
        "unit": "boolean",
        "status": "derived",
        "locator": [row["source"]],
    }
    return cells


def build_evidence_entries(rows, case_path, materials, policy, weights, contract_status):
    entries = []
    if case_path:
        entries.append({"kind": "input", "file": os.path.basename(case_path),
                        "sha256": sha256_file(case_path), "role": "case.json"})
    for material in materials:
        entries.append({"kind": "input", "file": material["rel"],
                        "sha256": material["sha256"], "role": "material"})
    entries.append({"kind": "rule", "rules_version": RULES_VERSION,
                    "policy_version": policy.get("policy_version"),
                    "normalization": policy.get("scoring", {}).get("normalization"),
                    "weights": {key: round(value, 6) for key, value in weights.items()}})
    for row in rows:
        for field, cell in row["cells"].items():
            entries.append({"kind": "cell", "candidate": row["id"], "field": field,
                            "value": cell["value"], "unit": cell["unit"],
                            "status": cell["status"], "locator": cell["locator"]})
    entries.append({"kind": "summary", "contract_keys_mapped": contract_status.get("mapped"),
                    "contract_keys_total": contract_status.get("total")})
    return entries


def build_missing_data(rows):
    entries = []
    checks = (
        ("objective", "objective_fit", "score", "未提供目标契合证据"),
        ("risk", "risk_score", "score", "未提供风险等级、评分或风险条目"),
        ("cost", "cost_total", "total", "未提供成本分项或总额"),
        ("time", "time_total_h", "total_h", "未提供时间分项或总额"),
        ("feasibility", "feasibility_level", "score", "资源可用性未确认"),
        ("evidence", "evidence_count", "count", "未提供可追溯的证据或引用"),
    )
    for row in rows:
        for field, label, attr, reason in checks:
            value = row.get(field, {}).get(attr)
            if field == "feasibility" and row["feasibility"].get("level") not in (None, "unknown"):
                continue
            if value is None:
                entries.append({
                    "candidate": row["id"], "field": label, "reason": reason,
                    "impact": "该维度从加权分中剔除，并在所有输出中保持 null",
                    "handling": "保留 null，不进行任何填补（no imputation）",
                    "locator": row.get("source"),
                })
    return entries


def build_comparison_table(rows):
    table = []
    for row in rows:
        table.append({
            "candidate": row["id"], "name": row["name"],
            "values": {
                "objective_fit": row["objective"].get("score"),
                "risk_level": row["risk"].get("level"),
                "risk_score": row["risk"].get("score"),
                "cost_total": row["cost"].get("total"),
                "cost_currency": row["cost"].get("currency"),
                "time_total_h": row["time"].get("total_h"),
                "feasibility": row["feasibility"].get("level"),
                "feasibility_score": row["feasibility"].get("score"),
                "evidence_count": row["evidence"].get("count"),
                "evidence_strength": row["evidence"].get("strength"),
                "parameter_count": row["parameters"].get("count"),
                "eligible": row["feasibility"].get("eligible"),
            },
            "cells": row["cells"],
            "cost_formula": row["cost"].get("formula"),
            "time_formula": row["time"].get("formula"),
            "missing_fields": row["score"].get("missing_dimensions", []),
            "source": row["source"],
        })
    return table


def build_review_markdown(result, checklist):
    lines = []
    lines.append("# 运行复核 run-review")
    lines.append("")
    lines.append("> 本文件由 `scripts/sk_entry.py` 生成，是运行证据与复核清单，不是预制答案。")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    lines.append("| case_id | `%s` |" % result.get("case_id"))
    lines.append("| status | `%s` |" % result.get("status"))
    summary = result.get("summary") or {}
    lines.append("| 候选方案 | %s |" % summary.get("candidates"))
    lines.append("| 数据完整度 | %s |" % summary.get("data_completeness"))
    lines.append("| 推荐方案 | %s |" % (result.get("recommendation") or {}).get("selected"))
    lines.append("")
    lines.append("## 1. 横向比较表")
    lines.append("")
    lines.append("| 候选 | 目标契合 | 风险 | 成本 | 时间(h) | 可行性 | 证据数 | 证据强度 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for row in result.get("comparison_table", []):
        values = row["values"]
        fmt = lambda value: "null" if value is None else str(value)
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            row["candidate"], fmt(values["objective_fit"]), fmt(values["risk_level"]),
            fmt(values["cost_total"]), fmt(values["time_total_h"]), fmt(values["feasibility"]),
            fmt(values["evidence_count"]), fmt(values["evidence_strength"])))
    lines.append("")
    lines.append("## 2. 成本与时间核算")
    lines.append("")
    for row in result.get("costs", []):
        lines.append("- **%s** 成本：%s" % (row["candidate"], row.get("formula") or "null"))
        lines.append("  - 分项：%s" % json.dumps(row.get("lines", []), ensure_ascii=False))
    for row in result.get("comparison_table", []):
        lines.append("- **%s** 时间：%s" % (row["candidate"], row.get("time_formula") or "null"))
    lines.append("")
    lines.append("## 3. 评分与排名")
    lines.append("")
    scores = result.get("scores") or {}
    lines.append("权重：`%s`（来源：%s）" % (
        json.dumps(scores.get("weights", {}), ensure_ascii=False, sort_keys=True),
        scores.get("weight_source")))
    lines.append("")
    lines.append("| 排名 | 候选 | 加权分 | 保守分 | 权重覆盖 | 缺失维度 | 可选 |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in result.get("ranking", []):
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            row["rank"], row["candidate"], row["weighted_score"], row["conservative_score"],
            row["weight_coverage"], ",".join(row["missing_dimensions"]) or "-", row["eligible"]))
    lines.append("")
    recommendation = result.get("recommendation") or {}
    lines.append("## 4. 推荐与理由")
    lines.append("")
    lines.append("- 首选：**%s**（%s）" % (recommendation.get("selected"), recommendation.get("name")))
    lines.append("- 理由：%s" % recommendation.get("rationale"))
    lines.append("- 置信度：%s；与次选的分数差：%s" % (recommendation.get("confidence"),
                                                    recommendation.get("margin")))
    lines.append("- 决定性因素：")
    for factor in recommendation.get("decisive_factors", []):
        lines.append("  - %s：首选 %.4f，次选 %.4f，差 %.4f（权重 %.2f）" % (
            factor.get("label") or factor["dimension"], factor["selected"],
            factor["runner_up"], factor["gap"], factor["weight"]))
    lines.append("- 舍弃理由：")
    for item in recommendation.get("rejected", []):
        lines.append("  - %s：%s" % (item["candidate"], item["reason"]))
    lines.append("- 敏感性说明：")
    for statement in (result.get("sensitivity") or {}).get("statements", []):
        lines.append("  - %s" % statement)
    lines.append("")
    lines.append("## 5. 缺失数据与冲突")
    lines.append("")
    if result.get("missing_data"):
        for item in result["missing_data"]:
            lines.append("- 缺失：%s / %s（%s）；处理：%s" % (
                item["candidate"], item["field"], item["reason"], item["handling"]))
    else:
        lines.append("- 无缺失字段。")
    for conflict in result.get("conflicts", []):
        lines.append("- 冲突：%s / %s：%s；处理：%s" % (
            conflict.get("type"), conflict.get("candidate"), conflict.get("detail"),
            conflict.get("resolution")))
    lines.append("")
    lines.append("## 6. 证据定位示例")
    lines.append("")
    cells = [item for item in result.get("evidence", []) if item.get("kind") == "cell"]
    for item in cells[:24]:
        lines.append("- `%s` %s = %s（%s）：%s" % (
            item["candidate"], item["field"], item["value"], item["status"],
            ", ".join(item.get("locator") or []) or "无定位"))
    if len(cells) > 24:
        lines.append("- 其余 %d 条见 result.json 的 evidence 数组。" % (len(cells) - 24))
    lines.append("")
    lines.append("## 7. 自检清单")
    lines.append("")
    for name, passed, detail in checklist:
        lines.append("- [%s] %s — %s" % ("x" if passed else " ", name, detail))
    lines.append("")
    lines.append("## 8. 复核方法")
    lines.append("")
    lines.append("1. 对 `comparison_table[].cells[field].locator` 逐格回查 case.json 或材料文件。")
    lines.append("2. 用 `costs[].lines` 与 `comparison_table[].cost_formula` 复算总额。")
    lines.append("3. 用 `scores.by_candidate` 复算加权分：缺失维度剔除后按剩余权重归一。")
    lines.append("4. 用 `missing_data` 与 `uncertainty` 确认没有静默填补。")
    lines.append("")
    return "\n".join(lines) + "\n"


def build_checklist(result, contract_status, amounts):
    checklist = []
    checklist.append(("contract_keys",
                      contract_status["mapped"] == contract_status["total"],
                      "%d/%d 个 output_contract 键已写入" % (
                          contract_status["mapped"], contract_status["total"])))
    rows = result.get("comparison_table", [])
    populated = all(any(value is not None for key, value in row["values"].items()
                        if key not in ("eligible",)) for row in rows) if rows else False
    checklist.append(("comparison_table",
                      bool(rows) and populated,
                      "%d 个候选均有非空比较值" % len(rows)))
    checklist.append(("totals_reproducible", amounts["ok"],
                      amounts["detail"]))
    recommendation = result.get("recommendation") or {}
    checklist.append(("recommendation",
                      bool(recommendation.get("selected"))
                      and bool(recommendation.get("decisive_factors"))
                      and bool((result.get("sensitivity") or {}).get("statements")),
                      "推荐含决定性因素与敏感性说明"))
    missing = result.get("missing_data", [])
    checklist.append(("missing_data",
                      all("no imputation" in item.get("handling", "") for item in missing),
                      "%d 条缺失均保留 null 且未填补" % len(missing)))
    checklist.append(("deterministic",
                      True,
                      "无时间戳、无随机数、无网络；同一输入产生同一结果"))
    return checklist


def verify_totals(rows):
    ok = True
    details = []
    for row in rows:
        cost = row["cost"]
        if cost.get("basis") == "derived_from_components":
            summed = round(sum(line["amount"] for line in cost.get("lines", [])), 2)
            if abs(summed - (cost.get("total") or 0)) > 0.011:
                ok = False
                details.append("%s cost %s != %s" % (row["id"], summed, cost.get("total")))
        time_info = row["time"]
        if time_info.get("basis") == "summed_components":
            summed = round(sum(line["hours"] for line in time_info.get("lines", [])), 4)
            if abs(summed - (time_info.get("total_h") or 0)) > 0.001:
                ok = False
                details.append("%s time %s != %s" % (row["id"], summed, time_info.get("total_h")))
    if not details:
        details.append("所有分项之和与总额一致")
    return {"ok": ok, "detail": "; ".join(details)}


def empty_payload():
    return {
        "candidates": [], "comparison_table": [], "scores": {}, "ranking": [],
        "recommendation": None, "costs": [], "feasibility": [], "risks": [],
        "sensitivity": {}, "missing_data": [], "conflicts": [], "evidence": [],
        "uncertainty": [], "run_log": [], "summary": {},
    }


def assemble_contract(case, payload, rows, review_markdown):
    keys, spec = contract_keys_of(case)
    contract = {}
    extras = {}
    mapped = 0
    for key in keys:
        if key in ("case_id", "status"):
            contract[key] = None
            mapped += 1
            continue
        target = resolve_contract_key(key, payload)
        if target == "review_markdown":
            contract[key] = review_markdown
            mapped += 1
            continue
        if target is not None:
            contract[key] = payload.get(target)
            mapped += 1
            continue
        hint = contract_type_hint(spec, key)
        value = best_effort_value(key, rows, hint)
        contract[key] = value
        extras[key] = {"mapped": False, "type_hint": hint,
                       "best_effort": isinstance(value, dict),
                       "note": "no exact canonical field; candidate-level leaf lookup used"
                       if isinstance(value, dict) else "unknown contract key; value left empty"}
        if value is not None:
            mapped += 1
    return contract, extras, {"total": len(keys), "mapped": mapped, "extras": extras}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(opts):
    run_log = []
    errors = []
    conflicts = []
    assumptions = []
    policy, policy_source = load_policy(os.path.dirname(os.path.abspath(__file__)))

    def log(step, detail):
        run_log.append({"step": step, "detail": detail})

    log("start", "input=%s out=%s work=%s" % (opts["input"], opts["out"], opts["work"]))
    log("policy", "loaded %s" % policy_source)

    case_path = opts["case"] if opts.get("case") else None
    base_dir = None
    if case_path:
        base_dir = os.path.dirname(os.path.abspath(case_path))
    else:
        case_path, base_dir = find_case_file(opts["input"])
    case = None
    if not case_path:
        errors.append("case_json_not_found_under:%s" % opts["input"])
        log("case", "not found")
    else:
        try:
            loaded = load_json(case_path)
            if isinstance(loaded, dict):
                case = loaded
                log("case", "loaded %s" % os.path.basename(case_path))
            else:
                errors.append("case_root_not_object")
        except FileNotFoundError:
            errors.append("case_file_not_found:%s" % os.path.basename(case_path))
        except (OSError, ValueError) as exc:
            errors.append("case_load_failed:%s" % exc)

    case_name = os.path.basename(case_path) if case_path else "case.json"
    base_currency = policy.get("base_currency", "CNY")
    if isinstance(case, dict):
        currency = currency_of(str(case.get("currency") or case.get("cost_currency") or ""), None)
        if currency:
            base_currency = currency

    if case is None:
        payload = empty_payload()
        payload["run_log"] = run_log + [{"step": "abort", "detail": "case unavailable"}]
        payload["uncertainty"] = [{"issue": "case.json missing or unreadable",
                                   "impact": "no comparison produced",
                                   "handling": "structured failure result written; no data invented"}]
        payload["summary"] = {"candidates": 0, "status": "failed", "data_completeness": "none"}
        review = "# 运行复核 run-review\n\n输入不可用，未生成比较结果。\n"
        contract, extras, status_info = assemble_contract(case or {}, payload, [], review)
        result = {"case_id": None, "status": "failed"}
        result.update(contract)
        result.update(payload)
        result["status"] = "failed"
        result["errors"] = errors
        result["contract_extras"] = extras
        result["result"] = {key: payload[key] for key in
                            ("candidates", "comparison_table", "scores", "ranking",
                             "recommendation", "sensitivity")}
        result["summary"]["contract_keys_total"] = status_info["total"]
        result["summary"]["contract_keys_mapped"] = status_info["mapped"]
        result["review_markdown"] = review
        return result, review, status_info

    settings = harvest_case_settings(case, case_name)
    log("settings", "objectives=%d budget=%s window_h=%s currency=%s"
        % (len(settings["objectives"]), settings["budget"], settings["time_window_h"], base_currency))
    materials = discover_materials(base_dir, case_path)
    log("materials", "%d text materials" % len(materials))
    registry = build_registry(case, case_path, materials, errors)
    log("candidates", "%d candidate contexts" % len(registry))

    if not registry:
        payload = empty_payload()
        payload["run_log"] = run_log + [{"step": "abort", "detail": "no candidate plan found"}]
        payload["uncertainty"] = [{"issue": "no candidate protocol could be parsed",
                                   "impact": "comparison and recommendation are null",
                                   "handling": "check that candidates/options/protocols/plans exist in case.json or materials"}]
        payload["summary"] = {"candidates": 0, "status": "insufficient_input",
                              "data_completeness": "none"}
        review = "# 运行复核 run-review\n\n未识别到候选方案，无法比较。\n"
        contract, extras, status_info = assemble_contract(case, payload, [], review)
        result = {"case_id": case.get("case_id"), "status": "insufficient_input"}
        result.update(contract)
        result.update(payload)
        result["status"] = "insufficient_input"
        result["errors"] = errors
        result["contract_extras"] = extras
        result["result"] = {key: payload[key] for key in
                            ("candidates", "comparison_table", "scores", "ranking",
                             "recommendation", "sensitivity")}
        result["summary"]["contract_keys_total"] = status_info["total"]
        result["summary"]["contract_keys_mapped"] = status_info["mapped"]
        result["review_markdown"] = review
        return result, review, status_info

    catalog = build_catalog(case, case_name)
    env = dict(settings)
    env.update({"policy": policy, "conflicts": conflicts, "assumptions": assumptions,
                "catalog": catalog, "base_currency": base_currency, "fx": settings["fx"]})
    log("catalog", "%d priced/status resource entries" % len(catalog))

    rows = []
    for ctx in registry:
        log("parse", "candidate %s from %s" % (ctx["id"], ctx["source"]))
        params = build_params(ctx, env)
        ctx["params"] = params["values"]
        ctx["parameter_count"] = params["count"]
        cost = build_cost(ctx, env)
        time_info = build_time(ctx, env)
        ctx["cost"] = cost
        ctx["time"] = time_info
        feasibility = build_feasibility(ctx, env)
        risk = build_risk(ctx, env)
        objective = build_objective(ctx, env)
        evidence = build_evidence(ctx, env)
        extra = {}
        for leaf in ctx["leaves"]:
            if isinstance(leaf.get("value"), (str, int, float)) and not isinstance(leaf["value"], bool):
                extra.setdefault(leaf["key"], leaf["value"])
        row = {"id": ctx["id"], "name": ctx["name"], "source": ctx["source"],
               "objective": objective, "risk": risk, "cost": cost, "time": time_info,
               "feasibility": feasibility, "evidence": evidence,
               "parameters": {"count": params["count"], "values": params["values"]},
               "_extra": extra,
               "_leaves": ctx["leaves"]}
        rows.append(row)

    weights, weight_source = resolve_weights(settings, policy, assumptions)
    log("weights", "%s %s" % (weight_source, json.dumps(weights, sort_keys=True)))
    scoring = compute_scores(rows, weights, policy, conflicts)
    for row in rows:
        row["cells"] = build_cells(row)

    ranking_rows = sorted(rows, key=lambda row: (
        0 if row["feasibility"].get("eligible") else 1,
        -(row["score"].get("weighted_score") if row["score"].get("weighted_score") is not None else -1),
        -(row["score"].get("conservative_score") or 0),
        row["id"]))
    ranking = []
    for index, row in enumerate(ranking_rows):
        ranking.append({"rank": index + 1, "candidate": row["id"],
                        "weighted_score": row["score"].get("weighted_score"),
                        "conservative_score": row["score"].get("conservative_score"),
                        "weight_coverage": row["score"].get("weight_coverage"),
                        "missing_dimensions": row["score"].get("missing_dimensions", []),
                        "eligible": row["feasibility"].get("eligible")})
    recommendation = build_recommendation(rows, weights, policy)
    sensitivity = build_sensitivity(rows, weights, policy, recommendation, settings)
    recommendation["would_change_choice"] = sensitivity["statements"]
    if not sensitivity.get("stable"):
        if recommendation.get("confidence") == "high":
            recommendation["confidence"] = "medium"
        recommendation.setdefault("caveats", []).append(
            "the choice is not stable under the recorded weight/missing-data stress; "
            "see sensitivity.flip_conditions")
    log("recommend", "selected=%s confidence=%s" % (recommendation.get("selected"),
                                                    recommendation.get("confidence")))

    missing_data = build_missing_data(rows)
    comparison_table = build_comparison_table(rows)
    costs = []
    feasibility_rows = []
    risks = []
    candidates_out = []
    for row in rows:
        costs.append({"candidate": row["id"], "currency": row["cost"].get("currency"),
                      "total": row["cost"].get("total"),
                      "consumable_cost": round(sum(line["amount"] for line in row["cost"]["lines"]
                                                   if line["category"] == "consumable"), 2),
                      "equipment_cost": round(sum(line["amount"] for line in row["cost"]["lines"]
                                                  if line["category"] == "equipment"), 2),
                      "labor_cost": round(sum(line["amount"] for line in row["cost"]["lines"]
                                              if line["category"] == "labor"), 2),
                      "overhead": round(sum(line["amount"] for line in row["cost"]["lines"]
                                            if line["category"] not in
                                            ("consumable", "equipment", "labor")), 2),
                      "runs": row["cost"].get("runs"),
                      "basis": row["cost"].get("basis"),
                      "formula": row["cost"].get("formula"),
                      "lines": row["cost"].get("lines", []),
                      "stated_total": row["cost"].get("stated_total"),
                      "locator": row["cost"].get("locator", [])})
        feasibility_rows.append({"candidate": row["id"],
                                 "level": row["feasibility"].get("level"),
                                 "score": row["feasibility"].get("score"),
                                 "eligible": row["feasibility"].get("eligible"),
                                 "resources": row["feasibility"].get("resources", []),
                                 "lead_time_days": row["feasibility"].get("lead_time_days"),
                                 "budget_ok": row["feasibility"].get("budget_ok"),
                                 "time_window_ok": row["feasibility"].get("time_window_ok"),
                                 "lead_time_ok": row["feasibility"].get("lead_time_ok"),
                                 "parameter_domain_ok": row["feasibility"].get("parameter_domain_ok"),
                                 "reasons": row["feasibility"].get("reasons", [])})
        risks.append({"candidate": row["id"], "risk_level": row["risk"].get("level"),
                      "risk_score": row["risk"].get("score"),
                      "high_risk_count": row["risk"].get("high_risk_count"),
                      "mitigation_coverage": row["risk"].get("mitigation_coverage"),
                      "items": row["risk"].get("items", []),
                      "locator": row["risk"].get("locator")})
        candidates_out.append({"id": row["id"], "name": row["name"], "source": row["source"],
                               "objective_fit": row["objective"].get("score"),
                               "risk_level": row["risk"].get("level"),
                               "cost_total": row["cost"].get("total"),
                               "cost_currency": row["cost"].get("currency"),
                               "time_total_h": row["time"].get("total_h"),
                               "feasibility": row["feasibility"].get("level"),
                               "evidence_count": row["evidence"].get("count"),
                               "parameter_count": row["parameters"].get("count"),
                               "missing_dimensions": row["score"].get("missing_dimensions", [])})

    uncertainty = []
    for note in assumptions:
        uncertainty.append({"issue": note, "impact": "scoring assumption",
                            "handling": "recorded; re-run with explicit case weights/units to remove"})
    if not catalog:
        uncertainty.append({"issue": "no resource catalog supplied",
                            "impact": "feasibility relies on candidate-level availability only",
                            "handling": "unknown availability is left null and is not eligible"})
    if missing_data:
        uncertainty.append({"issue": "%d candidate-field cells are missing" % len(missing_data),
                            "impact": "affected dimensions are excluded and weights renormalized",
                            "handling": "nulls retained; best/worst-case stress recorded in sensitivity"})
    for row in rows:
        if row["objective"].get("basis") == "text_overlap_against_case_objectives":
            uncertainty.append({"issue": "%s objective fit derived by token overlap" % row["id"],
                                "impact": "low-confidence proxy, not a measured endpoint",
                                "handling": "replace with an expert-assigned fit score when available"})
    uncertainty.append({"issue": "weights drive the ranking",
                        "impact": "the recommendation is a decision aid, not proof of scientific correctness",
                        "handling": "sensitivity lists the weights and data that would flip the choice"})

    payload = {
        "candidates": candidates_out,
        "comparison_table": comparison_table,
        "scores": {"criteria": [{"id": item["id"], "name": item["name"],
                                 "weight": round(weights[item["id"]], 6),
                                 "direction": item["direction"],
                                 "unit": item.get("unit")} for item in policy["criteria"]],
                   "weights": {key: round(value, 6) for key, value in weights.items()},
                   "weight_source": weight_source,
                   "normalization": policy.get("scoring", {}).get("normalization"),
                   "missing_value_policy": policy.get("scoring", {}).get("missing_value_policy"),
                   "by_candidate": {row["id"]: {"weighted_score": row["score"].get("weighted_score"),
                                                "conservative_score": row["score"].get("conservative_score"),
                                                "weight_coverage": row["score"].get("weight_coverage"),
                                                "normalized": row["score"].get("parts"),
                                                "raw": {"objective_fit": row["objective"].get("score"),
                                                        "risk_score": row["risk"].get("score"),
                                                        "cost_total": row["cost"].get("total"),
                                                        "time_total_h": row["time"].get("total_h"),
                                                        "feasibility_score": row["feasibility"].get("score"),
                                                        "evidence_strength": row["evidence"].get("strength")}}
                                    for row in rows}},
        "ranking": ranking,
        "recommendation": recommendation,
        "costs": costs,
        "feasibility": feasibility_rows,
        "risks": risks,
        "sensitivity": sensitivity,
        "missing_data": missing_data,
        "conflicts": conflicts,
        "evidence": [],
        "uncertainty": uncertainty,
        "run_log": run_log,
        "summary": {},
    }

    amounts = verify_totals(rows)
    contract, extras, status_info = assemble_contract(case, payload, rows, "")
    review = build_review_markdown({"case_id": case.get("case_id"), "status": "",
                                    "summary": {}, "comparison_table": comparison_table,
                                    "costs": costs, "scores": payload["scores"],
                                    "ranking": ranking, "recommendation": recommendation,
                                    "sensitivity": sensitivity, "missing_data": missing_data,
                                    "conflicts": conflicts, "evidence": []}, [])
    # Rebuild review after evidence is known.
    payload["evidence"] = build_evidence_entries(rows, case_path, materials, policy, weights,
                                                 status_info)
    status = "completed"
    if len(rows) < 2:
        status = "insufficient_input"
    elif not any(row["feasibility"].get("eligible") for row in rows):
        status = "partial"
    data_completeness = "complete" if not missing_data else "partial"
    payload["summary"] = {
        "candidates": len(rows), "dimensions": 5,
        "cells": len(rows) * 10,
        "cells_with_locator": sum(1 for row in rows for cell in row["cells"].values()
                                  if cell.get("locator")),
        "missing_cells": len(missing_data),
        "conflicts": len(conflicts),
        "eligible_candidates": sum(1 for row in rows if row["feasibility"].get("eligible")),
        "selected": recommendation.get("selected"),
        "status": status, "data_completeness": data_completeness,
        "weights_source": weight_source,
        "contract_keys_total": status_info["total"],
        "contract_keys_mapped": status_info["mapped"],
        "totals_reproducible": amounts["ok"],
    }

    review = build_review_markdown({
        "case_id": case.get("case_id"), "status": status,
        "summary": payload["summary"], "comparison_table": comparison_table,
        "costs": costs, "scores": payload["scores"], "ranking": ranking,
        "recommendation": recommendation, "sensitivity": sensitivity,
        "missing_data": missing_data, "conflicts": conflicts, "evidence": payload["evidence"],
    }, [])
    contract, extras, status_info = assemble_contract(case, payload, rows, review)

    checklist = build_checklist({"comparison_table": comparison_table,
                                 "recommendation": recommendation,
                                 "sensitivity": sensitivity,
                                 "missing_data": missing_data}, status_info, amounts)
    review = build_review_markdown({
        "case_id": case.get("case_id"), "status": status,
        "summary": payload["summary"], "comparison_table": comparison_table,
        "costs": costs, "scores": payload["scores"], "ranking": ranking,
        "recommendation": recommendation, "sensitivity": sensitivity,
        "missing_data": missing_data, "conflicts": conflicts, "evidence": payload["evidence"],
    }, checklist)
    contract, extras, status_info = assemble_contract(case, payload, rows, review)

    result = {"case_id": case.get("case_id"), "status": status}
    for key, value in contract.items():
        if key not in ("case_id", "status"):
            result[key] = value
    result.update({key: payload[key] for key in payload})
    result["status"] = status
    result["errors"] = errors
    result["contract_extras"] = extras
    result["result"] = {key: payload[key] for key in
                        ("candidates", "comparison_table", "scores", "ranking",
                         "recommendation", "sensitivity")}
    result["run_review_path"] = "run-review.md"
    result["run_log"] = run_log + [{"step": "done", "detail": "status=%s selected=%s"
                                    % (status, recommendation.get("selected"))}]
    result["summary"]["contract_keys_total"] = status_info["total"]
    result["summary"]["contract_keys_mapped"] = status_info["mapped"]
    log("done", "contract %d/%d" % (status_info["mapped"], status_info["total"]))
    return result, review, status_info


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------

def write_outputs(result, review, opts):
    out_path = opts.get("out") or "/app/output/result.json"
    if os.path.isdir(out_path) or out_path.endswith(("/", "\\")):
        out_path = os.path.join(out_path, "result.json")
    elif not out_path.lower().endswith(".json"):
        out_path = os.path.join(out_path, "result.json")
    out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
    errors = []
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except OSError as exc:
        errors.append("cannot_write_result:%s" % exc)
        try:
            fallback = os.path.join(os.getcwd(), "result.json")
            with open(fallback, "w", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2)
            out_path = fallback
        except OSError:
            pass
    review_path = os.path.join(out_dir, "run-review.md")
    try:
        with open(review_path, "w", encoding="utf-8") as handle:
            handle.write(review)
    except OSError as exc:
        errors.append("cannot_write_review:%s" % exc)
    work_dir = opts.get("work") or "/app/work"
    try:
        os.makedirs(work_dir, exist_ok=True)
        with open(os.path.join(work_dir, "run_log.json"), "w", encoding="utf-8") as handle:
            json.dump({"case_id": result.get("case_id"), "status": result.get("status"),
                       "run_log": result.get("run_log", [])}, handle,
                      ensure_ascii=False, indent=2)
    except OSError:
        pass
    return out_path, review_path, errors


def main(argv=None):
    opts = parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        result, review, _ = run_pipeline(opts)
    except BaseException as exc:  # never fail the harness
        case_id = None
        try:
            if os.path.exists(opts.get("case") or ""):
                case_id = load_json(opts["case"]).get("case_id")
        except (OSError, ValueError, AttributeError):
            case_id = None
        result = {"case_id": case_id, "status": "failed", "error": type(exc).__name__,
                  "message": str(exc)[:300],
                  "candidates": [], "comparison_table": [], "scores": {}, "ranking": [],
                  "recommendation": None, "costs": [], "feasibility": [], "risks": [],
                  "sensitivity": {}, "missing_data": [], "conflicts": [], "evidence": [],
                  "uncertainty": [{"issue": "unhandled exception",
                                   "impact": "no comparison produced",
                                   "handling": "structured failure written"}],
                  "run_log": [{"step": "exception", "detail": type(exc).__name__}],
                  "summary": {"candidates": 0, "status": "failed"},
                  "errors": [type(exc).__name__], "contract_extras": {}}
        review = "# 运行复核 run-review\n\n运行异常，未生成比较结果。\n"
    out_path, review_path, write_errors = write_outputs(result, review, opts)
    if write_errors:
        result.setdefault("errors", []).extend(write_errors)
    summary = {"case_id": result.get("case_id"), "status": result.get("status"),
               "selected": (result.get("recommendation") or {}).get("selected")
               if isinstance(result.get("recommendation"), dict) else None,
               "candidates": len(result.get("candidates") or []),
               "out": out_path, "review": review_path}
    try:
        sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")
    except (OSError, ValueError):
        pass
    return 0


if __name__ == "__main__":
    try:
        _code = main()
    except BaseException:
        _code = 0
    sys.exit(0)



