# 五分钟历史核对性能问题与单日有界试跑（2026-10-25）

## 实测情况

用户在本地PowerShell执行 `--years 2025 2026 --periods 5min --universe a-share-candidate`，卡在 `AUDIT 5min/2025` 约五小时。进程31072从2026-10-25 17:59左右启动，CPU累计1621秒、常驻内存约0.23GB；原临时SQLite文件路径检查未找到文件。用户随后手动按Ctrl+C中断。**不能据此认定H5或Parquet损坏**，也不能因为没有找到SQLite文件就证明它未写入：SQLite放在Python`TemporaryDirectory`中，正常退出或中断的清理过程会移除其文件。

旧核对程序在每个年份首先遍历每只股票的全年H5 5min历史，把数千万条记录逐条序列化为Python tuple写入SQLite带主键索引，再按Arrow batch扫描整个Parquet年度文件；其日志仅在整个年度完成后输出结果，容易让用户误认为死循环。CPU与内存占用不足以区分磁盘I/O等待与HDF5随机读取；真正瓶颈要在新日志的两个阶段逐一定位。

## 本次代码调整的作用和范围

1. 增加同一年内的 `--from-date`、`--to-date`，日期范围两端包含；先按日，再按周或月试跑。原有日线全年功能保持不变。
2. H5用二分查找 `datetime`，仅把日期范围内的原始K线复制到临时SQLite；按市场和每400证券输出进度，不再先写入整年全证券分钟数据。
3. Parquet使用RowGroup统计列 `ts` 的min/max判断是否与请求窗口有交集，确定不重合的组直接跳过；缺失统计的组保守读取，防止漏数。分批解码时先筛选时间戳，没有请求窗口的batch不转码六个OHLCV字段。
4. 每隔约20秒或者处理到文件最后一组输出Parquet行组读取/跳过、读取行数、匹配窗口行数。若全部行组都覆盖全年，按时间跳过效果可能很差，这是需要下一版构建持久时间分区索引或利用DuckDB数据流的证据。
5. 计算和报告按窗口而非整年度；窗口内H5为0时仍从Parquet取实际键做精确核验，不再仅根据年度footer估算差集。
6. JSON记录 `requested_from_date`/`requested_to_date`、每分区窗口及Parquet读取/跳过行组数；`--resume` 不允许把单日、单月或全年结果混用。
7. 5min与1min整年处理改为**必须显式** `--allow-full-year-minute` 才能运行。加这个开关仍可能耗费数小时，不代表性能已经解决；当前推荐单日短窗。

**限制**：新增的单日扫描**不等于**已经具备按日中断续跑整个年份。若把日期范围扩大到整个月，仍要一次完成该窗口才有一次checkpoint。要实现按日自动分区、跨日期累计，需后续改变报告结构并增加唯一键去重、按日可恢复索引。这个阶段不能将单日结果误写成整年的覆盖率，也不可自动合并两个来源。

## 下一步本机复现步骤

均在 `D:\ChatGPT\AStockDataTools` 仓库根执行；所有JSON/Markdown/SQLite只在 `H5ParquetReconciler` 模块目录内：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_reconcile_local_a_share_h5_parquet.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2025 --periods 5min --from-date 2025-09-30 --to-date 2025-09-30 --universe a-share-candidate --read-only --out "reports\h5-parquet-5min-2025-09-30-pilot.json"
```

仅在单日成功、行组过滤比例合理且报告无误时，才尝试不同文件名的2025年9月整月报告：
```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2025 --periods 5min --from-date 2025-09-01 --to-date 2025-09-30 --universe a-share-candidate --read-only --out "reports\h5-parquet-5min-2025-09-pilot.json"
```

若单日即明显慢，应优先发终端H5 symbols进度、Parquet读取/跳过行组数、剩余磁盘容量；不要重复发起全年任务。不修改源数据库，不上传购买行情，不新建模块外产物。

## 验收门槛

本轮新增4项合成测试，包括有界5min匹配、按行组min/max跳过、窗口H5无记录时Parquet真实独有键、窗口resume参数一致性、禁止未确认的全年分钟模式等。旧回归套件原有15项，新增后为19项。提交到GitHub不能视为本地测试通过；需以用户Windows终端输出为准。若代码/结果异常，先修复再跑真实数据。

其他安全边界仍在：09:30、5min开始/结束标记、H5量额单位、北交所历史证券代码以及跨Parquet批次重复键未获独立认证。真正构建并集前必须解决。
