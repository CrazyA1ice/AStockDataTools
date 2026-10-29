# 2026-10-30：跨年两个月真实Parquet与Hikyuu H5日线倍率候选复核

## 已证实的基础

- 用户Windows已完成第144轮**12/12项合成测试OK（2.241秒）**，同时成功生成真实`real-h5-parquet-heldout-day-factors-20260928-29-v1.json`。
- 该真实报告的2026-09-28、2026-09-29各2条股票日线（SH600000及SZ000001）全部满足：成交量`Parquet≈H5原始transCount×100` **4/4**、成交额`Parquet≈H5原始transAmount×1000` **4/4**，OHLC原始整数÷1000各字段**4/4**；量与额皆4/4正非零配对，不是全零带来的伪匹配。
- 加上2026-09-30先前真实两股日线**2/2**，相同九月份三个日期累计**6个股票日**支持这组候选比例。2026-09-30另已真正经Hikyuu 2.8.1 C++ `Stock.get_kdata()` + HMAC证实两股真实H5原始整数↔原生解码KRecord成功2/2；其余日期没有重复C++原生验收。
- **全部证据仍只在2026-09这一个月份。** 另外，之前在2026-09-28对其他证券的H5↔Parquet五分钟数据还有95/144根候选残差；不应将同月日线的一致性扩展为所有周期都可互转。

## 新增跨年份两个月固定小样本

新增`tools/probe-real-h5-parquet-crossyear-day-readonly.py`。下一轮仅查看以下**两个此前完全未用于倍率验证的交易日**：

| 日期 | 月度Parquet源 | 目标股票 | H5 |
|---|---|---|---|
| 2025-09-30 | **`day/2025.parquet`（年度文件）** | SH600000、SZ000001 | `sh_day.h5`、`sz_day.h5` |
| 2026-08-24 | `day/2026-08.parquet` | SH600000、SZ000001 | 同上 |

这些日期是预先固定的选取，不会因缺文件、停牌或不匹配而自动替换。若任一文件/目标日缺失或源超预算，拒绝整个本轮实验，**不能**因为试验失败而自动扩大读取范围。

- 先读取模块`reports/`下**三个已有SAFE**：2026-09-30原始H5与Parquet两股票日匹配报告、同日真实原生Hikyuu2.8.1 KRecord HMAC 2/2报告，以及2026-09-28/29的留出4/4匹配报告。逐一确认日期、字段、数量、零值、此前SAFE之间哈希链及所有转换认证仍为false；新报告记录三份SAFE的SHA256，但不允许任意报告路径进入模块外。
- 从**两个固定日线Parquet源文件**只读取限定8列。2025年度文件从Footer核验全年≤160万行/≤16个RowGroup，**只解码Footer时间范围命中目标日的最多2个RowGroup，实际读取≤150000行**；2026-08月度文件直接使用此前已通过的≤150000行/≤32组严格Reader，总实际解码≤300000行/64组；H5端只打开原始`sh_day.h5`、`sz_day.h5`两份文件，以日期键二分定位每个固定股票日的**4条H5原始复合整数记录**；不会读取5分钟/1分钟数据，也不会创建或转换真实H5。
- 固定重用此前已经Windows运行的`PAIR.evaluate()`：分别统计价格OHLC H5整数÷1000与Parquet价格在0.005内的匹配数量、成交量原始整数×100与成交额原始整数×1000在1e-5相对容差内的数量，同时保留每个日期六个倍率的分组统计。对一方/双方为零的数量**单独计数、不当作倍率证据**。
- 所有源文件只读，分析前后核对Parquet Footer与两份H5文件size/mtime是否一致（不是全文件SHA256）。每个源若缺少符合条件的两股记录、错误schema、重复日线，立即拒绝。只输出`reports/`内一个**新**SAFE JSON，不输出证券代码、真实OHLCVA、日期原始int64时间戳、H5原始整数、H5/Parquet绝对文件路径、异常栈或数据样本。
- **本轮不执行跨年样本上的原生C++ Hikyuu读取。**此前原生2/2只覆盖2026-09-30；如果本次4/4通过，代表**2025-09和2026-08两个月的4个新股票日**也支持同样的H5原始整数倍率，只能扩展样本证据，不能声明跨年普适规律或已认证供应商“元、万元、股、手”等具体物理单位。
- `vendor_amount_physical_units_certified`、`vendor_volume_physical_units_certified`、`source_timestamp_semantics_certified`、`universal_factor_across_time_or_periods_certified`、`licensed_parquet_to_h5_mapping_certified`、`ready_for_full_market_mirror`始终false。

## 第145轮Windows实测阻断及数据布局修复（2026-10-30）

- 用户Windows已完成原先跨年合成回归**13/13项OK（3.074秒）**，但真实`Test-Path "D:\\stock\\AllCycleAStockData\\day\\2025-09.parquet"`为**False**，`day\\2026-08.parquet`为True，真实工具因历史月文件缺失而安全拒绝，没有产生新SAFE，也未完成跨年倍率验证。
- 再核对用户此前上传的真实`parquet-primary-footer-inventory-2011-2026.json`，它**明确记录2025年度日线为单文件**`AllCycleAStockData/day/2025.parquet`，**1333385行、12行组**，并包含2025-01至12月的Footer日期包络；**2026年才改成逐月**`day/2026-08.parquet`，该文件117969行、2行组。此前硬编码`day/2025-09.parquet`是本工具错误假设，并**不证明2025历史行情缺失**。
- 修复后的`read_annual_2025_selected_day`只接受2025年度`day/2025.parquet`及已约定的2025-09-30，先核对所有行组ts字段为int64并逐组检验可信min/max且位于2025年度；仅选择时段包络与9月30日重叠的≤2个行组，总目标行组≤150000行才用PyArrow读选中行组。其他全年非相关行组**不会被解压/扫描**；没有时间统计、缺目标日、目标日重复、月组太宽都会拒绝。
- 因年度Parquet总行数可达133万，本轮严格**禁止**仅把2025文件名换成`2025.parquet`后用旧的月文件全扫描Reader，这会超出原有150000行预算。代码明确区分年度Footer剪枝与2026月度Reader，并在新SAFE记录年度Footer总数/总行组及实际目标行组数量，不输出源绝对路径/真实价量额。
- 新增**3项纯合成年度文件回归**：2025年度12个模拟行组只读命中1组、缺ts min/max统计拒绝、目标组扫描预算超限拒绝、跨出2025的错误Footer范围拒绝。本轮总测试量从13项增加到**16项（仍待Windows复验）**。任何来源都不修改，H5写入与真实物理单位认证继续关闭。

## Windows PowerShell：每条命令占一整行

更新仓库：

```powershell
git pull --ff-only origin main
```

首先运行新**16项纯合成小Parquet/H5回归**（这些测试的Windows实测结果尚未知）：

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_probe_real_h5_parquet_crossyear_day_readonly.py" -v
```

确认两个固定旧月Parquet源存在：

```powershell
Test-Path "D:\\stock\\AllCycleAStockData\\day\\2025.parquet"
```

```powershell
Test-Path "D:\\stock\\AllCycleAStockData\\day\\2026-08.parquet"
```

确认已有同月留出SAFE存在：

```powershell
Test-Path "H5ParquetReconciler\\reports\\real-h5-parquet-heldout-day-factors-20260928-29-v1.json"
```

确认新报告尚未存在：

```powershell
Test-Path "H5ParquetReconciler\\reports\\real-h5-parquet-crossyear-day-factors-20250930-20260824-v1.json"
```

只有**16项全部OK、三个已知文件均True、目标新报告False**时，运行一次两月只读：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\probe-real-h5-parquet-crossyear-day-readonly.py --parquet-root "D:\\stock\\AllCycleAStockData" --h5-root "D:\\stock\\HikyuuData" --prior-raw-safe "H5ParquetReconciler\\reports\\real-parquet-h5-raw-day-unit-factor-candidates-20260930-v1.json" --prior-native-safe "H5ParquetReconciler\\reports\\real-hikyuu-native-20260930-hmac-v3.json" --prior-heldout-safe "H5ParquetReconciler\\reports\\real-h5-parquet-heldout-day-factors-20260928-29-v1.json" --out "H5ParquetReconciler\\reports\\real-h5-parquet-crossyear-day-factors-20250930-20260824-v1.json" --read-only-crossyear-days
```

如新输出名称被占用，换`v2`并保留所有既有报告；**禁止覆盖或删除原始商业H5/Parquet文件，不需要重新读取原生Core311。** 仅上传新SAFE和16项测试日志，不要上传原始行情、原生SQLite或客户商业数据。

## 后续

- 若两个跨年月份的4个股票日均4/4匹配，结合2026-09已验收的6个股票日，共有**10个股票日在三个不同月份（跨2025、2026）**支持这些候选倍率；仍需独立供应商字段字典和更多证券/分钟周期异常核查。
- 若部分月份有缺数或出现价格/量/额差异，当前只输出分日统计和安全失败，不擅自补全、归一化、写入生产H5。
