# 基准对照报告：候选方案比较与选择

本报告由 `bench/run_bench.py` 生成，内容固定可复现；重复运行字节一致。

## 对照协议

1. 每个 case 在运行前已写好金标准（`bench/gold/`），winner 由硬约束唯一确定。
2. 技能侧：把该 case 单独复制到隔离目录，执行一次
   `python scripts/run_skill.py --case <隔离目录>/case.json --out <临时目录>/result.json --work <临时目录>/work`。
3. 基线侧：同一份 case 字节，直接取 `objective_fit` 最大的候选，忽略预算、货期、资源可用性与缺失数据。
4. 两侧使用同一金标准判分，不调参、不筛选 case、不修改引擎。

## 指标定义

- **winner 正确**：输出的 winner 与金标准 winner 完全一致。
- **缺失检出数**：`missing_data` 中 `候选:字段` 单元格的条数；基线按定义恒为 0。
- **缺失集合匹配**：检出的 `候选:字段` 集合与金标准 `missing_or_unsupported` 完全一致。

## 逐例结果

| case | 金标准 winner | 技能 winner | 基线 winner | 技能正确 | 基线正确 | 技能缺失检出 | 基线缺失检出 | 缺失集合匹配 |
|---|---|---|---|---|---|---|---|---|
| bench-budget-001 | B | B | A | 是 | 否 | 1 | 0 | 是 |
| bench-lead-time-001 | B | B | A | 是 | 否 | 2 | 0 | 是 |
| bench-resource-001 | C | C | A | 是 | 否 | 2 | 0 | 是 |

## 汇总

- case 数：3
- winner 正确数：技能 3 / 基线 0
- 缺失检出数：技能 5 / 基线 0
- 缺失集合与金标准完全一致的 case 数：3 / 3

## 复现

```bash
python bench/run_bench.py
```

运行后在 `bench/` 生成 `bench_metrics.json` 与 `bench_report.md`；两次运行可用文件哈希比对。

## 已知边界

- case 均为合成数据，规模小，覆盖预算、时间窗、采购货期、关键资源缺失四类硬约束。
- 每个 case 的 winner 都因其余候选违反硬约束而唯一，不检验多个 eligible 候选之间的权重排序。
- 报告只记录判定结果，不评价推荐理由的文字质量。

