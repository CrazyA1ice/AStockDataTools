# QMT 为主的财务数据入库：历史版本保留，不再逐股审核正常修订

## 决策及原因
用户于2026-11-23明确要求：不再对日常QMT财务数据逐条做东方财富/公告交叉审核，**QMT现有缓存作为当前优先版本，直接入库**。旧严格入库器将全部历史所选版本做Counter并集，凡旧记录在现时QMT中缺失或原值被修订就抛出 `SOURCE_HISTORY_CONFLICT`，把普通源版本变化也挡在待审队列。最近实机记录116只待审、其中115只来源历史冲突，Capital首阻断45只；两只样本的13条新增股本变动日期键和2条自由流通股本字段修改已经复现，至少部分日期可以找到正常公司公告，**不能由旧新版差异推断数据损坏**。

## 入库方案（独立财务Parquet）
新增可选 `--qmt-primary-versioned`，只改变九张QMT财务报表的**新版本接受规则**，不修改主股票八周期、H5、其它补充模块、20:05正式行情任务，也不需要东方财富审核。

- 仍从QMT读取其现有本地缓存（`--mode cache`不触发下载），检查股票身份、九表集合、数据结构、记录上限、QMT读取及解码状态；真正失败继续留在pending。
- 旧Parquet内容寻址文件保持不可变。若QMT当前数据与某表最新已选版本不一致，就按**本次采集日期**生成一个新独立快照并切换这一天的active pin；之前所有日期及同日旧文件继续保留。相同版本重跑不会重复建档。
- QMT某张表暂时返回空记录时**不删除旧表**，记为`SOURCE_EMPTY_OLD_RETAINED`或`NO_SOURCE_RECORDS`。空表不被声称完整。
- 历史修订只在覆盖审计日志`financial-coverage.jsonl`留下`historical_records_not_in_current`计数，**不再作为需逐股人工复核的停写条件**。成功写入后按现有状态机消除该股票的过期pending；原始pending在第一次执行前需备份以便追溯。
- 无法验证的快照、异常结构、失联、UTF-8解码失败、账户权限/数据为空仍按已有保护处理；保留批次上限、独占writer及进度检查点。大规模系统性冲突保护不解除。
- 新模式与旧`--capital-mquarter-nonbusiness`特例互斥；默认不开启，必须操作者明确使用新参数。独立worktree运行时必须指定`--workspace`指向**正式主仓库**`ParquetLiveSync/work/qmt_extra`，避免生成第二份进度账本。

## 两步推进，不用人工逐行审
1. 一次性运行新的模拟测试，在本机备份正式财务进度JSON；用`--mode cache --retry-pending --qmt-primary-versioned --apply`处理现有财务pending。会调用QMT现有缓存，但不下载；读/写均限于独立`qmt_extra/financial`。成功后比对processed、新快照及pending状态。单一失败不代表所有股票入库失败；不可解码/无缓存的仍保持pending。
2. 日常财经任务的包装器`run-qmt-financial-daily.ps1`支持一次性参数`-QMTPrimaryVersioned`以选择新模式；默认旧策略保持不变，**本PR不改动已有计划任务或触发器**。若原日常任务按旧参数启动，仍走严格策略；要在自动化中长期采用，需要一次性更新其启动参数并验收。日常`--mode daily`按原有实现仍会下载受限公告日窗口，不是纯缓存模式。

## 未验证的边界
截至本PR的这一变更只完成GitHub源码和合成测试文件编写，**用户Windows测试和正式pending入库尚未执行**；不能宣称115只冲突已解决。市场最新来源不等于证券交易所认证的历史数值。原QMT市场文件/数据库分区不会在此阶段发生隐式修改。

## 2026-11-23 688259.SH 单表损坏、七张核心表独立恢复

用户 QMT 重新下载单股八表后，九表联合读取仍连续2次`UnicodeDecodeError(utf-8, unexpected end of data, start=198)`。再通过已有`qmt_extra_financial_cache_worker.py --probe-readonly --symbols 688259.SH`逐表只读确认：

| 表 | QMT缓存状态 | 行 |
|---|---|---:|
| Balance | ROWS_IN_LOCAL_CACHE | 25 |
| Income | ROWS_IN_LOCAL_CACHE | 30 |
| CashFlow | ROWS_IN_LOCAL_CACHE | 27 |
| Capital | ROWS_IN_LOCAL_CACHE | 32 |
| Top10FlowHolder | ROWS_IN_LOCAL_CACHE | 200 |
| Top10Holder | **UTF8_DECODE_ERROR** | 不可读取 |
| HolderNum | ROWS_IN_LOCAL_CACHE | 21 |
| PershareIndex | ROWS_IN_LOCAL_CACHE | 33 |
| PerShare | EMPTY_OR_NOT_CACHED（可选） | 0 |

所以 **7张核心表共368条QMT当前缓存记录可读，Top10Holder确实独立损坏**。新工具`qmt_extra_financial_partial_recovery.py`严格绑定`688259.SH`、跳过唯一`Top10Holder`，按QMT一表一次`get_financial_data`读取**七张已验证的核心表**；已判定为空的可选`PerShare`也不读取；无任何QMT下载调用；强制本机QMT主库`financial-cache-progress.json`SHA一致、唯一pending `688259.SH/CACHE_DECODE_ERROR`、北京时间19:20~20:40避让、主仓库而非review worktree的独占写入锁。同一锁内复核账本SHA前后，复用已有`_commit_symbol(...,qmt_primary_versioned=True)`为**健康表**入库，以不可变Parquet快照保留全部旧版。坏表作为`[]`仅用于触发旧表`SOURCE_EMPTY_OLD_RETAINED`或`NO_SOURCE_RECORDS`，它**从未向QMT请求、也不会保存伪造的空历史记录**。原进度账本不写、故障标记仍是`CACHE_DECODE_ERROR`；因此不能报告全部九表完成。新的输出`QMT_FINANCE_PARTIAL_COMMIT`注明`pending_remaining=true`、`source_completeness_verified=false`，并打印每健康表行数，不打印原财务值。

新增5项完全模拟测试：离线preflight零QMT/零写；七核心表实际调用现有写入器后原Top10Holder文件字节保留且pending不清；另一个健康表解码错误会拒绝本次入库；账本SHA变化拒绝；异常身份状态拒绝。**截至提交，这些新增测试和真实数据恢复尚未在用户Windows执行。** 先执行测试，再正式仅处理该股健全表；确认7张可查询后直接转入回测，对Top10Holder单独列待修复，不继续全市场反复下载。
