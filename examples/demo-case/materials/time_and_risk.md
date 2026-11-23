# 合成示例材料：时间、风险与证据

> 全部数字为演示用合成值，不是供应商报价、设备手册或真实排期。

## Candidate A：酶标法

- sample_prep_h: 8
- run_h: 24
- queue_wait_h: 36
- characterization_h: 6
- rework_h: 4
- risk_level: medium
- risk_item: 高浓度样本超出线性范围（medium）；mitigation: 预实验确定稀释倍数，超限样本按 1:10 复测
- risk_item: 板间孔位漂移（medium）；mitigation: 每板加入标准曲线与阴性对照
- evidence: SOP-A1 酶标操作规范 2025
- evidence: Manual-Reader 酶标仪手册 2024

## Candidate B：化学发光法

- sample_prep_h: 6
- run_h: 30
- queue_wait_h: 12
- characterization_h: 10
- rework_h: 6
- risk_level: low
- risk_item: 探针批间差异（low）；mitigation: 同一批号完成全部样本并留 10% 复测
- risk_item: 采购到货延迟（low）；mitigation: 提前 2 天锁定货期并准备酶标法作为回退
- evidence: Literature-2023 化学发光定量方法比较
- evidence: Quote-2026-11 探针报价单
- evidence: Log-2025-Q4 同类项目历史记录

## Candidate C：成像定量法

- sample_prep_h: 10
- run_h: 20
- queue_wait_h: 48
- characterization_h: 8
- rework_h: 8
- risk_level: high
- risk_item: 成像系统占用导致排期滑移（high）；mitigation: 预约备用时段，但未确认
- risk_item: 低丰度样本信噪比不足（high）；mitigation: 增加曝光轮次，可能引入光漂白
