# V3 五分钟索引：分批快速报告后的独立只读全量键审计

更新：2026-10-26。适用于 `H5ParquetReconciler` 的 2025 年五分钟 V3 SQLite 索引。

## 要解决的问题

`--report-detail progress` 减少每批百万级 `daily_coverage` 和 `row_group_locator` 扫描，因此唯一键、重复键、分区和行组定位统计必须输出 `null`。原来的 `index-parquet-5min-coverage.py --resume` 想获取完整数字往往需要同时继续处理新的行组，无法仅针对**当前已完成的 checkpoint**再做一次完整审计。

新增 `tools/audit-parquet-5min-coverage.py`，对当前索引进行单独的、只读的 full 审计。只读取原 Parquet 文件路径、大小、mtime 和 RowGroup footer 元数据；绝不读取 Parquet 的 `ts/symbol` 批次，更不读取 OHLCV 数据。SQLite 以 `mode=ro` 打开，建立一致读取快照，复用现有 index_summary 的两个完整索引表求和及候选键守恒校验。

## Windows 本机执行

先检查当前分支及完整测试：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

如果主 V3 索引依然是35组，可先按上一轮的轻量增量方式最多续建10组（不要对另两份排序 A/B 的第40组克隆执行恢复）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 10 --max-index-mib 192 --journal-mode wal --write-order source --report-detail progress --read-only --report "reports\pq-5min-2025-v3-quick-progress-45.json"
```

不论主索引实际停在35、45还是其他组数，只要源文件指纹未变，就可以单独做一次**不推进 checkpoint**的完整统计：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --read-only --report "reports\pq-5min-2025-v3-readonly-full-audit-01.json"
```

如果索引没有放在默认路径，可明确指定 `--index "work\indexes\自定义文件名.sqlite"`。相对路径统一解释为模块目录内；JSON 只允许写在模块内，已存在报告拒绝覆盖。每次重审请使用新的报告文件名。应在索引续建过程暂停、SQLite 无其他写入者时运行，避免长时间 full 扫描与 WAL checkpoint 相互影响。

## 输出与约束

- `audit_mode=existing_index_read_only_full`、`full_key_audit_performed=true`：重新计算已提交行组的唯一键数、重复键数、证券/日期分区和定位项，不读取新源 RowGroup，也不推进 `groups_done`。
- `new_row_groups_this_run=0`、`no_parquet_data_rows_read_this_run=true`、`sqlite_index_modified=false`：报告的语义是读取既有索引。SQLite 在 WAL 模式下可能仍需要其正常的共享内存侧文件来完成只读连接。
- 核查 SQLite V3 版本、当前 Parquet 文件清单大小/mtime 指纹、Footer 行组数量、已提交 `groups_done` 的行组编号范围、候选源行数与明细表求和是否一致；不符合就拒绝输出有效审计报告。
- `index_complete=false` 仍表示年度522组未处理完成。即使 partial full 审计发现当前已索引部分重复键为0，也**不意味着全年无重复、无需冲突隔离或可以买卖/仿真直接使用**。
- `saved_meta_completed` 原样反映历史标记；新审计不写回 SQLite `meta`，不会把未完成库变成完成库，`usable_for_automatic_union_from_this_audit=false` 永远为 false。
- 源文件大小/mtime 指纹不是内容哈希，原生索引设计限制仍在；索引内部一致性检查不认证历史证券类型、五分钟时标、复权、量额单位或两供应商价格真值。
- 原始 `D:\stock` 保持只读；既有 V1/V2/V3 文件、A/B 克隆、原有报告与其他工程一律不覆盖。本轮没有任何并集写入。

## 合成验收

新增7项离线测试，覆盖快速报告后只读重审、源指纹改变、越界 RowGroup、候选键守恒损坏、完成标记与 checkpoint 冲突、禁止只读工具提升认证，以及没有 checkpoint/无效 footer。当前原路线图预计已有88项，本轮**预计95项**，须在用户 Windows Python3.11 环境实际运行，才能确认准确通过数量。没有用户本地 2025 年完整索引，不宣称已完成真实全年度实测。

建议每完成若干小批次 progress 续建就暂停，执行一次独立 full 重审；最后522组完成仍由原构建器强制做 full 审计、进行索引前后业务计数对照后再讨论 Phase 2。
