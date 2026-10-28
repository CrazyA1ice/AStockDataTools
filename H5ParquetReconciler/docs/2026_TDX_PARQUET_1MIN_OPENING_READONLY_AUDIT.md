# 2026-10-28：SH600000真实跨来源day/5min一致；Parquet额外09:30分钟记录只读诊断

## 2026-10-28 真实241根一分钟报告回传：开盘合并假说进一步核对

用户本机真实 `tdx-vs-pq-sh600000-20260930-1min-opening-audit.json`
已经证明 SH600000、2026-09-30：

- TDX分钟240、Parquet分钟241、Parquet五分钟48，源文件完整性验证通过。
- **共同240根：** high/low/close三项均240/240匹配；
  open/volume/amount各239/240匹配。开盘价最大相对差
  0.0021692263，成交量最大相对差0.0991382916，
  成交额最大相对差0.0992703168。报告未输出具体错位时间，
  不能仅凭239/240就断言差异必然是09:31。
- Parquet的额外**09:30**开盘记录volume、amount均非零，
  且它的open不同于09:31常规开盘价；纳入09:30后
  Parquet 1min→原生Parquet 5min 的48组OHLCVA**全部匹配**。
  不纳入则第一根5min开盘价、volume、amount不匹配，
  第一根volume相对差约0.0410460686、
  amount相对差约0.0410340581。
- **待验证的新解释：** TDX原生09:31可能已经合并了Parquet
  的09:30与09:31两条记录（如开盘阶段成交归属不同）。
  需要明确比较：TDX 09:31一根OHLCVA
  **vs** Parquet 09:30+09:31两根OHLCVA合并结果；
  其余239根是否逐根吻合；检查合并后240根是否全六字段吻合。
  不可提前标记为已认证转换规则。

因此扩展`audit-tdx-vs-parquet-1min-opening-readonly.py`，
在**原始两源各一次只读读取的数据**上额外输出：

- `first_minute_opening_merge_hypothesis.native_0931_vs_parquet_0931_without_opening`
- `first_minute_opening_merge_hypothesis.native_0931_vs_aggregation_of_parquet_0930_and_0931`
- `first_minute_opening_merge_hypothesis.remaining_239_native_vs_parquet`
- `first_minute_opening_merge_hypothesis.all_240_native_vs_first_merged_plus_remaining_239`
- 三个独立布尔结论，用来表明合并前、合并后与其余239根的
  容差匹配结果。即使全部通过，仍然
  `opening_merge_is_only_a_hypothesis_not_a_mapping_rule=true`、
  `eligible_for_automatic_production_union=false`。

本次新增2项合成回归：
1. 真实模拟：Parquet09:30记录价、量、额非零、开盘价不同于
   Parquet09:31；TDX09:31聚合包含两根数据，需出现
   原始第一根不匹配→合并后六字段全部匹配、其余239根匹配。
2. 反例：即使Parquet09:30非零，如果TDX09:31不包含这些值，
   必须明确将合并假说标记为不通过，而不能进行静默修正。

### Windows复验（仓库根目录）

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\audit-tdx-vs-parquet-1min-opening-readonly.py
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_tdx_vs_parquet_1min_opening_readonly.py" -v
```

此前已存在报告同名文件，**必须换新名称**，否则CLI拒绝覆盖：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-tdx-vs-parquet-1min-opening-readonly.py --parquet-root "D:\stock" --tdx-1min-file "D:\software\TDX\vipdoc\sh\minline\sh600000.lc1" --symbol SH600000 --date 2026-09-30 --read-only --out "reports\tdx-vs-pq-sh600000-20260930-first-minute-merge-v2.json"
```

这次复验不增加新的Parquet行组扫描范围：仍使用单股单日
1min与5min两周期，数据未出本机内存，仅新增字段级统计。
工具新增回归测试现为10项，**Windows真实执行结果尚未回传**。
报告可以提供给ChatGPT，不能上传真实原生二进制/Parquet
或包含市场OHLCVA明细的JSON。

---



## 前置真实证据（来自用户上传的安全JSON）

`tdx-vs-pq-sh600000-20260930-day5min.json`：
- 2026-09-30 SH600000真实TDX`.day`1根、`.lc1`240根、
  `.lc5`48根；TDX三周期内部一致（所有六个字段在容差内）。
- 独立购买Parquet当日日线1根、五分钟48根。
- 原生TDX`5min_end_48`与Parquet`5min_start_48`
  通过**同一个5分钟交易区间**对齐，48组OHLC全部容差内，
  最大价格相对误差约4.83e-08。
- 48根成交量逐组完全匹配，成交额最大相对误差1.048e-07；
  两来源日线OHLC完全匹配，成交量最大相对误差1.356e-07；
  Parquet内部五分钟聚合到日线六字段亦容差通过。
- 证据仅覆盖这只股票**一个真实交易日**；不保证全市场、
  不认证除权复权与量额单位的普遍一致，更未验证Parquet一分钟线。

## 继续主线：新增`audit-tdx-vs-parquet-1min-opening-readonly.py`

风险：TDX实测是`1min_end_240`（09:31—11:30、
13:01—15:00）。购买Parquet一分钟历史样本可能采用
`1min_opening_plus_end_241`，额外在09:30有一个独立记录。
不可以直接删09:30以得到240根，更不能自动补造TDX开盘bar。

新增单股单日只读工具只在本机内存执行：
1. 使用已验证通达信二进制probe完整扫描与SHA256，
   必须真实存在240条结束标签，且二次取日内数据时源SHA一致。
2. 通过现有`query-parquet-primary-readonly.py`读取**当日单股**
   Parquet一分钟（最多242条）和五分钟（最多49条），
   禁止读取或写入本地付费缓存（`local_cache=False`）。
   预算`--max-candidate-rows`默认3500万、最多1亿候选源行，
   超出即拒绝，绝不静默关闭预算。
3. 严格要求Parquet`1min=241`的完整假设网格
   （09:30，再09:31—11:30/13:01—15:00），以及
   `5min=48`的开始标签（09:30—11:25、13:00—14:55）。
   缺键、重复、逆序、数据非法一律拒绝，不插值或补数据。
4. 第一组：TDX240根与Parquet的**240个共有结束时间键**逐根
   比较OHLC、volume、amount（240组），只输出匹配数量、
   最大/平均相对误差、量额倍率。
5. 第二组：Parquet每5根普通分钟聚合→五分钟（48组）；
   第三组：仅第一根五分钟中**包含额外09:30**时的聚合→
   五分钟（48组）。独立比较两种假说，不假定谁是官方真值。
   记录第一根五分钟两种方案的字段级匹配与差异，
   标记`regular_240_better_matches_5min`、
   `opening_inclusion_better_matches_5min`、
   `both_hypotheses_match_within_tolerance`或
   `neither_hypothesis_fully_matches_5min`。
6. 额外诊断09:30记录的成交量、成交额是否为0、其开盘价是否
   与第一条正常分钟的开盘价一致、合并后第一根五分钟哪些
   字段发生变化；**只输出布尔值与误差/比例，不保存原始值**。
7. Parquet每次读取前后核对来源清单大小/修改时间，
   两轮查询完成后再次复验；记录只提供**stat-only**来源指纹，
   不是来源内容认证。TDX保留全文件内容SHA256。
8. 仅创建新`H5ParquetReconciler/reports/`安全JSON，
   不输出原始OHLCVA/单条时间标签/源绝对路径。
   不写源文件、不写`work/`，也**不更改TDX本机原件、购买
   Parquet、H5、任何正式查询或私有暂存指针**。
   `eligible_for_automatic_production_union`始终为`false`。

## Windows验收

在仓库根目录`D:\ChatGPT\AStockDataTools`执行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\audit-tdx-vs-parquet-1min-opening-readonly.py
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_tdx_vs_parquet_1min_opening_readonly.py" -v
```

如果合成测试通过，在同一**已证实有TDX和Parquet数据**日期运行：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-tdx-vs-parquet-1min-opening-readonly.py --parquet-root "D:\stock" --tdx-1min-file "D:\software\TDX\vipdoc\sh\minline\sh600000.lc1" --symbol SH600000 --date 2026-09-30 --read-only --out "reports\tdx-vs-pq-sh600000-20260930-1min-opening-audit.json"
```

结果只上传`reports/`中的安全JSON或完整本地错误文本；
**不要上传通达信原始二进制、付费Parquet或含真实OHLCVA的缓存**。
如提示源行预算不足，不要无限增大；根据真实source RowGroup
上界评估是否要进一步优化索引。若是`1min`少于241/不是
`09:30+240`，该工具会失败封闭，不能假称已证实该时间策略。

之后运行模块全测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

## 后续

本轮新增8项纯合成测试，包括240共同键匹配、09:30零量
二义性、09:30非零贡献、100倍量单位诊断、分钟缺失/重复、
错误五分钟网格、坏源OHLC、来源清单变更、报告隐私与拒绝覆盖。
**尚未收到用户本机合成/真实241记录测试结果**，不要把源时间
策略和量额口径提前认证。

当真实1min报告可用，再据此确定是否存在可复现、可审计、
保留09:30原始来源的明确标准化规则；之后再进行多日多股票
小范围复测，最后才允许用户显式批准的隔离暂存与回滚演练。
