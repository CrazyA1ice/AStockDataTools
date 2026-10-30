# 2026-10-30：跨年H5/Parquet日线实测——重新核验年度键后只读目标RowGroup

## 进入此阶段的真实证据

- 用户Windows第149轮12项虚构Parquet键列测试已全部通过（3.005秒），随后对真实2025年度`day/2025.parquet`执行了**只读ts/symbol两列**扫描，并上传`real-2025-annual-parquet-day-keyonly-20250930-v1.json`。
- 真实SAFE显示：年度Footer **1,333,385行，12组**；键列实际扫描1,333,385行，88个批次；2025-09-30两只股票目标键**恰好2条**；真实目标键只位于**1个RowGroup**，该组Footer显示**123,139行**，严格低于既有**150,000条OHLCVA行**及**最多2组**预算。
- 之前因2025年年度12个RowGroup全部具有跨日的`ts`时间范围，单看Footer均显示可能包含2025-09-30，按时间剪枝的只读跨年工具因此拒绝。键列实际定位**不等于**已读取2025年OHLCVA，也没有跨年4条数值证据。供应商单位和全市场格式转换仍未认证。

## 本轮调整已有跨年工具，不改变源文件

`tools/probe-real-h5-parquet-crossyear-day-readonly.py`新增显式参数`--prior-annual-key-only-safe`；原无此参数的严格Footer-only路径及历史18项合成测试保持原样。本轮**不新增第二套交叉比较算法**，仍沿用2025年度+2026年8月同两股4个日线、`T.compare`及两源的原始量价额诊断函数。

新增的有前置SAFE保护的读取分支如下：

1. 先确认此前3份真实证据SAFE：发现日2026-09-30两股原始Parquet/H5整数倍率2/2，同日Hikyuu真实C++逆向HMAC2/2，2026-09-28/29两股留出4/4；再确认新增2025年度键列SAFE的`format`、日期、扫描预算、**实际扫描1,333,385键、命中2个目标键、候选组数1、目标组123,139行**及所有供应商认证标志均符合要求；前序报告不存储或提供RowGroup ID，**不得拿它作为位置授权**。
2. 真实主跨年运行**重新**只解码2025全年最多1,600,000行的`ts`和`symbol`键，最多16个RowGroup，分批最多16,384行。重新确认年Footer、批次数、扫描行数、固定2025-09-30 SH600000/SZ000001分别恰好出现一次、所处组数与目标组累计行数均和新SAFE完全一致。若同一组或跨组有重复目标证券/日键、源改动、前序SAFE与现值冲突，一律在读取OHLCVA前拒绝。**不信任前次运行的RowGroup序号，也不输出该序号。**
3. 仅在此时真正打开**重新定位到的1个年度行组**的八列`ts/symbol/open/high/low/close/amount/volume`，最多读取150,000行/2组，并在批内筛选2条目标股票日线，检查唯一性、有限float64和准确日期。严格校验全部已选组的解码行数是否等于Footer列示行数。年度键列的1,333,385行**绝不计作**OHLCVA读取，SAFE两者分开记录；代码禁止年度全组OHLCVA加载。
4. 2026-08-24仍使用已通过本机合成验收的月度Parquet严格Reader（≤150,000行/32组），并从原始`sh_day.h5/sz_day.h5`**只读**读取两日期固定的4条原始H5日线整数。只有全部4个股票日可配对才按原先的`PAIR.evaluate`分别统计价(H5 raw÷1000, 0.005容差)、量(H5 raw×100)、额(H5 raw×1000)候选倍率与双零/单零分类，缺数或不匹配不跳过、不替换股票/日期、不把零当作倍率证据。
5. 新SAFE不仅存4股票日分日期固定候选统计，还额外存`annual_2025_key_only_rows_rechecked`、`annual_2025_key_only_batches_rechecked`、`annual_2025_ohlcva_rows_scanned`、`source_parquet_total_rows_scanned`（**只计算年度选中组的OHLCVA加2026月度全部扫描行，不含键列**）、2/3月份源文件只读证据及前序2025键列SAFE的SHA256；不会输出真实OHLCVA、H5整数、股票代码、原始时间戳、用户文件路径、密钥或HMAC值。报告文件写入项目模块`reports/`全新位置，不允许覆盖。
6. 源Parquet/Footer及H5文件stat前后校验不变（**不是整份大文件SHA256**），不启动原生Hikyuu C++、不写Parquet/H5/正式SQLite。即使新4/4结果全部匹配，也只能表明加上2026-09的6个样本，在**2025-09、2026-08、2026-09三个不同月份共10个股票日**支持一组原始数值倍率，不能验证供应商“股/手/元/万元”等具体物理单位、全市场或分钟线。

## Windows PowerShell操作（每块一条完整单行）

更新仓库：

```powershell
git pull --ff-only origin main
```

先跑本轮新增**9项纯合成Parquet/H5回归**（Windows结果仍未知）：

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_probe_real_h5_parquet_crossyear_keylocated_readonly.py" -v
```

先核对真实年度键列SAFE仍存在：

```powershell
Test-Path "H5ParquetReconciler\\reports\\real-2025-annual-parquet-day-keyonly-20250930-v1.json"
```

确认新跨年只读报告名未被占用：

```powershell
Test-Path "H5ParquetReconciler\\reports\\real-h5-parquet-crossyear-day-factors-keylocated-20250930-20260824-v2.json"
```

只有9项全部OK、第一项True、第二项False时执行，仍使用原来的两份历史源Parquet和原H5目录：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\probe-real-h5-parquet-crossyear-day-readonly.py --parquet-root "D:\\stock\\AllCycleAStockData" --h5-root "D:\\stock\\HikyuuData" --prior-raw-safe "H5ParquetReconciler\\reports\\real-parquet-h5-raw-day-unit-factor-candidates-20260930-v1.json" --prior-native-safe "H5ParquetReconciler\\reports\\real-hikyuu-native-20260930-hmac-v3.json" --prior-heldout-safe "H5ParquetReconciler\\reports\\real-h5-parquet-heldout-day-factors-20260928-29-v1.json" --prior-annual-key-only-safe "H5ParquetReconciler\\reports\\real-2025-annual-parquet-day-keyonly-20250930-v1.json" --out "H5ParquetReconciler\\reports\\real-h5-parquet-crossyear-day-factors-keylocated-20250930-20260824-v2.json" --read-only-crossyear-days
```

若仍被安全拒绝，保留当前本地旧源与全部前序SAFE，不删除、不覆盖、不绕过两个预算；记录完整终端最后错误并先分析失败时处于2025 H5历史日线、2026月度源或前序证明哪一步。不要上传任何付费Parquet、原始H5、实际价量额或源文件路径；只上传本轮生成的SAFE与9项测试日志。

## 保护后的下一步

- 只有**新的**`keylocated-v2`真实SAFE明确给出2025-09-30与2026-08-24两个日期各自的价/量/额候选匹配数，才可以进行真正的跨年实证结论。
- 成交额差异（哪怕单日1/2）应该分别保留并溯源，而不能因2026-09的6/6而消除异常；并须独立处理5min已知差异、来源时间标签和量额物理单位。
