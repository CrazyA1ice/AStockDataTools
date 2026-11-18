# P62：QMT Capital.m_quarter 分层扩大抽样，只读且可限时

日期：2026-11-18。P61 五市场真实缓存抽样（002237.SZ、300766.SZ、601519.SH、688367.SH、920288.BJ）全部返回 `M_QUARTER_ONLY_CANDIDATE`；21 项相关离线测试全通过。四市场样本各有 1 条旧记录的 `m_quarter` 变化，北交所样本 5 条全变。**仅证明这五只样本的其余业务字段与已保存完整历史版本一致，不代表 5,001 只都可释放。**

新增范围：
- `qmt_capital_conflict_census_readonly.py --sample-size 25 --max-sample-minutes 20`：按深市主板/创业板、沪市主板/科创板、北交所五层，各抽取最多五个不同代码分位点，不只对单一中位数抽样。无足够股票的层会把配额分配给其他待审 Capital 股票
- 至多 25 只，依照代码排序每批至多 5 只，读取 QMT **已有本地缓存**；无 `download_financial_data*`、无 Parquet 写入、无进度游标移动。真实缓存采样只允许在正式 checkout 上使用共享独占锁
- 与正式增量入库器共用 `_prior_rows`，验证**所有已选历史版本原始行的并集**；只有 `m_quarter` 可视作未定义辅助字段的候选差异。所有日期、数值字段、字段布局严格一致；新增/缺失、历史业务字段改变、源缓存解码失败仍分别报告
- 逐批输出 `QMT_CAPITAL_SAMPLE_BATCH`，最后提供 `class_counts`、`candidate_count`、`review_count`、`m_quarter_changed_rows_in_candidates`。超出审计预算后返回 `PAUSED_TIME_BUDGET`，未检查样本不作为 PASS，并以非零退出报告未完成
- 只读采样最多 25，只能形成下一步受控版本化修复的准入依据，**不得清空当前 5,003 条 pending、绕过大规模 Capital 历史冲突熔断，或直接改写 2011–2026 八周期行情**

推荐验收：离线执行 `python -m unittest discover -s ParquetLiveSync/tests -p test_qmt_capital_conflict_census_readonly.py -v` 和 `test_qmt_capital_semantic_proof.py`，确保原有样本测试和新增 25 只分组/超时保护通过；之后先用 Preview worktree 离线测试，再在正式 checkout 中经版本 pin、安全锁、任务 Ready 检查，在 16:30 定时器冲突窗口之外只读实测。

## 后续未实现

在满足大样本严格安全判据后，才考虑显式批准的逐股恢复程序：不能直接在官方 importer 全局忽略 `m_quarter`；必须锁住原状态、逐股验证其他八表不退化、保留原始不可变快照及新版本审计账本、支持回滚与复核，并把真正财务股本变动继续隔离。单日全部股票的财务筛选仍需从“200 只轮转”进一步升级为公告事件驱动。
