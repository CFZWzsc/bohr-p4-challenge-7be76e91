# 比较字段与单位口径

本文件定义 `comparison_table` 的每一格、单位、状态与定位方式。字段名在所有输出中保持稳定，便于逐格回查。

## 1. 五个维度与规范字段

| 维度 | 规范字段 | 单位 | 方向 | 说明 |
|---|---|---|---|---|
| 目标契合 | `objective_fit` | 0–1 比例 | 越高越好 | 优先读取显式 `objective_fit/fit_score/effect_size`；其次用 `objectives_met` 计数；最后才用候选文本与 case 目标做词元重合，并标为低置信 |
| 风险 | `risk_level` / `risk_score` | 序数 / 0–1 | 越低越好 | 标签 low/medium/high/critical 映射 0.2/0.5/0.8/1.0；数值 0–1 直接使用，0–5 或 0–10 量表会显式换算 |
| 成本 | `cost_total` | case 货币（默认 CNY） | 越低越好 | 由分项求和或显式总额；分项公式逐条写入 `costs[].lines[].formula` |
| 时间 | `time_total_h` | 小时（h） | 越低越好 | 由准备/运行/排队/表征/返工分项求和，或显式总额 |
| 可行性 | `feasibility` / `feasibility_score` | 档位 / 0–1 | 越高越好 | 已具备=1.0，可外协=0.6，需采购=0.4，不具备=0.0，未确认=null |
| 证据 | `evidence_count` / `evidence_strength` | 条数 / 加权条数 | 越高越好 | 按文献 1.0、手册 0.9、SOP 0.8、预实验 0.8、报价 0.7、记录 0.6、未知 0.5 加权 |

成本维度得分不是单看金额：`cost` 维度的内部权重为金额 0.65、时间 0.35；两者缺一时只用可用项并按剩余内部权重归一。

## 2. 单元格结构

`comparison_table[].cells[field]` 的每一格为：

```json
{"value": 5630.0, "unit": "CNY", "status": "derived_from_components", "locator": ["materials/costs.csv#row=2"]}
```

- `status`：`declared`（直接声明）、`derived_*`（由分项或规则推导）、`missing`（缺失）。
- `locator`：可回查的位置，格式约定：
  - case.json：`case.json#/candidates/0/objective_fit`
  - Markdown：`materials/notes.md#L12`
  - Markdown 表格：`materials/notes.md#L20:col2`
  - CSV：`materials/costs.csv#row=6`
  - JSON 材料：`materials/plans.json#/0/cost_total`
- 有值但无法定位的情况不应出现；自检会统计 `cells_with_locator`。

## 3. 归一化

- 每个维度在候选之间做 min-max 归一化；方向为“越低越好”时取 `1 - (x-min)/(max-min)`。
- 只有一个候选或所有值相等时，该维度统一记 1.0。
- 缺失值不参与 min/max，也不进入该候选的加权分母；同时计算“缺失按 0”的保守分 `conservative_score`。
- 货币不一致且没有显式汇率时，金额子项整体置空并记 `mixed_currency_without_fx`，时间子项仍可用。

## 4. 常见别名

`candidate`/`option`/`protocol`/`plan` 均视为候选；`cost`/`budget` 视为成本；`citation`/`source`/`reference` 视为证据；`note`/`assumption`/`limitation` 视为不确定性。输出契约中的键会按别名与词元路由到上述规范字段。
