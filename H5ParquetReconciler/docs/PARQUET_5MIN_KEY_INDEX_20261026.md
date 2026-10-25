# 全年Parquet五分钟唯一键索引（2026-10-26）

本阶段承接2025-09-30真实五分钟并集预检报告。原始H5有192根、Parquet有240根，交集192根，H5独有0，Parquet独有48（全部为BJ920680），重复键在这5只证券的当日选取样本中未发现。重叠192条中，184条存在至少一个字段超出暂定容差的冲突，8条容差内不同，数值完全相同0。来源时间、量额单位、证券主数据和裁决口径尚未认证，禁止自动覆盖和自动并集。单日样本不能证明年度文件全部没有重复键。

## 本轮工具为什么需要

原2025年Parquet五分钟年度文件有522个row groups、64,081,920行。源文件的行组时间和symbol min/max对2025-09-30五只证券无一可跳过：每次进行单日查缺都要再次遍历所有522组，重复读取数千万条源行。

新增 `tools/index-parquet-5min-coverage.py`，**只扫描时间戳ts和证券代码symbol**，不读取、存储或上传任何OHLCV原始量价。一次性在本模块的`work/indexes/`目录生成可复用SQLite覆盖索引：

- 以（标准化证券代码、北京时间自然日）为聚合键，使用一个**48位bitmask**记录五分钟各时段是否存在K线，同时累加源行数。
- 支持按5min起点候选时标对应09:30—11:25及13:00—14:55两个交易段，遇见其他时标、非法时间戳、源年度范围外记录时单独统计，不会错误塞进48个正常时段。
- 以`source_rows - bit_count(slot_mask)`精确统计**正常48时段内**相同证券/日期/5min时段的重复记录，即使跨Arrow批、Parquet RowGroup乃至同年度不同文件。异常时标另列，不冒称全部已认证。
- 另外建立（证券、日期、来源文件编号、RowGroup编号）定位表；今后对单日少数证券的预检通过`--coverage-index`只扫描已确认包含对应键的行组，避免再读全年522个行组。
- SQLite以**整个RowGroup为事务边界**保存索引，Ctrl+C中断或失败后使用`--resume`续建已完成的RowGroup；缓存了年度源文件路径、字节长度和纳秒mtime的指纹，发现来源变更则拒绝复用。指纹不是整个原文件的密码学哈希，不可当作内容完整性认证。
- 默认不覆盖索引或汇总报告；另有`--max-new-groups`支持先扫描少量RowGroup检查读写兼容性，部分索引的`index_complete=false`，**禁止用作并集预检快速定位**。
- 输出目录：`H5ParquetReconciler/work/indexes`持久SQLite（被.gitignore忽略），`H5ParquetReconciler/reports`本地摘要JSON（被.gitignore忽略）。不创建格式转换后的H5/Parquet数据库，不写入D:\stock。

## Windows：先测试、少量建索引、断点续跑、再查询

在`D:\ChatGPT\AStockDataTools`仓库根目录：

```powershell
git status -sb
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

首次用2025年度的2个RowGroup检查环境和磁盘是否正常（**这里不会扫完全年的64,081,920行**）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --max-new-groups 2 --read-only --report "reports\pq-5min-2025-index-smoke.json"
```

此时模块内会保存**部分索引** `work/indexes/pq-5min-2025-a-share-candidate.sqlite`；报告应标明`index_complete=false`、`row_groups_complete=2`。由于小批次不代表全年度，不能仅凭这2组估计全市场重复键总数。

检查初次正常后，对同一个本地索引继续（请留足磁盘空间，这是**一次性的全年键索引构建**，耗时取决于本地SSD与CPU；它仍需扫描所有年度Parquet一次）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --read-only --report "reports\pq-5min-2025-index-full.json"
```

报告`index_complete=true`、`row_groups_complete=522`时才能试用加速预检。建议避免覆盖此前结果，新建报告文件：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\plan-5min-readonly-union.py "D:\stock" --date 2025-09-30 --symbols SH600000 SZ000636 SH603181 SZ300747 BJ920680 --coverage-index "work\indexes\pq-5min-2025-a-share-candidate.sqlite" --index-universe a-share-candidate --read-only --out "reports\5min-union-preflight-2025-09-30-indexed.json"
```

预检报告应显示`parquet_coverage_index.used=true`，以及`parquet_scan.row_groups_skipped_by_index`大于零。**比较新旧同日预检的H5独有、Parquet独有、交集与冲突数量必须完全一致**；若不一致，先视为索引或源文件变动问题，不要启用索引。

## 明确限制与防误用

1. 只有2025年5min这一类**固定48个合法起点时段**获得了位图级精确重复检测。非正规日期、非五分钟时刻和其他异常被汇总为异常，不纳入位图，摘要不能当作全源全部键完全认证。
2. 为安全起见，索引中存在非法时标或无法识别证券代码时，查询程序拒绝仅依赖它跳过RowGroup，避免把异常记录错认成不存在。存在正常时段重复键时会在并集预检中标记阻断；不得直接合并。
3. 股票筛选仍是代码前缀候选集；历史证券主数据、真实上市状态、量价归一化和复权未认证。索引不能判断任何一个价格或成交量“正确”。
4. 该索引只保存覆盖时间键、出现次数和相关行组位置，**不是复制一份新的5min原始行情**；不能用它直接输出新的H5/Parquet，未来格式互转仍需要独立的来源验证与安全写入模块outputs。
5. 索引/SQLite可能占用一定磁盘空间，已有完整源文件不会因此减少体积。若磁盘不足，可中断并保留checkpoint，禁止在源数据树下生成缓存。
6. 本轮增加9项合成测试。原52项+9项共**61项**，这是提交的测试数量，不是已经在用户本机通过的测试数量；须以上述本机命令结果为准。

开发目标是可靠地把全年度键覆盖与行组定位工作**只做一次**，然后继续研究真正全量H5+Parquet双格式并集，而不是每天重复扫描年度数据。
