# 2026-10-28：原生通达信日线/分钟线有界只读探测（不自动入主库）

## 目的和数据边界

上一轮标准化暂存工具`tdx-postclose-private-overlay.py`已经提供
`validate`、显式`stage --allow-private-copy`、`rollback`，
但它只能读**标准化JSON**，不能直接读通达信原生`.day/.lc5/.lc1`。
此轮新增`tools/probe-tdx-native-readonly.py`实现原生**只读格式探测**，
作为后续适配器的证据门槛。当前**不向暂存工具提供真实bar值**，
不输出CSV、不添加隐式变更/自动优选查询，不移动行情原文件。

此前用户上传的安全离线审计：
`pq-202609-three-symbol-month-shared-5min-offline-audit.json`证实
90个股票日期组合、63个有键股票日、3,024个5分钟键、
1,289条RowGroup定位、9/30单日逐组严格对账通过。
另据沪深交易所**2026年中秋节休市安排**，9月25～27日休市，
9月28日正常开市；所以9月25日零键不是上述样本的缺失证据。
相关公告：
- https://www.sse.com.cn/disclosure/announcement/general/c/c_20260915_10832273.shtml
- https://www.szse.cn/www/disclosure/notice/general/t20260917_622911.html

## 本轮支持的候选通达信二进制布局

常见的32字节无文件头、小端格式（以下**不是对用户当前安装版本的实测**）：

| 文件类型 | 前四字节 | OHLC | amount | volume | 后四字节 |
|---|---|---|---|---|---|
| `.day` | uint32 YYYYMMDD | 4×uint32除以100 | float32（不转换） | uint32（不转换） | 保留字段 |
| `.lc5` | uint16压缩日期+uint16分钟数 | 4×float32 | float32（不转换） | uint32（不转换） | 保留字段 |
| `.lc1` | 与`.lc5`同候选结构 | 4×float32 | float32（不转换） | uint32（不转换） | 保留字段 |

分钟线日期候选规则：`year=2004+packed//2048`，
`month=(packed%2048)//100`、`day=(packed%2048)%100`，
分钟数是从当天00:00起的分钟数。
通达信各版本/供应商导出、复权与量额换算可能不同；
本轮**不做单位缩放、不声明金额/成交量单位已经确认**。

外部依据（有具体布局说明，但不是官方最新协议认证）：
- https://github.com/donge/tdx_ext （日/分钟的32字节字段布局）
- https://www.cnblogs.com/citycomputing/p/6242980.html （分钟压缩日期与字段）
- https://pytdx-docs.readthedocs.io/zh-cn/latest/hqreader/ （pytdx支持TDX本地文件）

## 安全与读取方式

- **只允许显式选择1个文件、1只证券、1个日期**；
  名字必须有`sh/sz/bj+六位代码`前缀、扩展名为
  `.day/.lc5/.lc1`，`--symbol`必须与文件名匹配。
- 最多读取64MiB的**单文件**（可传`--max-source-bytes`
  进一步缩小，不允许增大上限）；文件必须为32字节对齐，
  不可为空或直接符号链接；只做顺序流读取/哈希。
- 逐条解析全年/月历史K线元数据，严格验证源时间键递增、
  日期字段合法及OHLC逻辑/有限数值；任一坏记录即拒绝，
  不会跳过错误行并假称数据完整。
- 用标准库`struct`解码，**不读取/写入Parquet/H5**；
  只在进程内暂存指定日期的分钟数，用于比对公认时间网格，
  不导出单根真实bar或独立时间键。
- 输出`H5ParquetReconciler/reports/`里的**全新安全JSON**
  （源文件大小、记录数、首尾日期、源完整内容SHA256、
  当日匹配记录数量、时间网格候选分类、未验证声明）；
  **不输出任何OHLCVA、源文件绝对路径、原始分钟键**。
  对已存在报告不覆盖，CLI强制用户显式加`--read-only`。
- 读取前后检查文件stat大小/mtime一致；这无法阻止恶意同尺寸同mtime
  篡改，也不能证明文件是合法真实的供应商行情，但和完整文件SHA
  结合可以审计数据版本。
- 不提供写操作，不生成或修改`work/`目录，不影响任何生产查询。

## 时间标签分类不是强制补齐

可能存在以下**候选**时标（依据此前购买Parquet历史实验及TDX公开格式，
必须以你本机的真值核验）：

- 5分钟线：`5min_start_48`（09:30～11:25，13:00～14:55），
  `5min_end_48`（09:35～11:30，13:05～15:00）。
- 1分钟线：`1min_start_240`（09:30～11:29，13:00～14:59）、
  `1min_end_240`（09:31～11:30，13:01～15:00）、
  `1min_opening_plus_end_241`（09:30～11:30，13:01～15:00）。
- 日线：该日期恰有1根记录。

没有记录：`no_records_on_requested_date`，**只说明本地这个文件
该日期未找到键**，不能判断是停牌、周末、休市、未下载、缺数据或
文件名错。

有记录但不符合任何候选网格：
`unrecognized_or_partial_time_grid`，不得进行自动填充、自动
补缺或转换入库。严格匹配：
`recognized_native_time_grid`，也**只证明时间标签网格特征，
不能认证数值、单位或真源**；更不是入主库的通行证。

## 本机验收（Windows PowerShell，仓库根目录）

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\probe-tdx-native-readonly.py
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_probe_tdx_native_readonly.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

如果本机已有TDX原生日线文件，先查找（**不会改动文件**）：

```powershell
Get-ChildItem "D:\stock" -Recurse -File -Filter "sh600000.day" |
    Select-Object -First 5 -ExpandProperty FullName
```

找到实际路径后，执行**明确文件和日期**的单文件只读探测，
用真实文件路径替换下面的示例，不要预设它真的存在：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\probe-tdx-native-readonly.py --source "D:\stock\vipdoc\sh\lday\sh600000.day" --symbol SH600000 --date 2026-10-27 --read-only --out "reports\tdx-native-sh600000-day-20261027-probe.json"
```

分钟线分别可选`sh600000.lc5`、`sh600000.lc1`，扩展名自动决定周期，
每日时间标签按原生记录识别，不强行使用之前Parquet的241/48网格。
**不要上传真正的本地二进制源/中间转换OHLCVA**，只上传
`reports/`里安全JSON和测试`OK`/错误输出。
若尚未有任何TDX原生文件，执行合成单测即可，不能把购买Parquet
或H5冒充TDX源来宣称真实接入完成。

## 仍待开发

1. 获得本机TDX实际二进制的探测结论后，对同股同日的TDX
   日/1min/5min（若有）执行只读跨周期对照及量额单位假设检验，
   明确复权口径和时间标签，再构建受控标准化adapter。
2. 对`tdx-postclose-private-overlay.py`的完整网格约束作明确版本化，
   避免把TDX常见240分钟线错误强制要求Parquet特有241根。
3. 在保留源数值和来源指纹的前提下，进入独立暂存层、版本及回滚演练；
   未审核的TDX永不自动覆盖已验证的历史Parquet/H5。
4. 生产统一查询（Parquet优先、H5核验回退、TDX盘后增量）仍未实现。
   不把这一步的只读探测包装为已经入库。
