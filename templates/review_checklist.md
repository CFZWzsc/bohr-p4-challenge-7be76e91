# 复核清单模板：候选实验方案比较

对一次比较结果逐项复核，任一项不通过都要在复核记录的对应位置写明原因，不得补造数值或候选。

## 1. 输入与契约

- [ ] `case_id`、`status` 非空，`status` 与实际情况一致。
- [ ] `output_contract` 中的每个键都出现在结果里；无法映射的键在 `contract_extras` 中有说明。
- [ ] 候选数量与输入一致，没有凭空新增或静默丢弃候选。

## 2. 比较矩阵完整性

- [ ] 每个候选在 `comparison_table` 中都有一行。
- [ ] 每个非空单元格都有 `locator`，可按 `case.json#/...`、`*.md#Lx`、`*.csv#row=N` 回查。
- [ ] 单位显式（成本为货币、时间为 h、目标契合为 0–1），不存在未声明的换算。
- [ ] 归一化方向正确：成本、时间、风险为越低越好。

## 3. 缺失数据

- [ ] 缺失值一律为 `null`，没有填 0、均值或“合理估计”。
- [ ] 每个缺失单元格都在 `missing_data` 中登记，处理方式含 `no imputation`。
- [ ] 明确缺失维度已从加权分母剔除，并给出 `weight_coverage` 与 `conservative_score`。
- [ ] 若缺失数据的最有利情形会改变结论，`would_change_choice` 有对应语句且 `confidence` 不高于 medium。

## 4. 成本与时间核算

- [ ] `cost_total` 与 `costs[].lines` 的金额之和一致；不一致时记 `arithmetic_mismatch` 并以分项为准。
- [ ] 每条金额公式可按 `quantity × unit_price` 或 `hours × rate` 复算。
- [ ] `time_total_h` 与时间分项之和一致；`min/day/week` 换算只在声明单位时发生。
- [ ] 预算、时间窗、采购货期三类硬约束逐候选核对：超限者保留在表中但标为不可推荐，并写明冲突类型。

## 5. 结论与证据一致性

- [ ] `recommendation.selected` 只从 eligible 候选中产生。
- [ ] `decisive_factors` 写清首选相对次选在各维度的差值与权重，方向（优势/代价）无误。
- [ ] `rejected` 覆盖每个落选候选，给出首要差距或不可行原因。
- [ ] `sensitivity` 含权重扰动、权重扫描阈值、缺失数据最好/最坏情形、逐个资源降级的结果。
- [ ] `would_change_choice` 具体到“补什么数据、改什么资源、权重到多少”，不是泛泛而谈。
- [ ] 结论中出现的每个数字都能在比较表或成本/时间分项中找到出处。

## 6. 复核记录

- [ ] 复核结论已写入输出目录的 `run-review.md`。
- [ ] `status != completed` 时写明原因，且未补造候选或数值。
- [ ] 所有无法回查的单元格都在 `uncertainty` 中说明。
