# 2026-10-27：Parquet历史主数据源第一阶段验收完成 → 轻量只读覆盖盘点

## 1. 已收到的真实安全台账

用户已在Windows端运行`plan-parquet-primary-evidence-ledger.py`，上传`parquet-primary-sampled-evidence-2026-08-24-09-30.json`，其中：
- `sampled_stock_day_count=5`，`sampled_date_count=2`，`summary_by_status.candidate_parquet_primary_in_this_sample_only=5`。
- 2026-08-24：SH600000 0.025ppm、SZ000001 0.033ppm、SZ300750 7.157ppm（日线对分钟OHLC严格一致，1min→5min严格一致，量额仅在旧容差内），对应已有离线验收安全报告。
- 2026-09-30：SH600000 0.005ppm、SZ000001 0.049ppm（日线对分钟OHLC及量严格一致，额仅在旧容差内），对应真实三周期安全报告。
- 所有5个股票日`verified_full_history_coverage=false`、`eligible_for_unattended_import=false`。台账`data_import_performed=false`，`source_market_files_modified=false`，`eligible_for_automatic_source_merge=false`。**不能把通过5个证券日误称为认证购买Parquet全历史。**
- 先前8组2026年沪市主板/科创板/深市主板/创业板股票日共384/384根五分钟线，按真实09:30开盘特殊分钟规则由1min六字段严格重建；日线抽检仅5组证券日，后续需按年份和北交所抽查。用户已经选择购买Parquet为历史数据主源首选。

## 2. 当前下一步的方向与为什么不继续重跑数据

过去核验一日3股票的1min和5min，读取Parquet源行往往需要700～900万行，重复成本很高，且不能据此知道2011～2026-09全部年代的源覆盖。现在优先**元数据级文件覆盖盘点**，不生成全量分钟索引、不重新聚合已验日期、不复制购买源。

新增 `tools/inventory-parquet-primary-footers.py`：
- 在`D:\stock\AllCycleAStockData\{day,1min,5min}`按周期各遍历一次Parquet文件，使用文件相对路径中的**唯一年份**归属到2011～2026。没有年份标记或同一相对路径含冲突年份的文件会记录为`year_ambiguous_or_absent_parquet_filenames_by_period`，**不能假装不存在**；跳过符号链接文件。
- **只读每个Parquet的metadata/footer，不调用`iter_batches`、`read_table`，不读ts/symbol行或OHLCVA列**。按每个年份/周期输出文件数、字节、来源行数、行组数量、缺失或非法`ts`统计的行组、文件名年份与实际footer时间边界冲突数、北京时间最早/最晚原始时间标签，以及各源文件的有限元数据摘要。
- `5min`**保留Parquet源原始起始时间标签**，不沿用H5对账阶段的+5分钟。日线源时间也原样保留时分，另提取北京时间日期；对未验证过的年代不擅自假设所有股票都是2026年相同时间规范。
- `source_file_stat_identity_sha256_not_content_digest`只对文件相对路径、长度与mtime纳秒序列生成SHA-256，以便**低成本发现来源文件元信息变动**，不读取昂贵的整个付费文件。这**不是文件内容哈希**，mtime不变化的恶意变更无法被识别，入库前若需要强完整性证明应为相应实际用到的源文件计算真实内容SHA256。
- 默认`--from-year 2011 --to-year 2026 --periods day 1min 5min --max-files 5000 --max-row-groups 100000`，最多40年，报表必须为本模块`reports`下的新JSON且拒绝覆盖、不写源数据。
- 字段`footer_envelope_complete_for_nonempty_row_groups`只表示非空行组都有可信ts统计、实际源时间与文件名所属年份没有冲突。**即使为true，也不意味着某个交易日或某只股票存在、有48根五分钟、241根一分钟，更不意味着无数据间隙或供应商正确**。
- `files=0`仅说明这个命名年份+周期没有找到符合约定的源文件；**不能证明交易所该年没有交易**。如果文件名不是可辨识的公历年份，该工具会报告跳过数量，并要求人工确认目录命名再定是否需要额外适配。
- 输出不含付费OHLCVA，不扫描证券时间键、不导入行情、不改写源、不自动补H5、不启动通达信盘后同步。

本轮新增`tests/test_inventory_parquet_primary_footers.py` **10项合成测试**，使用临时生成的无版权Arrow Parquet文件验证footer时间边界、完整/缺失ts统计、文件命名冲突、缺年份、时间归属不符、文件/rowgroup预算及报告不暴露原始OHLCVA。当前仅完成GitHub静态检查，**用户Windows测试及2011～2026真实付费Parquet盘点尚未实际运行**。

## 3. Windows第一次验收

在`D:\ChatGPT\AStockDataTools`仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\inventory-parquet-primary-footers.py "D:\stock" --from-year 2011 --to-year 2026 --periods day 1min 5min --max-files 5000 --max-row-groups 100000 --read-only --out "reports\parquet-primary-footer-inventory-2011-2026.json"
```

如之前全套240项经PR#56修复后均通过，则本轮新增10项预计**250项**；但需要本机真实运行结果证明。盘点输出为`H5ParquetReconciler/reports/parquet-primary-footer-inventory-2011-2026.json`，可直接上传分析。该报告不包含行情OHLCVA或本机源根绝对路径。

报告出来后，优先分析：
1. 日线、1min和5min各自的**实际最早/最新footer日期范围**，找出只有日线或只有部分分钟的年份；
2. 文件名中年份不明确的文件、缺统计/时间错年的RowGroup；
3. 哪些年份值得做小规模**key-only逐证券日精准索引**；不要对每个年份一开始就建大型SQLite索引；
4. 保持Parquet主查询API的只读和来源指纹设计，以额外独立存储层接入通达信完整盘后交易日；H5只作为实测缺口备选。

**本轮没有认证任何尚未扫描的历史年份，也没有开始正式主库同步。**
