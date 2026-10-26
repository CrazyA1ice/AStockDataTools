# 2025年五分钟V3索引：45组快报暴露异常墙钟时间，新增循环空档诊断

更新：2026-10-26。仅记录用户真实上传的**聚合JSON摘要**，不公开付费OHLCV行。

## 前置核验

用户已在35/522组上运行独立全表只读审计 `pq-5min-2025-v3-readonly-full-audit-01.json`：已处理范围唯一规则五分钟键4,302,144、候选行4,302,144、重复0；耗时28.453秒；`index_complete=false`，源指纹为 `516ae482...`。

随后在同一V3主索引执行 `--resume --max-new-groups 10 --max-index-mib 192 --journal-mode wal --write-order source --report-detail progress`，用户上传 `pq-5min-2025-v3-quick-progress-45.json`：

| 字段 | 实测 |
|---|---:|
| V3 RowGroup | 35→45 / 522，仍只占8.62% |
| 本轮新增源行 | 1,232,892 |
| 累计源行/候选行 | 5,535,738 / 5,534,876 |
| 额外排除非候选证券 | 累计862行 |
| 时标无效/年度越界/证券无法识别 | 均0 |
| 本轮总墙钟耗时 | **1,318.813秒** |
| Parquet读取及键聚合 | 33.077秒 |
| SQLite RowGroup事务 | 140.517秒 |
| 全表结尾摘要（progress） | 0.047秒 |
| 原报告未归因耗时 | **1,145.063秒（86.83%）** |
| 最慢SQLite RowGroup提交 | 0号文件、40号行组，79.235秒 |
| SQLite主库逻辑分配 | 69,525,504B ≈ 66.30MiB |
| SQLite主库+WAL落盘 | 139,141,176B ≈ 132.70MiB |
| 容量软预算/触发 | 192MiB / false |
| 停止原因 | `max_new_groups` |

**解释限制**：进度快报中 `unique_regular_session_keys=null`、`duplicate_regular_session_keys=null`、分区/定位关系也为null，这些键的真实统计需要另外执行full审计；不能以累计候选源行替代已去重的时间键数量。源指纹只覆盖文件集合/大小/mtime，不是文件内容哈希；未经认证不能自动合并。

旧的细分计时只覆盖读聚合、提交、容量guard和结尾摘要，未单独计算Parquet footer建立、扫描已完成checkpoint、输出日志及行组循环的其他墙钟时间。因此无法判定19分钟未归因时间是否来自Windows休眠/系统调度、磁盘被占用、日志终端阻塞或代码路径。**尤其不能归因这19分钟全部是SQLite性能退化**。第40号行组的79.235秒提交是另一件已观测到的局部慢点。

## 本轮小范围代码改动

`tools/index-parquet-5min-coverage.py` 在原 `stage_profile_this_run` 下细分并保留原字段：

- `phases_seconds.parquet_footer_metadata`：ParquetFile元数据建立和行组总数读取。
- `phases_seconds.checkpoint_lookup`：包括跳过既有组在内的SQLite断点查询。
- `phases_seconds.progress_output`：原终端进度打印耗时。
- `phases_seconds.row_group_loop_other`：整段行组循环墙钟时间减去已计时的内部阶段；只是剩余墙钟时间，可能包含调度/IO停顿，**绝不代表额外的SQLite耗时**。
- `slowest_row_group_wall_groups`：最多5个最大RowGroup整体墙钟跨度，连同原read和commit明细；用于下一轮查明是否存在长时间停顿/离群单组。
- `process_cpu_seconds_this_run`：同一次计时窗口内当前进程的CPU耗时，与墙钟耗时并列查看；受多线程计数影响，可能大于墙钟秒数，因此不能将两者差额直接解释为休眠时间，也不能仅凭它定位磁盘阻塞。
- `unattributed_seconds` 保留，现已扣除以上新增阶段；WAL checkpoint仍只计入 `budget_guard_and_checkpoint`，不可重复加总。

没有变更SQLite索引表、源键分组规则、去重位图、断点逻辑、WAL模式默认值、主键写入顺序或报表的完成认证，旧的V3文件可以继续使用。

## 下一次 Windows 安全复测（只增2组）

先确认本机主V3索引确实完成45组，并在没有其他索引写入者时执行合成测试。然后仅新增2组，继续保持192MiB软预算，避免盲目扩至全部522组：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 2 --max-index-mib 192 --journal-mode wal --write-order source --report-detail progress --read-only --report "reports\pq-5min-2025-v3-wall-gap-47.json"
```

预期新增最多2个完整RowGroup，主库累计最多47组，且仅在预算未触发时。检查 `row_group_loop_other`、`checkpoint_lookup`、`parquet_footer_metadata`、`progress_output`、`slowest_row_group_wall_groups` 与 `unattributed_seconds`。如果仍出现分钟级墙钟空档，结合Windows睡眠/电源策略、任务管理器磁盘利用率和杀毒实时扫描进行**独立验证**，不能由Python墙钟数据单独确定原因。

如产生报告名已存在，请换一个新的 `--report` 路径；绝不要删除原V3索引或手动清理活动WAL。所有写入仍只限本模块 `work` 和 `reports`，`D:\stock`源数据保持只读。

## 验收状态

新增3项离线单元测试：循环残差不重复计算WAL、重现1318.813秒计时缺口后阶段守恒、最慢行组墙钟排序上限和不泄露OHLCV字段。之前预计95项+3项=**预计98项**，在用户Windows环境运行之前不声称全通过。此轮尚未对第46—47组执行真实数据测试。
