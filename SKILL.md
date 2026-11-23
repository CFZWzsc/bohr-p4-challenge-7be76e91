---
name: aligned-candidate-plan-comparison
description: Use when an experimental-design case supplies several candidate or versioned experiment plans and asks which one to choose, why, and what is rejected; run scripts/run_skill.py to place all plans on one comparable matrix with explicit units, cost and time arithmetic, weighted scoring, rejection reasons and sensitivity.
---

# 候选实验方案对齐比较与选择

## 用途与适用条件

把 2–5 个候选实验方案放到同一张可比矩阵上，统一目标、硬约束、变量、资源、时间、成本、风险与证据字段，给出可辩护的选择、舍弃理由和敏感性说明。

适用于 `aligned_plan_comparison_and_choice` 类案例：每例含 3 个版本化候选方案与前瞻性资源/价格/预约契约。

不适用：从零设计新方案、单篇文献综述、实验数据统计分析。比较结论不替代实验室设备核查或伦理审查。

## 输入

- `/input/case.json`（可用 `--case`）：`case_id`、`output_contract`；常见可选键 `plans`/`candidates`/`plan_versions`、`criteria`/`weights`、`resources`/`equipment`/`materials`、`budget`、`time_window_h`、`constraints`、`evidence`。
- `/input/task.md`（可选）：补充选择偏好。
- 输出默认 `/app/output/result.json`。

## 处理流程（对应评分维度）

1. **固定口径（任务完成度）**：先建立统一字段 `objective_fit`、`equipment_readiness`、`time_hours`、`cost_total`、`risk_level`、`evidence_strength`、`feasibility`、`parameter_range`；每个字段声明单位、来源和缺失状态，避免各方案各用一套描述。
2. **逐方案填表（完整性）**：按同义词（`cost`/`budget`/`price`、`duration`/`hours`、`risk`、`evidence`/`reference`）从每个方案提取；未声明写 `unknown`，不按 0 计。
3. **成本与时间核算（正确性）**：耗材按数量×单价，机时按小时×费率，人工单列；总时长区分执行、等待与排期；给出算术式与分项。
4. **可行性分档（正确性）**：资源状态分为 `available`/`outsource`/`procure`/`unavailable`/`unknown`；只有全部可用才记 `feasible_now`，否则 `conditional` 或 `not_feasible`。
5. **统一评分（可核验性）**：按案例给定权重，缺省等权；成本、时间、风险为负向指标，目标契合、证据强度、可行性为正向指标；用 min–max 归一化，输出每个方案的逐项分值、加权总分与排名。
6. **选择与舍弃（可辩护性）**：给出首选方案、次选、每个落选方案的具体舍弃理由（哪一项差距、差多少），不以“综合更优”搪塞。
7. **敏感性（创新增益）**：对每个权重分别做 ±25% 扰动，记录首选是否改变；不稳健时明确写出对哪些权重敏感。
8. **证据与异常（可靠体验）**：为每个判断挂来源路径；处理方案全部不可行、字段全缺失、成本超预算、时间窗冲突，并给出替代路径或转人工节点。

## 输出契约

| 字段 | 含义 |
|-|-|
| `case_id` | 与输入一致 |
| `output_contract` 各字段 | 命中则填真实值，否则 `null` + `contract_notes` |
| `status` | `success` / `partial` / `insufficient_input` / `failed` |
| `result` | `criteria`、`comparison_matrix`、`scores`、`ranking`、`choice`、`rejection_reasons`、`sensitivity`、`conditions`、`risks` |
| `evidence` | 输入哈希、字段来源路径、规则版本 |
| `uncertainty` | 缺失字段、权重假设、不可比项 |
| `errors` / `stats` | 真实错误与方案数/未知字段数 |

## 异常处理表

| 情况 | 处置 | 状态 |
|-|-|-|
| `case.json` 缺失/非法 | 空骨架 + `case_load_failed` | `failed` |
| 少于 2 个方案 | 不做比较，说明需要候选 | `insufficient_input` |
| 方案字段缺失 | 该格 `unknown`，不参与该指标归一化 | `partial` |
| 全部方案不可行 | 首选为 null，给放宽约束或补充资源的路径 | `partial` |
| 成本或时间单位不一致 | 标 `unit_mismatch`，不强行换算 | `partial` |
| 权重未给出 | 等权并写入 `uncertainty` | `partial` |
| 首选对权重敏感 | `sensitivity.stable=false`，列出翻转条件 | `partial` |
| 方案自相矛盾（分项和≠声明总量） | 以分项为准并记 `arithmetic_mismatch` | `partial` |

## 限制

- 只比较输入中的方案，不引入外部设备价格或文献结论。
- 评分是决策辅助，不是科学正确性的证明；权重改变会改变排名。
- 不把 `unknown` 当作满足或零成本。
- 不生成真实供应商报价或设备排期承诺。

## 最小调用示例（示例，非官方案例结果）

```bash
python /skills/weekly-skill/scripts/run_skill.py --case /input/case.json --out /app/output/result.json --work /app/work
```

示意输入：`{"case_id":"synthetic-compare-demo","output_contract":{"comparison_matrix":"array","choice":"object"}}`。示意输出保留 `case_id`、`comparison_matrix`、`choice`、`status`；少于两个方案时 `insufficient_input`，`choice` 为 `null`。仅为接口示例。


## 交付保证与评分对齐

调用顺序（固定）：

1. 先运行包内脚本（若存在）：`python scripts/run_skill.py`（默认读 `/input/case.json`，写 `/app/output/result.json`）；路径不同时用 `--case` / `--out` 指定。
2. 再完成脚本无法自动完成的实质工作（译文、论述、图表、修订、结论等），把结果写回 `result.json` 对应字段。
3. 最后自检：`case_id` 与输入一致；`output_contract` 每个字段都存在；`status` 为 `completed`（仅在确实缺输入时为 `partial`）；无 `pending` 占位；数字、引用、来源可逐条回溯。

运行保证：

- 输入缺失、JSON 损坏、字段异常、输出目录不存在时，仍须写出结构化 `result.json` 并正常结束，不得崩溃或非零退出。
- 不联网、不伪造数据、不声称平台评分或官方案例结果。
- 交付物必须是可直接编辑与复核的成品，而不是流程说明。

评分对齐（本题五个维度）：

- 实际效果（40）：完整产出任务要求的最终成品，覆盖全部输入条目，可直接进入修改流程。
- 使用增益（25）：体现相对基础 Agent 的可验证改进（结构化、术语/数字/引用核对、可编辑性）。
- 创新增益（15）：保留方法学增量（分块、对齐、二次校验、版本比对等），并用结果证明其价值。
- 可靠体验（10）：异常输入有明确降级与说明，不同长度/文体/重复运行下稳定产出。
- 生态贡献（10）：用途、调用、输入输出、限制、示例、维护信息齐全，资源可被他人复用。

## 最终交付强制要求

1. **调用 Agent 必须交付成品，不是流程说明**：脚本产出只是索引、核对或规格骨架；调用 Agent 必须在同一 `result.json` 中补齐本题要求的最终产物（正文/译文/审稿意见/综述/分析结论/图表源文件与导出件/幻灯片页内容与讲稿/实验方案等）。交付字段为空、只有标题骨架，或含 `pending`、`TODO` 之类占位，一律视为未完成。
2. **必须覆盖全部输入条目**：输入中的每个章节、问题、文献、图、页面、指标都要有对应条目，不得只处理示例或首条；确实缺失的条目写入 `uncertainty` / `limitations` 并说明原因，不得静默跳过。
3. **必须自检后再交付**：`case_id` 与输入一致；`output_contract` 每个字段都存在；状态值取本题契约规定的枚举；数字、单位、引用、来源可逐条回溯；结果内部无自相矛盾。
4. **参数等价**：`python scripts/run_skill.py --case <输入> --out <输出>` 与 `--output <输出>` 等价；默认 `/input/case.json` → `/app/output/result.json`。
5. **平台用 3 个固定案例分别运行**：逻辑要由输入驱动，不针对某一份示例硬编码；字段命名差异走别名匹配与显式降级，并在 `uncertainty` 记录假设。
