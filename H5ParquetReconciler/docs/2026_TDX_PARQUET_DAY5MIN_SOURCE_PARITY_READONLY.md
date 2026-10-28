# 2026-10-28：真实通达信三周期守恒通过；对购买 Parquet 做单日/五分钟跨源安全核验

## 用户本机证据与本轮转向

用户上传的真实安全报告
`tdx-native-sh600000-three-period-20260930-audit.json`，对应
SH600000，2026-09-30：
- TDX日线1根、1分钟240根（`1min_end_240`）、5分钟48根
  （`5min_end_48`），3个原生文件经全文件SHA校验稳定。
- 1min聚合到5min：48组OHLC和成交量全部无差异，成交额最大
  相对误差`1.048e-07`，48/48在容差内。
- 5min、1min分别聚合到原生日线，6个字段均容差内。
  成交量日汇总与日线的比约`1.00000014`，没有100倍单位错位。
- **仅证实一只股票单个交易日的通达信内部周期关系**；
  不能据此宣布TDX全市场正确、已统一复权口径，或与购买
  Parquet/H5一致。报告明确`eligible_for_automatic_production_union=false`。

下一步必须进行独立来源**同日价量额对账**，而不是再扫描已证明
存在的键或把TDX源复制到生产数据目录。

## 新增`audit-tdx-vs-parquet-day5min-readonly.py`

只针对同股票/同一个北京自然日、原生通达信的day/1min/5min和
已购买的Parquet `day`/`5min`。不读取H5，也**刻意不读取
Parquet一分钟线**，因为该源可能含241根独立09:30开盘条；
TDX已证实为240根、分钟结束标签。不能以同时间戳逐条映射。

1. 真实本机TDX先调用已有`audit-tdx-native-three-period-readonly.py`
   **重新读取三份原生二进制**并核验完整来源、240/48/1时标、
   内部OHLCVA，获取内容SHA256与内部容差匹配状况；
   随后再次读取当天TDX day/5min并验证源内容SHA未变化。
2. 对购买Parquet调用现有`query-parquet-primary-readonly.py`
   的`query_bars`公开API，严格一天窗口、`local_cache=False`
   不生成或读取付费缓存。要求当天`day=1`，`5min=48`，
   且48个原始北京标签必须为**09:30—11:25、13:00—14:55区间起点**。
3. 比较时将每个Parquet 5分钟时间键转换成**区间结束分钟 = 原
   起点 + 5分钟**，只在**内存**中映射到TDX原生对应的结束标签；
   不改写或保存Parquet原始记录、不插值、不补齐0成交K线。
   任何不完整、午休时段错位或非48根的数据都会明确拒绝。
4. 检查3组关系：① TDX 5min vs Parquet 5min（48组）；②
   TDX 日线 vs Parquet 日线（1组）；③ Parquet内部48根5min聚合
   vs Parquet日线（1组）。每组比较开高低收、volume与amount，
   记录原`native._compare()`定义的字段容差内数量、最大/平均相对
   误差，以及量额的**Parquet/TDX**比例中位数（第三组为
   Parquet日线/Parquet5min聚合）。
5. Parquet源的来源清单只存**统计字段指纹**（相对路径、
   文件大小与修改时间参与SHA256，不包含内容SHA）；查询后逐条
   核对仍存在、没有超出合法Parquet源目录、大小/修改时间未变化，
   有任何变化即报错拒绝生成成功摘要。注意：统计指纹
   **不认证文件内容**，也不能证明供应商真实性。
6. 报告仅写到`H5ParquetReconciler/reports/`，不覆盖已有文件，
   不包括原始价格、成交量/额、单根K线、源绝对路径或单条时间键。
   输出本轮2类源的计数、全源TDX文件哈希、Parquet统计指纹、
   逐字段相对误差/量额倍率，注明内部TDX三周期是否全部在容差内；
   明确`eligible_for_automatic_production_union=false`。
7. **不能自动导入、合并、校正或改变主查询**；真实文件只读，
   Parquet本地缓存显式关闭，不改任何H5源或TDX原始二进制。
   默认每个Parquet周期的Footer候选源行上限为1500万，
   最高允许3000万；命中结果最多日线2条、5min49条，
   超过上限失败封闭。TDX每个文件最多64MiB且用户可降低。

## Windows本机验收

在`D:\ChatGPT\AStockDataTools`仓库根目录执行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\audit-tdx-vs-parquet-day5min-readonly.py
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_tdx_vs_parquet_day5min_readonly.py" -v
```

真实跨来源检查（**输入路径是用户已核实存在的原文件**，不需要上传
文件；Parquet的数据根目录依照此前的`D:\stock`）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-tdx-vs-parquet-day5min-readonly.py --parquet-root "D:\stock" --tdx-day-file "D:\software\TDX\vipdoc\sh\lday\sh600000.day" --tdx-5min-file "D:\software\TDX\vipdoc\sh\fzline\sh600000.lc5" --tdx-1min-file "D:\software\TDX\vipdoc\sh\minline\sh600000.lc1" --symbol SH600000 --date 2026-09-30 --read-only --out "reports\tdx-vs-pq-sh600000-20260930-day5min.json"
```

结果在模块`reports/`中的安全JSON。仍需运行全量合成回归：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

遇到`candidate source rows exceeds...`不能自动解除预算；
应收集本机低风险信息后调整有界策略，不能直接全库扫描。
如果报告同日数据不一致，应先分辨价格、volume、amount、
时标、复权和供应商更新截止日期。对于用户报告里可能的
100倍成交量差，**仅作为诊断不视为已认证的换算规则**。

## 未完成项目

- 本轮新增8项离线合成测试，需要用户Windows本机及完整测试
  回传结果；未直接读取用户私有Windows数据或购买Parquet，
  不能预先声称跨来源匹配或证明全市场一致。
- Parquet 1min **241条特殊开盘bar没有被读取或比较**，
  单独研究这一条的数值归属后才能设计明确的分钟级跨供应商映射。
- Parquet/H5缺口正式选择与私有TDX增量受控写入尚未完成，
  只有通过同日来源证据后才能讨论版本化、显式审批与回滚。
