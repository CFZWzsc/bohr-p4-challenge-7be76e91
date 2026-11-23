# Quickstart（合成示例）

`examples/demo-case` 是完全合成的 3 候选演示，只用于验证接口、算术与契约，不代表真实实验。

## 运行

在 skill 根目录执行：

```bash
python scripts/sk_entry.py --input examples/demo-case --out /tmp/demo-result.json --work /tmp/demo-work
```

或走薄封装（与平台入口一致，任何异常都返回 0 并写出结构化结果）：

```bash
python scripts/run_skill.py --input examples/demo-case --out /tmp/demo-result.json --work /tmp/demo-work
```

## 预期结果

- 3 个候选全部出现在 `comparison_table`，每格带 `locator`。
- 成本可复算：
  - A：2×850 + 1×450 + 6×180 + 4×600 = 5630 CNY
  - B：1×2200 + 3×120 + 12×95 + 3×600 = 5500 CNY
  - C：4×300 + 8×140 + 5×600 = 5320 CNY
- 时间可复算：A 78 h、B 64 h、C 94 h。
- C 的 `evidence` 字段故意缺失：`missing_data` 出现 `C / evidence_count`，值为 `null`，处理方式含 `no imputation`。
- 输出含 `candidates`、`comparison_table`、`recommendation`、`costs`、`feasibility`、`risks`、`evidence`、`uncertainty`、`summary` 九个契约键。
- `run-review.md` 与 `result.json` 写在同一输出目录。

## 换成自己的案例

1. 新建输入目录，放入 `case.json`；候选可放在 `candidates/options/protocols/plans` 列表中。
2. 材料可放 `.md/.txt/.json/.csv`：
   - 成本：`candidate,item,category,quantity,unit,unit_price,currency`
   - 时间与风险：每个候选一个标题（如 `## Candidate A`），下面用 `key: value` 行。
3. 在 `case.json` 写 `output_contract`（键名可自定义，脚本会别名映射）。
4. 运行后逐格按 `locator` 回查，并确认 `missing_data` 中没有被静默填补的字段。
