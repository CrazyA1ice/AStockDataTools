# P63 · Capital.m_quarter 九表修复前置只读预览

2026-11-18：上一阶段对五市场 25 个分层抽样只进行了 Capital 历史并集证明；25/25 候选，39 条 m_quarter 值变化，但这不能证明其他八张财务表不会同时出现新增、缺失或修订。

新建 `qmt_capital_nine_table_repair_preview.py`：

- 最多**显式指定五只**股票（默认一只），必须在正式 checkout 运行。仅使用 QMT **已有缓存**，mode=cache，绝不调用 download_financial_data2
- 运行前验证身份、已隔离待审原因 Capital、原私有财务账本；在 LIVE 共享 writer 锁下完整读取所有九张财务表；账本前后 SHA256 一致，工作过程仅在系统临时目录写短暂 worker 输出
- Capital：调用全历史并集严格 `prove_historical_union`，要求日期集合完全一致，**仅 m_quarter 字段不同**
- 其余八表：复用正式导入器 `_prior_rows`，逐条比较过去所有已选历史快照的 raw row multiset（排除供应商行位置索引 `_index`）。**本次试点只允许完全一致**；新公告/财务修订即便合理也先标为需人工审核，不能隐藏在 Capital 字段异常之下
- 只读回执为 `ELIGIBLE_FOR_MANUAL_PILOT_PREVIEW` 或 `REVIEW_REQUIRED`，后者列出确切表名/差异类型
- **没有 --apply 入口**、没有任何 Parquet/调度/游标/pending 的修改途径；回执中的 eligible 也不代表已经批准数据修复
- 后续仅在通过九表门槛后设计单只股票显式授权的不可变版本写入与审计，需另行审查异常值的业务含义、退出回滚及批量逐股验收

建议先在 Preview worktree 测试 `test_qmt_capital_nine_table_repair_preview.py`，然后只在 canonical checkout、计划任务未运行且处于 16:30 更新窗口之外，选一只 QMT Capital pending 股票验证，比如 `002237.SZ`。测试通过之前不要开启批量写入。
