# P65 · QMT Capital.m_quarter 单股白名单语义比较（默认关闭）

日期：2026-11-18，承接 P64 五市场九表联合只读验证：五只 `ELIGIBLE_FOR_MANUAL_PILOT_PREVIEW`，九表其余已保存历史与当前缓存一致；39 项 Windows 本机离线测试通过。五只的预检 SHA256 指纹已记录。原本 5,003 待审尚未变更。

## P65 修改了什么

只修改 `qmt_extra_financial_cache_import._plan_symbol`、`_commit_symbol` 的**可选**参数 `capital_approved_symbol=None`。正式 `run()`、日常 16:30 计划任务及命令行并未增加批准参数，因此**默认原有逐行严格比较和批量历史冲突熔断行为完全不变**。没有新增常驻白名单文件，也没有解除 pending、更新私有进度或触碰真实行情。

只有调用方显式传入**恰好等于本次 `code`** 的 `capital_approved_symbol`，且在 `Capital` 遇到原始记录历史冲突时，才调用 `qmt_capital_semantic_proof.prove_historical_union` 对**全部已选旧快照并集**进行复核：

- 旧版和最新缓存存在完全相同的 `m_timetag` 日期集合，每个日期唯一
- 除 `_index` 与 `m_quarter` 外，所有源字段完全相同，字段有无、真实股本值、日期及公告时间严格一致
- 历史旧版本之间亦没有非 `m_quarter` 差异
- 其他八张财务表仍调用原始严格历史并集比较，不能因为 Capital 的批准放松所有表
- 返回 `M_QUARTER_ONLY_CANDIDATE` 才可将当前 raw source 原样保存为新的内容寻址 Parquet；**旧版快照字节及过去日期的 pin 均不修改；同一 asof 如已有旧活动版本，新增版本可能更新该日期的 active pin，正式 apply 必须事先保留可回退的 pin 凭证**
- 若当前 raw 版本此前已存档，则标记 `UNCHANGED` 而非无限重复提交新版本，即便全部旧版 `m_quarter` 变化记录仍然保留

## 未完成及严格边界

- P65 提供一个可在临时模拟 Parquet 中测试的**核心比较能力**，不是完整运营恢复：`run()` 不会传入 `capital_approved_symbol`；P65 没有 `--apply` 操作、批准文件、回退记录、pending 事务性释放或自动持久白名单，因此不会修复当前 5,001 只股票
- 允许新公告/新的 `m_timetag` 日期时，现有严格 `prove_historical_union` 仍会拦截，后续需要单独引入已核验历史记录的 append-only 证明；不得把合法新记录和 m_quarter 异常合并为一个无条件放行规则
- 一旦新增可运行的 `--apply`，需在同一 writer 锁下重新读取九表、验证源 SHA 和旧快照、记录原始 pending 与旧 pin、生成原始 raw 不可变 Parquet、持久关联单股白名单、最后才解除单股 pending；设计可撤销及崩溃恢复，真实运行前另需用户明确授权
- 九表中 `PerShare` 的缓存与历史均为 0 行，仅表示一致，绝不宣称数据源完整

验收建议：`python -B -m unittest discover -s ParquetLiveSync/tests -p test_qmt_capital_scoped_comparison_rehearsal.py -v`；再跑 `test_qmt_extra_data.py`、`test_qmt_capital_semantic_proof.py`、`test_qmt_capital_nine_table_repair_preview.py`，确保原 importer 的严格默认路径不退化。所有合成测试使用临时目录，不访问真实 QMT 缓存。真实财务修复仍需下一阶段的显式批准和事务实现。
