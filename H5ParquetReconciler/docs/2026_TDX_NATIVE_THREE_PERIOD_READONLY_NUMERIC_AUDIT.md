# 2026-10-28：通达信原生日线、1分钟、5分钟同日价量额只读核验

## 真实证据与问题定义

此前**用户Windows本机真实来源**对SH600000/2026-09-30做了两份
`probe-tdx-native-readonly.py`安全JSON：
- 原生`sh600000.lc1`：240根，`1min_end_240`，
  09:31—11:30，13:01—15:00；源总25,200根；
  文件覆盖2026-05-11至2026-10-13。
- 原生`sh600000.lc5`：48根，`5min_end_48`，
  09:35—11:30，13:05—15:00；源总5,040根，
  覆盖同样日期，源排序、稳定性合格。
- 原生`sh600000.day`实测1999-11-10至2026-10-13的6,404根
  可被正确解码，10/13指定日期有1根。**2026-09-30当日日线
  尚未单独核验，需在本次对账时由新工具验证。**
- 购买Parquet的1分钟样本可能有**241根特殊开盘记录**、五分钟线
  曾使用**区间起点标签**，所以不能拿TDX 240根/结束标签按
  同时间戳逐条对齐或补出一根。

这轮仅验证**同一TDX来源内部**的三周期OHLCVA相对关系，
不读取购买Parquet/H5，不推断换算单位，不自动并集或自动补记录。

## 新增工具及真实做法

`tools/audit-tdx-native-three-period-readonly.py`接受：
- 必须显式指定同一股票的原生日线`*.day`、5分钟线`*.lc5`
  和1分钟线`*.lc1`的3个不同本地文件，以及交易日与
  **`--read-only`**。每个文件<=64MiB（可通过
  `--max-source-bytes`进一步降低）；只读取来源字节，不写源文件。
- 先借用既有`probe-tdx-native-readonly.py`做**完整文件检验**：
  文件名股票一致、全源时间键严格递增、32字节布局、
  每条源OHLCVA有限且合法、文件读取期间stat稳定、
  完整源内容SHA-256。
- 对所选日期严格要求：日线1根、1分钟240根且
  `1min_end_240`、5分钟48根且`5min_end_48`。
  任一缺失、不完整、只满足241根或标签不符则**停止**，
  不把未知时标自动映射到已有模式。
- 再读取文件并验证文件完整SHA-256仍与第一次探测一致，
  只将该日的价量额放进Python内存，**不落盘、不打印**。
- 从每连续5根1分钟K线重建1根5分钟K线，严格验证
  `end-4...end`与原生5分钟结束时刻对应；
  开盘采用首根open、高价为max(high)、低价为min(low)、
  收盘为末根close、成交量及成交额分别求和。
- 依次计算3组配对：
  ①1min→5min重建与原生5min逐根48组对照；
  ②5min汇总与原生日线单组对照；
  ③1min汇总与原生日线单组对照。
- 输出6个字段（开高低收、成交量、成交额）每组的
  `n`、容差内匹配数、最大/平均**相对误差**；
  对成交量、成交额再输出**被比值/参考值中位数**和正值参考计数，
  以便发现可能的乘100、除100或其他系统性口径差异。
  **这些比例只是诊断，绝不擅自换算或改动来源值。**
- 价格诊断容差：`math.isclose(rel_tol=1e-5,abs_tol=2e-4)`；
  量额容差：`rel_tol=1e-5,abs_tol=0.02`。
  容差匹配只能表达数值接近，不表示源真实、复权口径正确或
  所有历史日期可合并。

## 不泄露与回退边界

- 只新建`H5ParquetReconciler/reports/`中的安全JSON；包含文件
  **basename**、全源SHA256、日期覆盖、记录数量、相对误差
  和比例统计；不写原始OHLCVA、价格水平、绝对成交量/成交额，
  不写实际源绝对路径或任何个别分钟时间键。
- `H5ParquetReconciler/work/`不创建或修改；
  原始`.day/.lc1/.lc5`，购买Parquet、H5和正式查询均不修改。
- 即使所有容差内匹配仍然
  `eligible_for_automatic_production_union=false`。
  此时只能进入“量额单位、复权、上市证券品种/口径、开盘特殊记录”
  的进一步独立证据核验。
- 历史的Parquet 241条不在本工具映射范围；
  不发生“自动补开盘一条”或跨源静默修复。
- 一次仅单只股票、单个有数据日期，不支持长时间范围/全市场后台扫描。

## Windows PowerShell本机验证

在仓库根目录`D:\ChatGPT\AStockDataTools`：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\audit-tdx-native-three-period-readonly.py
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_tdx_native_three_period_readonly.py" -v
```

已有用户真实通达信文件的**明确实例**：
```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-tdx-native-three-period-readonly.py --day-file "D:\software\TDX\vipdoc\sh\lday\sh600000.day" --minute5-file "D:\software\TDX\vipdoc\sh\fzline\sh600000.lc5" --minute1-file "D:\software\TDX\vipdoc\sh\minline\sh600000.lc1" --symbol SH600000 --date 2026-09-30 --read-only --out "reports\tdx-native-sh600000-three-period-20260930-audit.json"
```

该命令在本机一次读取三个真实原生文件，**不会**读Parquet/H5。
如果文件结构、量额值或当日日线不符合约定，会拒绝写报告并给错误；
不要为了得到“通过”而关闭源的完整性检查。
目标报告已经存在时换新文件名，拒绝覆盖。

之后跑整个模块的测试，便于发现前轮Win32句柄等遗留问题：
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

**上传新安全JSON或错误终端输出即可，不要上传购买/通达信的
原始行情二进制、已标准化OHLCVA记录或本地`work/`文件。**

## 已测试范围与后续主线

本轮增加7个合成单测：三周期完全一致、成交量100倍口径差、
单个5min收盘价漂移、TDX241根分钟线拒绝、缺少分钟记录及错周期、
源指纹跨读不一致、CLI仅安全报告且禁止覆盖。
开发环境使用模拟的既有probe接口，对本轮纯合成数据执行了
`Ran 7 tests ... OK`；**GitHub真实仓库+用户Windows的完整
联动测试仍需上述命令验证**，不能冒充真实TDX三周期结果。
后续基于这次真实量额误差报告，优先确认源单位与精度，
再决定受审核的TDX标准化到本地隔离层的规则；统一
Parquet优先/H5核验回退/TDX盘后增量查询还未实现。
