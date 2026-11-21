# Finance P3：Capital 证明拒绝原因与历史候选快照的受限元数据盘点（2026-11-21）

## 前置事实
- Finance P2 的323项 Windows 合成回归通过，正式账本SHA `9327b75fa7920294593dd11bb4221255c3f14410551705A98371C111F6B334FC`。84条冲突：Capital首阻断42只、Top10Holder33只、Top10FlowHolder5只、HolderNum4只，解码异常另1只。
- `qmt_capital_semantic_proof.prove_historical_union` 返回具体拒绝类型，如报告期键增删、历史经济字段自身冲突、当前经济字段或报告期变化、缺失m_quarter、重复报告期、格式不明等；先前P2只汇总为SCOPED_M_QUARTER_PROOF_REJECTED，不足以指导下一步的人工复核。
- 任何证明拒绝记录都不意味着可被自动豁免；上游先遇到冲突就停止检查后续表，不能断言全部9表的状态。

## P3 新增
新增 `market_center_finance_pending_snapshot_review.py`，需要明确 `--state-module`、`--market-root`（必须名为AllCycleAStockData）和 `--explicit-readonly`。
- 先运行P2验证账本并固定SHA，使用记录里的规范精确错误码统计全部Capital证明失败的具体类型；未知类型独立统计为UNRECOGNIZED，不装作认证。
- 对每个首阻断表按待审asof最早和最晚的记录确定性选取**最多2只**，每表只查看本表名下历史snapshots文件名/大小及active pin结构和文件是否存在，最多8组。每目录≤256文件，整体≤4096个元数据候选、≤40GiB声明字节，pin≤16KiB；北京时间19:50–20:25保护窗口拒绝盘点。
- 严格限制路径、拒绝symlink、非法名字、无对应快照的active pin及过程中账本SHA变化。不读取Parquet内容、经济字段、财务DAT，也不散列Parquet字节。所有hash真实性、来源真实性、原始历史业务对比均标记**未验证**。
- 结果只含有限股票代码、首阻断表、pending日期/次数、证明拒绝类别以及候选版本文件数量、大小和pin引用结构核对。没有任何QMT请求、下载、修复、调度或状态写入。

## 验收边界
新增9项Windows合成回归（含Capital类别、多表抽样、active pin错配、symlink、schedule保护、账本变化、无原始文件不得宣称完整）。基于已通过的P2 323项，预计匹配 `test_market_center*.py` 的总数332；**本分支没有Windows现场回归，不能宣称通过**。

P3只是样本元数据审计。若希望将旧历史版本与当下QMT缓存经济字段逐行比对，需要另立可复核的、限定输入的只读采样协议；当前不允许任何源覆盖或自动豁免。保持Draft，不合并main/部署。
