# 候选实验方案横向比较与选择（skill 包）

把 2 个及以上候选实验方案放到同一张可比矩阵上，统一给出：选哪个、为什么、落选者差在哪、什么数据或条件会改变选择。适用于实验设计类 case 的方案比较与选择，不生成全新实验设计，也不联网查价。

## 1. 放什么、得到什么

- 输入：一个 `case.json`（必需）加上可选的 `materials/` 文本材料。
- 输出：`result.json`（含比较表、成本/时间分项、可行性、风险、评分与排名、推荐、敏感性、缺失数据、冲突、证据、不确定性）与同目录的 `run-review.md` 复核草稿。
- 入口 `scripts/run_skill.py` 是薄封装：即使输入缺失或损坏也返回退出码 0，并写出结构化结果，`status` 如实反映情况。

## 2. 单次运行方式

在本包根目录执行：

```bash
python scripts/run_skill.py --input examples/demo-case --out out/result.json --work work
```

也可以直接指定 case 文件：

```bash
python scripts/run_skill.py --case examples/demo-case/case.json --out out/result.json --work work
```

参数说明：

- `--input`：输入目录，或 `case.json` 路径；平台内默认读取约定输入目录。
- `--case`：直接指定 case 文件，优先于 `--input`。
- `--work`：中间日志目录。
- `--out`：结果文件，或以路径分隔符结尾的目录（目录会自动追加 `result.json`）；同目录写 `run-review.md`。

注意：引擎会把 **case 文件所在目录** 下的文本材料一并读入。若同目录存在多个 case 或历史 `result.json`，会被当作材料解析，可能引入额外候选。批量运行时请让每个 case 单独占一个目录（`bench/run_bench.py` 已按此方式隔离）。

## 3. 输入格式

### 3.1 `case.json` 顶层字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `case_id` | string | 案例标识，写入结果 |
| `objective` / `objectives` | string / array | 研究目标；也用于目标契合度的文本兜底 |
| `budget` | number | 总预算，默认货币为 `currency` |
| `time_window_h` | number | 总时间窗，单位小时；与 `time_window_days` 可互相推导 |
| `time_window_days` | number | 时间窗天数，用于校验采购货期是否超窗 |
| `currency` | string | 结算货币，默认 `CNY` |
| `weights` | object | 五维权重，键为 `objective/risk/cost/feasibility/evidence`；缺项补齐后归一 |
| `constraints` | object | 可选的 case 级约束记录（如 `budget_cny`、`time_window_h`） |
| `parameter_domains` | object | 参数允许区间，形如 `{"incubation_temp_c": {"min": 4, "max": 37}}` |
| `candidates` | array | 候选列表，见下 |
| `output_contract` | object/array | 期望出现的结果键；引擎按键名或别名映射 |

### 3.2 候选字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` / `name` | string | 候选标识与显示名 |
| `objective_fit` | 0–1 | 目标契合度，越高越好（缺失时退化为目标文本重合，置信度低） |
| `risk_level` | string | `low/medium/high/critical`，映射 0.2/0.5/0.8/1.0 |
| `risk_score` | number | 数值风险，0–1 直接使用，0–5、0–10 会显式换算 |
| `estimated_cost` / `cost_total` / `total_cost` | number | 声明总成本；用于预算硬约束 |
| `time_total_h` / `total_hours` | number | 声明总时间，单位 h；用于时间窗硬约束 |
| `parameters` | object | 实验参数，用于参数域校验（见限制说明） |
| `resources` | array | 必需资源，见下 |
| `evidence` | array | 证据条目，元素可为字符串或 `{"claim": ..., "source": ...}` |

资源条目字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `name` | string | 资源名 |
| `availability` | string | `available` / `needs purchase` / `outsource` / `unavailable` 等 |
| `lead_time_days` | number | 采购或预约提前期（天） |

### 3.3 可选材料文件

`materials/` 下支持 `.md`、`.txt`、`.json`、`.csv`：

- 成本 CSV 建议表头：`candidate,item,category,quantity,unit,unit_price,currency`。
- 时间/风险 Markdown 建议每个候选一个小节（如 `## Candidate A`），下面用 `key: value` 行。
- case.json 中已给的成本/时间字段与材料中的分项不重复加总。

## 4. 比较口径与权重

| 维度 | 规范字段 | 单位 | 方向 | 默认权重 |
|---|---|---|---|---|
| 目标契合 | `objective_fit` | 0–1 | 越高越好 | 0.25 |
| 风险 | `risk_level` / `risk_score` | 序数 / 0–1 | 越低越好 | 0.20 |
| 成本与时间 | `cost_total` / `time_total_h` | 货币 / h | 越低越好 | 0.20 |
| 可行性 | `feasibility` / `feasibility_score` | 档位 / 0–1 | 越高越好 | 0.20 |
| 证据 | `evidence_count` / `evidence_strength` | 条 / 加权条 | 越高越好 | 0.15 |

- 每个维度在候选之间做 min-max 归一化；单一候选或全相等时该维度记 1.0。
- 成本维度内部再分：金额 0.65、时间 0.35；缺一项时按剩余内部权重归一。
- 缺失值不参与 min/max，也不进入该候选的加权分母；同时给出“缺失按 0”的 `conservative_score`，并记录 `weight_coverage`。
- 证据按类型加权：文献 1.0、设备手册 0.9、SOP 0.8、预实验 0.8、报价 0.7、记录 0.6、未知 0.5。

## 5. 判定阈值与硬约束

- **预算**：`cost_total > budget` 记为 `over_budget`，候选保留在表中但不进入推荐。
- **时间窗**：`time_total_h > time_window_h` 记为 `over_time_window`，同上。
- **采购货期**：`lead_time_days > time_window_days` 记为 `lead_time_exceeds_window`，同上。
- **资源缺失**：任一必需资源为 `unavailable` 时可行性为 `not_feasible`，不可推荐；资源信息全缺失为 `unknown`，同样不可推荐。
- **可行性档位**：已具备 1.0、可外协 0.6、需采购 0.4、不具备 0.0、未确认 `null`。
- **算术容差**：成本 `max(1.0, 1%)`，时间 `max(0.25 h, 1%)`；超出即记 `arithmetic_mismatch`，以分项之和为准并保留声明总额。
- **停止规则（引擎输出的 `stop_rule`）**：前两名加权分差 ≥ 0.05 且权重覆盖 ≥ 90% 时可直接决定；否则建议对关键维度补一次确认性测量。并列判定使用 `1e-4` 的容差。
- **结论门槛**：`recommendation.selected` 只从 eligible 候选中产生；推荐含 `decisive_factors`、`rejected`、`would_change_choice`。缺失数据若可能改变结论，`confidence` 不高于 medium。

可复用的阈值模板见 `templates/thresholds.json`。

## 6. 输出字段

| 字段 | 内容 |
|---|---|
| `candidates` | 候选概览（目标契合、风险、成本、时间、可行性、证据数、缺失维度） |
| `comparison_table` | 逐格比较矩阵，每格带 `value/unit/status/locator`，并含成本/时间公式 |
| `scores` | 权重来源、归一化方式、逐候选加权分与保守分、原始值 |
| `ranking` | 排名，标注是否 eligible |
| `recommendation` | 选中方案、理由、决定性因素、落选原因、翻转条件、置信度 |
| `costs` | 逐候选成本分项、公式、声明总额与定位 |
| `feasibility` | 逐候选可行性档位、资源明细、预算/时间/货期校验结果与原因 |
| `risks` | 风险等级、评分、高风险计数、缓解覆盖与定位 |
| `sensitivity` | 权重扰动、权重扫描阈值、缺失数据压力、资源降级 |
| `missing_data` | 每个缺失单元格的候选、字段、原因、影响、处理方式（含 `no imputation`）与定位 |
| `conflicts` | 算术不符、超预算、超时间窗、货期超窗、参数越界等，均带 `resolution` |
| `evidence` | 输入文件哈希与逐条定位，便于回查 |
| `uncertainty` | 假设、缺失影响、权重敏感性等提示 |
| `run_log` | 运行步骤记录 |
| `summary` | 候选数、eligible 数、状态等汇总 |

`case.output_contract` 中的键会全部写入结果；常见别名会映射到上表字段（如 `table → comparison_table`、`decision → recommendation`），未知键在 `contract_extras` 中说明。

## 7. 依赖与限制

- 仅依赖 Python 标准库，离线运行，不访问网络。
- 只接受文本输入；`.xlsx`、`.pdf` 等二进制表格需先转成 CSV/Markdown/JSON 文本。
- 缺失数据一律保持 `null`，不填 0、均值或行业惯例；缺失维度会降低 `weight_coverage`。
- 目标契合度在缺少显式 `objective_fit` 时按目标文本重合估算，置信度低，不应作为真实测量的替代。
- 只有一个候选时 `status=insufficient_input`，不制造比较。
- 参数域校验的限制：`parameter_domains` 虽在协议中标记为硬约束，当前引擎不会从 case.json 读取并据此否决候选。依赖参数域的结论必须人工复核。详见 `bench/README.md` 的“已知边界”。
- 批量运行时注意第 2 节的目录隔离要求，避免同目录其他 JSON 被当作材料。

## 8. 目录结构

```text
submission/
  SKILL.md                     # skill 说明与运行指令
  GITHUB_URL.txt               # 公开代码地址
  README.md                    # 本文件：复用者文档
  assets/policy.json           # 默认权重、单位、档位与容差
  references/                  # 字段口径、成本与可行性、推荐与敏感性
  scripts/
    sk_entry.py                # 主引擎
    run_skill.py               # 薄封装，永不崩溃
  examples/                    # 合成示例与 quickstart
  templates/
    thresholds.json            # 可复用权重/阈值模板
    review_checklist.md        # 可复用复核清单
  bench/
    cases/                     # 合成对照案例
    gold/                      # 各 case 的金标准
    run_bench.py               # 公平对照脚本
    README.md                  # 对照协议与指标
    bench_metrics.json         # 运行产物（逐例指标）
    bench_report.md            # 运行产物（表格报告）
```

## 9. 复现与自检

```bash
python bench/run_bench.py
```

脚本对每个 case 运行一次技能，并与固定金标准对比 winner 与缺失单元格，写出 `bench/bench_metrics.json` 和 `bench/bench_report.md`；重复运行字节一致。复核单次结果时，可按 `templates/review_checklist.md` 逐项检查比较表完整性、缺失数据、成本/时间核算与结论证据一致性。
