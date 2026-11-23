---
name: aligned-candidate-plan-comparison
description: Use when an experimental-design case supplies several candidate or versioned experiment plans and asks which one to choose, why, and what would change the choice; parses case.json and material files, places all plans on one comparable matrix with explicit units, cost/time arithmetic, feasibility levels, weighted scoring, missing-data accounting, sensitivity and cell-level locators.
---

# 候选实验方案横向比较与选择

## 用途

把 2 个及以上候选实验方案放到同一张可比矩阵上，统一回答五个问题：

1. **目标**：哪个方案最契合研究目标与终点？
2. **风险**：各方案的主要风险、等级、是否有缓解措施？
3. **成本与时间**：各方案要花多少钱、多少小时，分项如何加总？
4. **可行性**：按当前资源，是已具备、可外协、需采购，还是不具备？
5. **证据**：每个判断能否定位到 case.json 或材料文件的具体位置？

输出包含 `candidates`、`comparison_table`、`scores`、`ranking`、`recommendation`、`costs`、`feasibility`、`risks`、`sensitivity`、`missing_data`、`conflicts`、`evidence`、`uncertainty`、`run_log`、`summary`，并逐键满足运行时 `output_contract`。

## 适用条件

- 输入中存在 **2 个及以上** 候选方案（`candidates/options/protocols/plans/plan_versions/arms` 之一，或材料文件中按候选分节）。
- 需要横向比较，而不是只优化单个方案。
- 允许部分字段缺失：缺失会显式记录，不做静默填补。
- 需要给出推荐、理由、舍弃原因，以及“什么证据会改变选择”。

## 不适用场景

- 只有一个方案，只需可行性审查或参数优化（仍可运行，但 `status=insufficient_input`，不制造比较）。
- 需要生成全新实验设计、写论文、做统计分析或调用仪器。
- 需要联网查价、抓取供应商页面（本 skill 离线、仅用输入文件）。
- 输入是二进制表格（.xlsx/.pdf）；请先转成 CSV/Markdown/JSON 文本。

## 输入形态

`--input` 可以是目录，也可以是 `case.json` 路径。目录内约定：

```text
/input/
  case.json                     # 必需：case_id、候选、约束、output_contract
  task.md                       # 可选：任务说明
  materials/*.md|*.txt|*.json|*.csv
```

候选来源：

- `case.json` 中的候选列表；每项通常含 `id/name`、`objective_fit`、`risk_level`、`resources`、`parameters`。
- 材料文件中的 `## Candidate A` / `### 方案A` 分节，使用 `key: value` 行。
- CSV 表格，首行含 `candidate` 列；成本行建议列为 `candidate,item,category,quantity,unit,unit_price,currency`。
- JSON 材料中的候选列表或候选对象。

case 级设置：`budget`、`time_window_h/time_window_days`、`currency`、`weights`、`objectives`、`parameter_domains`、`fx_rates`、`output_contract`。

## 调用方式

平台内固定命令：

```bash
python /skills/weekly-skill/scripts/run_skill.py --input /input --work /app/work --out /app/output/result.json
```

本地或示例：

```bash
python scripts/sk_entry.py --input examples/demo-case --out /tmp/result.json --work /tmp/work
```

参数：

- `--input`：输入目录或 case.json，默认 `/input`。
- `--work`：中间日志目录，默认 `/app/work`。
- `--out`：结果文件或目录，默认 `/app/output/result.json`；同目录会写 `run-review.md`。
- `--case`：直接指定 case.json（可选）。

`run_skill.py` 是薄封装：无论参数异常、输入损坏还是内部错误，都返回退出码 0，并写出结构化 `result.json` 与 `run-review.md`。

## 比较口径

### 规范字段与单位

| 维度 | 字段 | 单位 | 方向 |
|---|---|---|---|
| 目标契合 | `objective_fit` | 0–1 | 越高越好 |
| 风险 | `risk_level` / `risk_score` | 序数 / 0–1 | 越低越好 |
| 成本 | `cost_total` | 货币（默认 CNY） | 越低越好 |
| 时间 | `time_total_h` | h | 越低越好 |
| 可行性 | `feasibility` / `feasibility_score` | 档位 / 0–1 | 越高越好 |
| 证据 | `evidence_count` / `evidence_strength` | 条 / 加权条 | 越高越好 |

### 归一化

- 每个维度在候选之间做 min-max；方向为“越低越好”时取反。
- 单一候选或全相等时该维度记 1.0。
- 缺失值不参与 min/max，也不进入该候选的加权分母；同时给出“缺失按 0”的 `conservative_score`。
- 成本维度内部再分：金额 0.65、时间 0.35；缺一项时按剩余内部权重归一。
- 权重默认见 `assets/policy.json`；case 的 `weights` 优先，缺失项补齐后归一，并在 `uncertainty` 中记录。

## 成本/时间核算规则

**成本**：

- 行项目：`quantity × unit_price`；设备 `hours × rate`；人工 `person_days × day_rate` 或 `labor_hours × hourly_rate`。
- 分项金额：`consumable_cost/equipment_cost/labor_cost/overhead` 等；同类已有行项目时不重复加总。
- 显式总额：`total_cost/cost_total/estimated_cost/budget`，仅在无分项时直接采用。
- `per_run_cost × runs`；`one_time_cost` 只计一次。
- 总额 = 分项之和；若与显式总额相差超过 `max(1.0, 1%)`，记 `arithmetic_mismatch`，**以分项为准**，并保留 `stated_total`。
- 币种换算只在 case 明确给出 `fx_rates` 时执行，公式中写出汇率；否则多币种记 `mixed_currency_without_fx`，金额子项不评分。

**时间**：

- `sample_prep_h + run_h + queue_wait_h + characterization_h + rework_h`。
- 只在显式单位出现时换算：`min ÷60`、`day ×24`、`week ×168`；公式与单位写入 `lines[].note`。
- 分项与总额不一致时记 `arithmetic_mismatch`，以分项为准。

每条公式写入 `costs[].lines[].formula` 与 `comparison_table[].cost_formula/time_formula`，可直接复算。

## 可行性判定

| 档位 | 中文 | 分值 | 触发条件 |
|---|---|---|---|
| `ready` | 已具备 | 1.0 | 所有必需资源 available/已具备 |
| `conditional_outsource` | 可外协 | 0.6 | 存在外协/外部合作，无不可用项 |
| `conditional_purchase` | 需采购 | 0.4 | 存在采购/订货，无不可用项 |
| `not_feasible` | 不具备 | 0.0 | 任一必需资源 unavailable/不具备 |
| `unknown` | 未确认 | null | 无资源信息或全部未知 |

硬约束另查：预算、时间窗、采购提前期、参数域。冲突写入 `conflicts[]` 与 `feasibility[].reasons`；候选保留在表中但不进入推荐。

## 风险与异常

- 风险标签 low/medium/high/critical 映射 0.2/0.5/0.8/1.0；数值按 0–1、0–5、0–10 量表显式换算。
- 多个风险条目取最高严重度；声明等级与条目最高值差异过大时记 `risk_declared_conflict`。
- 已处理的异常类型：
  - `arithmetic_mismatch`：总额与分项不符，以分项为准。
  - `mixed_currency_without_fx`：多币种且无汇率，金额不混算。
  - `over_budget` / `over_time_window` / `lead_time_exceeds_window`：超硬约束，标记不可推荐。
  - `parameter_out_of_domain`：参数越出 case 给定窗口。
  - `unknown_time_unit` / `unrecognized_risk_level`：无法识别则留空，不猜。
  - `risk_declared_conflict`：声明风险与条目冲突。
- 任何异常都不会中断运行；`status` 如实反映结果。

## 推荐与敏感性

- `recommendation.selected` 只在 `eligible` 候选中产生；不可行候选给出原因，不删除。
- `decisive_factors`：首选相对次选在各维度的归一化差与权重，正值为优势，负值为代价。
- `rejected`：每个落选候选的首要差距或不可行原因。
- 敏感性每次运行都做：
  1. 每个权重 ×0.75 / ×1.25；
  2. 每个权重 0.05–0.95 扫描，记录首次翻转阈值；
  3. 每个缺失维度取最好/最坏情形；
  4. 依次把每个可行候选降级为不可行。
- `would_change_choice` 用自然语言列出“补什么数据/改什么资源/权重到多少会换选”。

## 缺失数据政策

- 缺失一律 `null`，**绝不**填 0、均值、行业惯例或“合理估计”。
- 每个缺失单元写入 `missing_data`：候选、字段、原因、影响、处理方式（固定含 `no imputation`）、定位。
- 缺失维度会从加权分母剔除并降低 `weight_coverage`，同时用 `conservative_score` 检查是否因缺失而虚高。
- 若缺失数据的最有利情形会改变选择，`would_change_choice` 必须出现对应语句，`confidence` 不高于 medium。

## 异常处理与状态

| status | 含义 | 行为 |
|---|---|---|
| `completed` | 比较完成，契约键齐全 | 缺失字段照常记录，不代表数据完整 |
| `partial` | 有候选但全部不可行，或关键输出受限 | 仍给出表与原因 |
| `insufficient_input` | 未识别到候选，或候选少于 2 个 | 不制造比较 |
| `failed` | case 缺失、损坏或不可读 | 写结构化失败结果，退出码仍为 0 |

任何情况下都写 `run_log`、`errors`、`uncertainty`，并保证 `result.json` 可被解析。

## 输出契约映射

运行时 `case.output_contract` 的每个键都会写入结果：

- 直接键：`candidates`、`comparison_table`、`recommendation`、`costs`、`feasibility`、`risks`、`evidence`、`uncertainty`、`summary`、`scores`、`ranking`、`sensitivity`、`missing_data`、`conflicts`、`run_log`。
- 别名：`options/protocols/plans → candidates`；`table/matrix → comparison_table`；`decision/choice/selection → recommendation`；`citations/references/sources → evidence`；`notes/assumptions/limitations → uncertainty`；`state/stats → summary`。
- 未知键：尝试按候选级同名字段做 best-effort 表；仍无法映射时保留键，值置空，并在 `contract_extras` 说明。
- 另含 `case_id`、`status`、`review_markdown`、`run_review_path`、`result`（核心结果副本）。

## Agent 运行指令

1. 运行上面的固定命令；不要改写输入，不要联网补数据。
2. 打开 `result.json`，逐项确认 `output_contract` 的每个键都存在。
3. **逐格复核** `comparison_table[].cells[*].locator`：按 `case.json#/...`、`*.md#Lx`、`*.csv#row=N` 回查原始值；无法回查的格子必须在 `uncertainty` 中说明。
4. 用 `costs[].lines[].amount` 与 `time` 分项复算 `cost_total` / `time_total_h`，与 `formula` 对照。
5. 检查 `missing_data`：每个缺失字段是否为 `null`、是否含 `no imputation`、是否出现在 `uncertainty`。
6. 检查 `recommendation.decisive_factors` 与 `sensitivity.statements` 是否回答了“为什么”和“什么会改变选择”。
7. 把复核结论写入 **`/app/output/run-review.md`**（脚本会先生成草稿到输出目录；确认后覆盖为最终版）。内容至少包含：比较表、成本/时间公式、评分与排名、推荐理由、敏感性、缺失数据、冲突、逐格定位结果、自检清单。
8. 若 `status != completed`，在复核文件中明确说明原因，不得补造候选或数值。

## 自检清单

- [ ] `case_id` 与 `status` 非空。
- [ ] 每个候选在 `comparison_table` 中都有一行，且至少有一个非空测量值。
- [ ] 每个非空单元格都有 `locator`，可回查。
- [ ] `cost_total` 与分项之和一致；`time_total_h` 与分项之和一致。
- [ ] 单位显式；未经声明的换算不存在。
- [ ] 缺失字段在 `missing_data` 中为 `null`，处理方式含 `no imputation`。
- [ ] `conflicts` 中每个冲突都有 `resolution`。
- [ ] `recommendation` 含 `decisive_factors`、`rejected`、`would_change_choice`。
- [ ] `sensitivity` 含权重扰动、缺失压力与资源降级结果。
- [ ] `output_contract` 全部键存在；未知键在 `contract_extras` 中有说明。
- [ ] 运行退出码为 0（即使输入为空或损坏）。

## 文件结构

```text
SKILL.md
GITHUB_URL.txt              # 保持原样
assets/policy.json          # 权重、单位、可行性档位、容差、约束开关
references/
  comparison-fields.md
  costing-and-feasibility.md
  recommendation-and-sensitivity.md
scripts/
  sk_entry.py               # 主引擎
  run_skill.py              # 薄封装，永不崩溃
examples/
  quickstart.md
  demo-case/
    case.json
    materials/costs.csv
    materials/time_and_risk.md
```

## 最小示例（合成，仅演示接口）

```bash
python scripts/run_skill.py --input examples/demo-case --out /tmp/demo.json --work /tmp/demo-work
```

预期：3 个候选全部进入比较表；成本 5630 / 5500 / 5320 CNY，时间 78 / 64 / 94 h；C 的证据缺失进入 `missing_data`；输出含九个契约键；退出码 0。该示例的数字全部为合成值，不可用于任何真实决策。
