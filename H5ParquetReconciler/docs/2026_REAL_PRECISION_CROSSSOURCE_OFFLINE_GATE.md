# 2026-10-29：真实float64精度与既有TDX/H5跨源证据的离线决策门禁

## 本轮已确认的事实

- 用户Windows真实`test_audit_real_parquet_day_float64_h5_tick_candidates.py` **12/12项全部OK（10.332秒）**；实机日线月文件2026-09的两个row group、118208条源记录被读取，仅保留2026-09-30的SH600000、SZ000001共2条目标日线，未打开/修改任何H5或正式库。
- 新用户SAFE `parquet-day-float64-h5-tick-candidates-20260930-v1.json`：OHLC四字段各**2/2**满足`Decimal(str(float))×1000`整数量化，但四字段各**0/2**满足原始binary64严格整数刻度；amount与volume分别**2/2**短十进制刻度及binary64严格整数刻度（针对候选假设比例），两根样本的12字段没有最短十进制必须舍入或溢出。**这不是供应商原始十进制恢复，也不能自动建立真实H5单位。**
- 以前已经做过、可复用的真实只读TDX/Parquet 2026-09-30 `tdx-vs-pq-sh600000-20260930-day5min.json`：仅SH600000，当天TDX与购买Parquet的48个5min区间六字段**48/48落既有容差**，日线1/1六字段在既有容差；**明确h5_accessed=false**，并不是Hikyuu H5比较，供应商单位未独立验证。
- 此前H5/Parquet 2026-09-28 `h5-parquet-5min-x100-2026-09-28-top3-sessions.json`：SH688629、SH688017、SH688172各48个5min对齐，共**144个比较键、95个候选任意字段冲突**。H5成交量×100仅是本次诊断候选；即使聚合总量几乎抵消，也不代表逐根完全一致。**此结果与9月30日的两股精度实验是不同股票和日期，不得按同一根K线合并。**

## 新增程序

`tools/audit-real-precision-crosssource-evidence-offline.py`

严格从`H5ParquetReconciler/reports/`目录读取 **3个之前已生成的SAFE JSON报告**，不会打开原始Parquet、TDX、Hikyuu H5、stock.db、其他SQLite，不会新查任何真实行情、不会写入任何行情记录。输入文件必须存在且不超过200KiB，不接受符号链接、模块外路径，输出是该模块reports下新的不可覆盖JSON。

对这三份报告的`format`、日期、样本股票、各字段匹配计数、报告只读/未认证标记进行严格校验；只提取**固定Schema**的量化数量、TDX/Parquet同一证券日48/48六字段容差匹配、H5/Parquet另外三证券日144个中95个候选冲突、两数据源日期分离及三份输入的SHA256。额外原始行情字段即使出现在报告中，也不会原样复制到产物；精度字段结构的多余字段会拒绝。

所有全局认证旗标**恒为false**：`physical_amount_unit_certified`、`physical_volume_unit_certified`、`real_float64_to_native_h5_precision_mapping_certified`、`h5_parquet_universal_volume_factor_100_certified`、`licensed_parquet_to_h5_mapping_certified`、`ready_for_full_market_mirror`。

**这并不是否定此前数据工作**。其作用是阻止把“最短十进制2/2恰好无舍入”、“TDX/Parquet单股单日48/48落容差”与“H5/Parquet 144中有95个残差”误拼成“全市场H5镜像转换单位已证实”。

## Windows命令：每个PowerShell代码块均为单行

更新main：

```powershell
git pull --ff-only origin main
```

新增加的10项**不读取任何市场文件的虚构SAFE单测**：

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_audit_real_precision_crosssource_evidence_offline.py" -v
```

预期10项全通过但**尚未由用户Windows实测**。

先分别核实之前的三份报告**已经存在于本机模块reports目录**，避免无必要地重新采集市场数据：

```powershell
Test-Path "H5ParquetReconciler\\reports\\parquet-day-float64-h5-tick-candidates-20260930-v1.json"
```

```powershell
Test-Path "H5ParquetReconciler\\reports\\tdx-vs-pq-sh600000-20260930-day5min.json"
```

```powershell
Test-Path "H5ParquetReconciler\\reports\\h5-parquet-5min-x100-2026-09-28-top3-sessions.json"
```

**只有三项全部True**，才执行下面的纯离线JSON汇总：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\audit-real-precision-crosssource-evidence-offline.py --real-day-precision-safe "H5ParquetReconciler\\reports\\parquet-day-float64-h5-tick-candidates-20260930-v1.json" --tdx-parquet-safe "H5ParquetReconciler\\reports\\tdx-vs-pq-sh600000-20260930-day5min.json" --h5-parquet-safe "H5ParquetReconciler\\reports\\h5-parquet-5min-x100-2026-09-28-top3-sessions.json" --out "H5ParquetReconciler\\reports\\real-precision-crosssource-evidence-bridge-v1.json" --offline-reports-only
```

如果后两份以前的JSON当前**不在reports目录**，请只把相应**已脱敏JSON报告**复制到模块reports目录（先确保不存在同名旧文件），**不要为补报告重新运行Parquet五分钟数百万行扫描**。原始三方数据文件不能上传GitHub。若新输出已存在，请改用`v2`等新文件名；不要覆盖旧报告。除上述两份SAFE报告外没有必要提供用户本地绝对数据源路径。

## 后续优先级

1. 先获取**商业Parquet数据供应商字段单位说明/数据字典**（成交量究竟股/手、成交额元/万元、复权和时间标签规则）；这类独立书面说明不能从Arrow Schema推断。
2. 确定Hikyuu原始H5解码单位，并通过已存在的只读H5/TDX报告作单证券、同日、同周期**按两源相同基准单位的配对验证**。确认不同阶段是否一致，避免统一×100猜想。
3. 数值转换策略要明确`str(float)`是否符合供应商真实精度、舍入模式、half-tick和整数溢出处理，再考虑仅在隔离目录的暂存转换；正式H5镜像始终关闭。

**勿将本工具的证据决策SAFE误解为实际完成供应商单位认证或全市场转换许可。**
