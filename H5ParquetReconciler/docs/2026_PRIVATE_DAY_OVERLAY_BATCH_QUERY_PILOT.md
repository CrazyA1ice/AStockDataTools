# 2026-10-29：经验证日线多股票批量查询（只读试点）

## 前置实测：不是预期，是Windows已核验

- 用户本地三组合成回归：H5暂存10/10、不可变版本12/12、显式单股票只读11/11，总计33/33，三组结尾均为`OK`。
- 真实`SH600000`、2026-09-30～10-13：购买Parquet **1根**、已准备四日私有版本 **4根**，最终5根。
- 批量多日现场复核v3已从四次重复扫描变为**一次有界扫描**，输出`live_absence_recheck_scan_count=1`，全部H5候选22,191根、Parquet仍无这些日期。v2总耗时249.920308秒、现场247.758501秒；v3总耗时55.653345秒、现场54.447011秒。一次实测约降77.7%，不代表持久性能基准。
- 原版本依旧为已prepare但**未activate**：`46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03`。原购买Parquet及H5不修改、生产路由不修改。

## 为什么还需要批量查询？

单股票查询即使降至55.65秒，连续读取多只股票，每只独立跑一次真实市场来源审计，成本仍不适合数据分析/后续H5镜像。因此此轮**新增独立批量日线只读入口**而不是取消源审计、接受未经验证的所谓“快缓存”。

`tools/query-parquet-primary-day-overlay-batch-readonly.py`：

1. 显式传入1～10个规范沪深北A股股票代码、统一同一年内不超过31天的日期窗口、完整**已准备**私有版本SHA。
2. 每**一批**只核对一次完整不可变版本所有stage的SHA及证券唯一键；涉及私有日期时只调用一次已验收的多日H5/Parquet实时缺口复核。对每一个目标日分别审计原H5行数和购买Parquet全日无键，源文件状态复核前后不变。
3. 对购买Parquet，逐股票复用已核验的有界只读`query_bars`；购买数据仍优先且绝不被H5覆盖。每股票限制购买RowGroup扫描和返回行数，同时对整批次购买源扫描行数和结果总量进行预算限制。
4. 只有窗口覆盖的私有日线stage每个文件读**一次**，抽取多个指定股票；重复证券、重复股日、损坏stage、购买Parquet新增日期数据均拒绝整个批次，**不返回部分安全报告**。
5. 交易数据仍仅返回本地Python调用者内存`bars_by_symbol`，命令行**从不打印单根商业OHLCVA**，只能新建模块`reports/`下仅含按股票数量、完整来源校验状态、耗时的安全JSON。
6. 不读、不写私有活动指针，不改变既有单股票查询及其兼容性，不创建Hikyuu镜像、不改原始商业行情。
7. 成交量×100、金额×1000及价格÷1000的H5日线映射仍是候选解释，不认证为权威量纲。分钟线数据不在本轮范围内。

## Windows验收（目前**新批量工具8项测试尚未运行**）

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_query_parquet_primary_day_overlay_batch_readonly.py" -v
```

新增批量测试预期8项，使用临时构造H5+Parquet，检验两股共一次现场审计/一次私有stage解码、预算、篡改拒绝、新到货购买数据拒绝、只查基线、缺版本。**新8项未经验收前，不声称已可用于正式生产。**

全部通过后，用 SH600000 + SZ000001 两只股票做首个有界真实试点。两只股票的实际返回条数不能臆测；只核验两股一起消费同一个prepared版本，审计次数=1。对比此前单股票v3不能直接做苹果对苹果的耗时加速承诺：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-primary-day-overlay-batch-readonly.py "D:\stock" --symbols SH600000 SZ000001 --from-date 2026-09-30 --to-date 2026-10-13 --version-sha256 "46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03" --max-candidate-rows-per-symbol 300000 --max-total-candidate-rows 3000000 --max-result-bars-per-symbol 50 --max-total-result-bars 100 --max-overlay-source-rows 30000 --out "reports\private-day-query-batch-SH600000-SZ000001-20260930-20261013-v1.json" --read-only
```

把**新8项测试完整终端末尾**和刚生成的**安全JSON**发回即可；不用上传模块`work/`中的任何stage Parquet或原购买K线。

## 下阶段主线（不变）

真实批量只读试点 → 独立可控的私有统一Parquet版本消费协议 → 创建**Hikyuu可用的原生H5镜像**（独立`work/h5_mirror/`，真实Hikyuu验证后才考虑消费） → 通达信真实盘后来源接入统一Parquet再镜像同步。**10月14日以后现有源无记录的缺口不能凭推断填补**，旧分钟线差异机理继续暂停。
