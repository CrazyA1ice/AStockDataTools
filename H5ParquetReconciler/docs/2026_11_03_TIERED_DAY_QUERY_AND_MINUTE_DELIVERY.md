# 2026-11-03：历史DAY真实验收后直接交付分层本地查询 + 1/5分钟精确覆盖

## 本轮用户Windows真实验证（不要重做）

此前已完成真实 **1990—2010历史RAW 3,682,327行** → 未认证购买字段候选3,673,987+原生整数无损隔离8,340；原2011—2026购买优先日线14,137,981行旧16年Parquet已验，未重建。新上传终端日志对`run-day-catalog-audit.ps1`四项测试全PASS，**21个私有历史年Parquet/年度SAFE的完整SHA及隔离原因对账通过**；SAFE：
`reports/pre2011-historical-reject-reasons-catalog-d90fb2c8a563.json`。

8,340条隔离原因真实合计：
- `historical_vwap_factor10000_not_supported` 5,899；
- `alternative_historical_vwap_factor_100000` 2,344；
- `native_volume_or_amount_zero` 65；
- `alternative_historical_vwap_factor_100` 25；
- `alternative_historical_vwap_factor_1000` 5；
- `alternative_historical_vwap_factor_10` 2。

**任何VWAP候选倍率都不是原供应商/交易所成交额单位认证。** 不能把8,340行机械换算并入标准日线；特别是1990仅24条全隔离、1991/1992大量另类候选。应先交付现有可以直接读取的数据层，而不是继续新增每一轮成本高昂的只读全源扫描。

## 新增：本地研究分层查询工具（源码已提交，新测试待Windows）

`tools/query-private-1990-2026-tiered-day-local.py` 的 `read_local_bars` **只在用户本地Python进程内存**给出已授权的真实许可OHLCVA；CLI仅输出脱敏计数JSON，**不会打印或上传股价、股票代码/请求日期**。查询按1..31天/最多31条记录：

| 物理数据层 | 年份/来源 | 查询口径 | 状态 |
| --- | --- | --- | --- |
| 已有2011—2026年Parquet | 14,115,707购买源 + 22,274 H5-only历史补缺 | 复用已有16年SHA/SQLite/真实OHLCVA本地读取器，购买与H5补差来源明确分开 | 购买值保留原样；H5新值单位仍候选，不是生产激活 |
| 1990—2010独立候选Parquet | 3,673,987 | 只有显式`allow_unverified_historical=True`，才按SHA限定的实际年度候选Parquet单证券/日期读取；来源标签恒为`h5_pre2011_numeric_hypothesis_not_vendor_certified` | **不能假装供应商单位、复权或历史证券身份已认证** |
| 1990—2010独立RAW隔离Parquet | 8,340 | 只有显式`allow_native_quarantine=True`才返回独立`native_quarantine_rows`原始无符号整数，不拼进`bars`，不推断价格/量额 | 保持原生字段与隔离原因，不算正式OHLCVA |
| 统一来源总账 | 17,820,308 | 37年各物理年已有SHA/version引用，不搬运/复制旧16年购买数据 | **仅是研究分层查询；生产active pointer仍false** |

新工具使用本机固定版本SAFE的SHA校验，单次读取所选历史年文件的SHA和Parquet schema，再按代码/日期进行Arrow筛选。现代部分复用已实机测试的原独立只读接口；历史/现代跨年窗口也可按日数上限读取，仍限用户内存。任何历史未显式许可、混合层总结果超过31条、年度分区SHA变动、历史源标识改变，均拒绝返回部分数据。

此阶段是**本地研究实验消费入口**，不是将未认证历史行情切换给AStockResearchLab/策略回测默认数据源。发布生产库前仍需供应商量纲/复权/证券身份审核；不能因为存在1990数据就称1990—2026全部可用于实盘回测。

## 唯一下一步Windows命令：新日线本地分层读 + 分钟累计

新入口 `run-tiered-day-and-minute-progress.ps1` 执行5项分层查询合成测试与5项分钟进度安全测试，随后对 SH600000 2010-12-28—2011-01-06 跨年做一次**仅写计数**本地私有读取；同时SHA遍历既有1/5min每日统一Parquet，**同日多个验收SAFE去重**，计算真实已写入的交易日数及两个周期总行数。已验日期不重新写盘，不重跑21年历史，原始采购文件/H5不读写。

在 `D:\ChatGPT\AStockDataTools` PowerShell 一整行执行：

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "切换失败" }; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; powershell.exe -NoProfile -ExecutionPolicy Bypass -File H5ParquetReconciler\run-tiered-day-and-minute-progress.ps1; if ($LASTEXITCODE -ne 0) { throw "37年分层研究日线/分钟Parquet SHA进度审计失败，源数据不变" }
```

**注意：新增5+5项合成测试、实际跨2010/2011 SHA私有值读取、精确分钟统计目前均尚待用户Windows首次验收，不应在跑完之前标为PASS**。报告只输出日线来源分类与分钟累计，不能将统计本身当作新增行情物化。

## 直接转入分钟实际写盘

紧接着双击 `H5ParquetReconciler/start-minute-converter.bat`，选择已有原源确实覆盖的日期范围（如先按2026年1月1日到10月13日；之后根据源覆盖再扩到2025年），让后台worker按日自动跳过之前8/9/10月已验Parquet，新增实际尚缺日期的1min、5min。关闭UI不停止任务，可恢复/暂停。用户源末端历史观测到2026-10-13，**不要把10-14以后没有行情源数据的日期算作已完成转换**。分钟数据真正完成后再对15/30/60、week、month原买文件做分区清单及缺口补充，Parquet正式版本/生产发布与H5镜像留在其后。
