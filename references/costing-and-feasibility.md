# 成本、时间与可行性核算

## 1. 成本核算

支持三种来源，按优先级合并：

1. **行项目**：`quantity × unit_price`。消耗品取 `consumables/materials/reagents/items`；设备取 `equipment_usage/hours`；人工取 `person_days × day_rate` 或 `labor_hours × hourly_rate`。CSV 表按 `candidate,item,category,quantity,unit,unit_price,currency` 读取。
2. **分项金额**：`consumable_cost`、`equipment_cost`、`labor_cost`、`overhead`、`shipping_cost` 等。若同类已有行项目，则不再重复累加。
3. **显式总额**：`total_cost/cost_total/estimated_cost/budget`。仅当没有分项时直接采用，`basis=declared_total`。

规则：

- `total = Σ 行金额 + Σ 未覆盖的分项`；`per_run_cost × runs`，`one_time_cost` 只计一次。
- 公式写入 `costs[].formula`，逐项写入 `lines[].formula` 与 `locator`。
- 若同时给出分项与总额，差额超过 `max(1.0, 1% × 较大值)` 时记 `arithmetic_mismatch`，**以分项之和为准**，总额保留在 `stated_total`。
- 货币默认取 case 的 `currency`，否则 CNY。只有 case 明确给出 `fx_rates` 时才换算，并在公式中写出“金额 × 汇率 = 结果”。
- 多币种且无汇率：记 `mixed_currency_without_fx`，金额子项不参与评分，绝不按 1:1 混算。

## 2. 时间核算

分项顺序固定为：`sample_prep_h` + `run_h` + `queue_wait_h` + `characterization_h` + `rework_h`。

- 单位只在显式出现时换算：`min/分钟 ÷60`、`day/天 ×24`、`week/周 ×168`，h 为基准。
- 字段名本身以 `_h` 结尾且无单位时按小时处理，并在 `lines[].note` 中写明。
- 同时有分项与总额时做一致性检查；差额超过 `max(0.25 h, 1%)` 记 `arithmetic_mismatch`，以分项为准。
- 时间窗口来自 case 的 `time_window_h` 或 `time_window_days`；超窗记 `over_time_window`。

## 3. 可行性档位

| 档位 | 中文 | 分值 | 判定 |
|---|---|---|---|
| `ready` | 已具备 | 1.0 | 所有必需资源均为 available/in stock/owned/已具备 |
| `conditional_outsource` | 可外协 | 0.6 | 无不可用项，但存在外协/外部合作 |
| `conditional_purchase` | 需采购 | 0.4 | 无不可用项，但存在采购/订货 |
| `not_feasible` | 不具备 | 0.0 | 任一必需资源 unavailable/不具备 |
| `unknown` | 未确认 | null | 无资源信息或全部状态未知 |

聚合规则：任一“不具备” → 不具备；否则任一“需采购” → 需采购；否则任一“可外协” → 可外协；全部“已具备” → 已具备；否则未确认。

## 4. 硬约束检查

- **预算**：`cost_total > budget` → `over_budget`；默认硬约束，候选保留在表中但不进入推荐。
- **时间窗**：`time_total_h > time_window_h` → `over_time_window`。
- **采购提前期**：`lead_time_days > time_window_days` → `lead_time_exceeds_window`。
- **参数窗口**：case 的 `parameter_domains` 中每个 `{min,max}` 与候选 `parameters` 对照，越界 → `parameter_out_of_domain`。
- 以上开关集中在 `assets/policy.json` 的 `constraints`，可显式改为非硬约束；改动后必须重跑并复核。

所有约束冲突写入 `conflicts[]`，格式为 `{type, candidate, detail, resolution}`；被排除的原因写入 `feasibility[].reasons`，不删除候选行。
