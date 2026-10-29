# 2026-10-30：真实Parquet/Hikyuu H5日线单位倍率——两日留出样本复核

## 已验收证据与剩余缺口

用户Windows已经完成原生Hikyuu 2.8.1 `verify-real-hikyuu-h5-native-day-isolated.py` **16/16项测试OK（3.664秒）**，使用新`realday003`对**真实**2026-09-30 SH600000与SZ000001各一条日线执行原生C++ `Stock.get_kdata`。上传SAFE `real-hikyuu-native-20260930-hmac-v3.json`：
- `native_status=native_complete`、`native_last_work_phase=native_complete`、`native_matching_stock_day_count=2`、`all_two_native_h5_real_daily_records_match=true`，原始H5整数与原生Hikyuu KRecord反向整数刻度HMAC配对成功2/2。
- 原始H5仅有大小/mtime前后不变，**不是**完整源文件SHA256检查。原生SAFE未访问Parquet或正式StockManager数据库，不输出用户行情、私钥或HMAC摘要。
- 先前真实`real-parquet-h5-raw-day-unit-factor-candidates-20260930-v1.json`：两只股票同日Parquet量≈H5 raw `transCount×100` **2/2**，成交额≈H5 raw `transAmount×1000` **2/2**，OHLC≈H5整数/1000 **四字段各2/2**。
- 因Hikyuu 2.8.1真实原生驱动对两股同日日线 H5原始整数解码：价×0.001、量×1、额×0.1，**仅此样本**可推得Parquet/原生KRecord量约100、额约10000、价格约1。不能据此认定供应商量纲为“元/股/手”，不能认定长期或5min/1min也适用；此前另一日5min跨源有95/144根候选冲突。

## 本轮新增：独立于发现日的真实日线小样本

`tools/probe-real-h5-parquet-heldout-day-factors-readonly.py`

专门检查2026-09-28和2026-09-29两天，固定SH600000及SZ000001，**4条以前未用于9/30倍率发现和native验证的股票日线**：

1. 严格要求模块`reports/`已有前两份原始H5/Parquet和真实原生HMAC`SAFE JSON`；审核格式、两条匹配、候选倍率和**所有自动转换授权为false**，计算两份SAFE文本SHA256作为审计链。此前证据若失败/伪造或认证旗标被置true则拒绝开始新的真实读取。
2. 只读取既有`D:\\stock\\AllCycleAStockData\\day\\2026-09.parquet`一个月日线源文件，调用第137轮通过Windows实测的严格Reader **两次**，各日期仅保留两股两条K线。最大整月源扫描总数300000、每次最多32个RowGroup。源文件2026-09已知118208行/2组，通常总累计扫描236416行/4组；如果源内容变动或超预算则拒绝。
3. 仅`h5py.File(...,"r")`打开同样两份原始`sh_day.h5`、`sz_day.h5`，以二分检索上述两天、每股各1条日线原始复合整数记录，共4条；**不会调用原生C++检查留出日期**、不会读Parquet分钟线、不会创建H5、不会连接用户真实stock.db/SQLite。
4. 对每日期分别独立统计价(raw整数÷1000)落0.005绝对容差的数量，原始量×100、原始额×1000在1e-5相对误差的命中数，及之前固定6个倍率的命中数。量/额**零值不能作为倍率支持**（独立统计双零、单零）；异常不能被总数掩盖。
5. 只写模块`reports/`中的**新SAFE JSON**，不记录原始OHLCVA、H5整数、原始Parquet时间戳、股票代码或本地市场源绝对路径；日期可以保留用于分组。验证文件大小/mtime和Parquet Footer在分析前后不变，**不是整个大文件的SHA256**。
6. 结论为**留出日诊断结果**，即使4/4匹配，`sample_factor_generalization_certified=false`、`vendor_volume_physical_unit_certified=false`、`vendor_amount_physical_unit_certified=false`、`licensed_parquet_to_h5_mapping_certified=false`、`ready_for_full_market_mirror=false`始终保持关闭。

## Windows PowerShell（每块只有一条完整单行命令）

更新主分支：

```powershell
git pull --ff-only origin main
```

运行**12项纯合成小Parquet和H5测试**（开发端尚未完成Windows真实执行，必须以用户实测为准）：

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_probe_real_h5_parquet_heldout_day_factors_readonly.py" -v
```

确认前序真实原生SAFE在模块reports中：

```powershell
Test-Path "H5ParquetReconciler\\reports\\real-hikyuu-native-20260930-hmac-v3.json"
```

确认新输出名未占用：

```powershell
Test-Path "H5ParquetReconciler\\reports\\real-h5-parquet-heldout-day-factors-20260928-29-v1.json"
```

**只有测试OK、原生SAFE路径True且新输出路径False**后，运行只读4条新股票日线：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\probe-real-h5-parquet-heldout-day-factors-readonly.py --parquet-root "D:\\stock\\AllCycleAStockData" --h5-root "D:\\stock\\HikyuuData" --prior-raw-safe "H5ParquetReconciler\\reports\\real-parquet-h5-raw-day-unit-factor-candidates-20260930-v1.json" --prior-native-safe "H5ParquetReconciler\\reports\\real-hikyuu-native-20260930-hmac-v3.json" --out "H5ParquetReconciler\\reports\\real-h5-parquet-heldout-day-factors-20260928-29-v1.json" --read-only-heldout-days
```

**不要**上传商业Parquet、原始H5、stock.db、原始价量额。只分享结果SAFE JSON和12项测试日志。如果输出名被占用使用`v2`，禁止覆盖。不需再次运行原生core311验证或前次百万分钟线核对。

## 进入转换研究的门槛

- 比较9/28、9/29各2个留出样本的因子计数。即使全部4/4匹配也只能说明**这6个股票日（发现日2+留出日4）**支持同一原始数值倍率；不能宣称单位来源、复权、历史跨度及5min/1min已解决。
- 以后仍应从购买Parquet的**供应商字段字典**独立获取量（股/手）、额（元/万元）、OHLC复权及开盘/收盘时间标记规则；分别验证过去不同年份、不同代码、停牌和极值样本。市场源H5只读，真正写入仍禁用。
