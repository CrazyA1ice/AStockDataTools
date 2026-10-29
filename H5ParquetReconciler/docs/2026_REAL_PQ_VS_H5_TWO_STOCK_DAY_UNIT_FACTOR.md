# 2026-10-29：真实 Parquet 与 Hikyuu H5 原始记录的双股票日单位倍率候选核对

## 已取得的验收（无需重复旧大扫描）

- 用户已完成离线汇总门禁 **10/10 全部OK（0.493秒）**，生成`real-precision-crosssource-evidence-bridge-v1.json`，只读取三份已脱敏报告，没有扫描行情。报告明确区分：2026-09-30的两股Parquet真实日线精度、SH600000的TDX↔Parquet 48/48条5min六字段容差匹配，及不同日期2026-09-28三股H5↔Parquet 144条5min中的**95条候选冲突**。
- 完全合成Parquet→H5→Hikyuu2.8.1 C++原生重读6/6已验收；但该试验不能证明购买Parquet与**真实H5存储记录的物理单位**一致。2026-09日线购买Parquet 118208条/2行组、金额与成交量Arrow float64，时间戳int64的Footer epoch_ms候选282/282组匹配。
- TDX和Hikyuu H5不是同一个来源。不能把TDX对账和H5部分样本冲突抵消解释成统一倍率。

## 本轮目标

新增 `tools/probe-real-parquet-h5-day-unit-factors-readonly.py`：只针对**2026-09-30、SH600000与SZ000001各一条实际日K线**，以只读方式同时获取：
1. 一份购买Parquet的`day/2026-09.parquet`，调用上一轮已通过Windows的限量日线Reader，仅接受1份文件≤150000行、≤32组，实际2026-09文件之前曾读取118208行/2组；内存中保留2只股票的6个原始float64字段。
2. 原始Hikyuu H5 `sh_day.h5`、`sz_day.h5`中的`/data/SH600000`及`/data/SZ000001`。使用`h5py.File(...,"r")`，仅通过有序日期键的二分查找读取每只一条`202609300000`日K线原始整数记录；每个股票的全历史H5数据集不超过25000行，否则拒绝。若缺文件、缺列、重复/缺日期、非整数类型、源文件大小/mtime变动则拒绝，**不扫描其他证券、不会打开任何正式数据库或H5写入模式**。
3. 对原始H5整数值测试假设性倍率`0.01,0.1,1,10,100,1000`，比较`Parquet原始float64数值 ≈ H5原始整数 × 候选倍率`，仅统计2个非零配对中符合相对容差`1e-5`的数量。全零与一侧为零的配对被单独计数，**不能**视为某个倍率通过。OHLC仅测试H5整数价格÷1000与Parquet价格在`0.005`绝对误差内的候选一致数量。
4. 只输出有限的字段角色、固定倍率、匹配计数、扫描行/组总数、否定认证旗标。不输出原始真实OHLCVA、H5原始整数、Parquet时间戳、源目录或证券编号。Safe JSON只写模块`reports/`中的一个**新**文件，不覆盖旧报告，且无正式H5镜像写入。

### 重要解释

此程序读取的是**真实H5复合数据集的原始整数记录**，不调用Hikyuu C++原生解码器，亦不使用提供者的独立单位说明。因此即使SH600000、SZ000001在单日均呈现成交量×100或成交额×1000的候选倍率，也只说明这些样本的**原始数值倍率**，既不保证H5驱动对这两个字段的用户可见单位等于此前合成样本，也不保证该倍率跨年、跨证券、跨周期通用。

特别不要混淆：旧跨源`H5成交量×100`用于**解码后所采用的旧诊断口径**，本轮“原始H5整数×100”用于**原始磁盘记录直接配对**。两者数值比例是否相同必须由源记录编码规则与原生读取双重验证后才可关联。测试没有独立供应商文件字典，`parquet_vendor_physical_volume_unit_certified=false`、`parquet_vendor_physical_amount_unit_certified=false`、`native_hikyuu_driver_unit_mapping_certified=false`、`licensed_parquet_to_h5_mapping_certified=false`、`ready_for_full_market_mirror=false`始终不变。

## Windows操作（**每条PowerShell命令一整行，不使用反引号换行**）

更新仓库：

```powershell
git pull --ff-only origin main
```

运行新增11项**仅使用虚构小型Parquet/H5文件**的回归（尚待用户Windows实测）：

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_probe_real_parquet_h5_day_unit_factors_readonly.py" -v
```

执行前确认真实H5源目录是否使用仓库既有`HikyuuData`位置（不得为了此核对更改正式H5）：

```powershell
Test-Path "D:\\stock\\HikyuuData\\sh_day.h5"
```

```powershell
Test-Path "D:\\stock\\HikyuuData\\sz_day.h5"
```

若本机原始H5路径不同，在下一条命令中只调整`--h5-root`为对应真实存在、包含`sh_day.h5`及`sz_day.h5`的绝对文件夹。必须**先11项全通过、两项Test-Path都为True**后，再执行一次小样本真实只读：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\probe-real-parquet-h5-day-unit-factors-readonly.py --parquet-root "D:\\stock\\AllCycleAStockData" --h5-root "D:\\stock\\HikyuuData" --trading-day "2026-09-30" --prior-bridge-safe "H5ParquetReconciler\\reports\\real-precision-crosssource-evidence-bridge-v1.json" --out "H5ParquetReconciler\\reports\\real-parquet-h5-raw-day-unit-factor-candidates-20260930-v1.json" --read-only-two-source-factor
```

只回传新的SAFE JSON和测试结果；**不要**上传原始商业Parquet、正式H5、Hikyuu数据库或真实证券价量额。若SAFE文件名已存在，请用v2新名字，不可覆盖。

如果原始H5指定股票日缺失，本程序安全退出；可以在后续阶段根据独立证据决定改用其他窗口，不应为了“通过”放宽到无限扫描所有历史文件。

## 下一阶段

若真实两源单位倍率候选清晰，先核验：
- Hikyuu 2.8.1 C++原生驱动对**真实H5原始复合记录**的解码单位（不只合成数据）。
- 购买Parquet源数据商关于amount、volume、复权和时标的书面字段定义，明确元、万元、股、手等。
- 价格/量/额跨周期和跨交易日的误差、异常处理、舍入模式与uint32/uint64范围。

**以上均未获得独立证据时，严禁正式生成/覆盖任何市场H5，亦不能切换生产数据源。**
