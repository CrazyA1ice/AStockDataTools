# 2026-10-29：真实两股票日线 Hikyuu 2.8.1 C++ 原生驱动读数——隔离 HMAC 核对

## 为什么现在做

- 用户Windows已完成 `test_probe_real_parquet_h5_day_unit_factors_readonly.py` **11/11 OK（3.777秒）**。真实只读2026-09-30的 SH600000、SZ000001各一条：购买Parquet的量≈**原始H5整数`transCount×100`**，金额≈**原始H5整数`transAmount×1000`**，OHLC≈**H5原始价格整数÷1000**，均2/2命中；其他五种数量倍率未命中（只试固定6个因子，容差1e-5）。此为真实样本而非全市场通用性证明。
- 既有用户Windows合成的H5→Hikyuu2.8.1 C++ `Stock.get_kdata` **6/6匹配**，但那是合成数据，不是本次真实H5文件。此前Hikyuu上游2.8.1源码提示native解码OHLC raw×0.001、amount raw×0.1、volume raw×1；本轮验证真实日线是否实际遵循这个解码规则。**如果该原生解码也匹配**，样本量级上Parquet对`KRecord`应分别呈量×100、额×10000的关系，仍需供应商数据字典解释“股/手”“元/万元”等真实物理单位。
- 原先汇总的另外一日三只股票的H5/PQ 5min样本仍有**95/144条候选任意字段冲突**；不能用日线两股一致掩盖它。

## 新增工具与安全边界

`tools/verify-real-hikyuu-h5-native-day-isolated.py`

严格限定目标**2026-09-30、SH600000和SZ000001的两份真实原始H5日线**，必须已有上轮成功的`real-parquet-h5-raw-day-unit-factor-candidates-20260930-v1.json`，且其各种未认证标志保持为false。这里只打开`D:\\stock\\HikyuuData\\sh_day.h5`、`sz_day.h5`，**不再读取Parquet**。

父进程由项目`.venv`内H5Py只读二分定位两只股票各一条原始40字节结构记录，检查`datetime`键、7个整数类型、整数精度范围、每股票日线数据集≤25000条，使用随机32字节密钥对两条记录构造HMAC-SHA256期望值；**从不将原始价量额或解码整数传入命令行、报告或子进程环境**。将一次性随机密钥通过当前进程环境变量送入隔离Python子进程，**不写入硬盘**。

子进程必须使用用户已有`D:\\software\\Python311\\python.exe`（须实际存在且安装 Hikyuu **2.8.1**），以`-I`启动，借鉴此前已经成功的合成原生测试：仅加载已安装C++ core311，不执行顶层`hikyuu_init()`、不读取用户正式`stock.db`、不加载默认插件。子进程仅在本模块`work/h5_mirror/real_day_native/<新run-id>/`建立**虚构证券注册SQLite**，把HDF5驱动的`sh_day`、`sz_day`明确指向两份只读检查过的原始H5文件，调用每股票`Stock.get_kdata(Query(-64,DAY))`，最多要求**返回64条最近日K线**，检查目标交易日恰好一根。

本轮只在原生子进程内从KRecord数值按已检验的Native存储刻度**逆向求最近整数**（OHLC×1000、amount×10、volume×1）并生成HMAC。父进程仅比较HMAC是否与其只读原始记录对应；HMAC密钥、摘要、真实证券价量额均不出现在最终SAFE，也不把任何原始H5交易值另存临时文件。本工具在模块reports里生成**新JSON**，只写两条配对是否完整匹配、上次运行阶段、固定字段的运行状态和认证仍为false。

**注意风险界限：** 子进程使用C++ native读取真实H5，而不是虚构源；父进程以stat大小/mtime检查两份源运行前后未变，但没有执行大型文件全内容SHA256，所以报告特别标明`original_h5_full_content_sha256_checked=false`。仅请求64条KRecord并不能保证底层HDF5驱动内部没有读取额外块。不要向仓库提交用户原始H5或市场注册数据。

### 原生状态可能为 false

由于真实市场日线文件可能有不同日期排序、stock注册库不兼容、core311运行时故障或最近64根K线不含指定日期，本轮实机输出可能有`all_two_native_h5_real_daily_records_match=false`。这时请直接上传SAFE，由`native_status`、`native_last_work_phase`定位；**不要**为了强行获得true而更改原始H5或调大无限扫描范围。C++异常/崩溃/超时不会冒充成功。

## Windows PowerShell：一条命令一整行、互不换行

拉取主分支：

```powershell
git pull --ff-only origin main
```

运行新增12项**完全合成H5+模拟native子进程**回归（本轮开发端未实测Windows）：

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_verify_real_hikyuu_h5_native_day_isolated.py" -v
```

确认Python311原生环境仍然存在：

```powershell
Test-Path "D:\\software\\Python311\\python.exe"
```

确认两份正式H5日线源仍然存在：

```powershell
Test-Path "D:\\stock\\HikyuuData\\sh_day.h5"
```

```powershell
Test-Path "D:\\stock\\HikyuuData\\sz_day.h5"
```

全部为True且12项本机回归OK后，运行一次真实**只读**native：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\verify-real-hikyuu-h5-native-day-isolated.py --h5-root "D:\\stock\\HikyuuData" --prior-two-source-safe "H5ParquetReconciler\\reports\\real-parquet-h5-raw-day-unit-factor-candidates-20260930-v1.json" --python-exe "D:\\software\\Python311\\python.exe" --run-id "realday001" --timeout 60 --out "H5ParquetReconciler\\reports\\real-hikyuu-native-20260930-hmac-v1.json" --native-read-only-two-stock-day
```

`--run-id`必须全新，`--out`必须全新，不能覆盖；失败后下次使用`realday002`和`v2`。仅需上传该**不含原始H5值和任何HMAC摘要**的SAFE，以及测试日志。真实源不能上传或写入Git。

## 下一步需要什么

若原生真实H5的2/2确认匹配，可把**H5原始数值→Hikyuu KRecord解码倍率**纳入一条有效、可追溯的真实本机样本链条。与前轮Parquet/H5原始整数×100/×1000两股样本证据组合起来，可得到具体样本的KRecord解码比例假说，但仍**不能认证商业Parquet物理单位**或开启正式H5写入；应继续索取商业数据供应商的字段定义和不同历史阶段样本验证。

源码与此前原生合成读取工具隔离运行模式一致，但**本轮确实会读取两份用户真实H5（只读）**；确认本机许可、备份和实际需求再执行。
