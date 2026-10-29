# 2026-10-29 | 将已完成的 Parquet 三周期历史核对 JSON 转成脱敏单位审核材料

## 当前已验证

- 原生合成Parquet → H5 → Hikyuu 2.8.1 C++ 二次读取：2只虚构证券、6条K线全部一致，无需再重复同一金丝雀实验。
- 脱敏字段与聚合证据审核脚本`audit-sanitized-parquet-h5-unit-evidence.py`：用户 Windows **11/11离线测试通过（0.192秒）**。
- 用户历史已生成的真实**只读聚合报告**（此前用户上传过）：
  - `pq-day-vs-minute-2026-08-24.json`：包括SH600000、SZ000001、SZ300750；其中前两股各有日线、5分钟48条、1分钟241条；报告中记录严格OHLC一致、分钟时间网格缺口0、两个周期的金额/数量汇总比例与容差判断。
  - `pq-day-vs-minute-2026-09-30.json`：SH600000、SZ000001的三周期同口径汇总；每股5分钟48条、1分钟241条，存在极小的金额比值偏差。
- 两个历史报告的`relative_ratio_day_over_intraday`是**已有程序写出的十进制可视表示**，不是原始高精度成交额数值。跨周期比例接近1，但依然**不能证明股/手、元/万元物理单位**，也不能确认独立的复权口径和具体Arrow时间戳物理Schema。

## 新增工具

`tools/derive-sanitized-unit-evidence-from-existing-three-period-reports.py`

严格只接收已经存在的、直接位于`H5ParquetReconciler/reports/`目录中的`AStockDataTools Parquet three-period full-day conservation v1` JSON报告。不会导入pyarrow/hikyuu/h5py，也不会访问、修改或转储购买Parquet、H5、SQLite、股票行情行或原始绝对路径。

- 只提取`SH600000`与`SZ000001`，且恰好两份**不同日期**的旧报告：构成4个stock-date窗口。避免本阶段把不同股票混合统计。
- 只用原报告的已核对日期数量、分钟网格完整性、逐字段OHLC一致标记、日与5分钟/1分钟的金额/成交量**汇总比值**；基于`Decimal`将`|day/intraday - 1|`转换成脱敏相对差字符串，不从历史报告已经被四舍五入的数值推断新的精度。
- 每周期的原始Arrow字段类型、时区、价格数据类型、成交额物理单位、成交量物理单位统统为`unknown`：**历史报告只说明`parquet_schema_checked=true`，不等于提供了具体的字段类型/单位**。
- 即使报告`day_bar_present=true`且分钟网格齐全，仍不把`closed_session`和`same_adjustment_basis`设置为True，因为旧报告没有独立证明。该限制会导致审核结果`ready_to_plan_independent_unit_check=false`；这是正确的失败关闭结论。
- 在新文件`sanitized-parquet-h5-unit-evidence-from-existing-v1.json`中仅保留允许的字段类型/布尔/小数差/固定两个股票代码与两个日期；另一新文件`parquet-h5-unit-evidence-from-existing-assessment-v1.json`只保留审核状态、窗口数量与缺失证据原因码，不保存原始报告内容。
- 这两个报告都生成在模块`reports/`目录，不覆盖输入或已有结果，保留真实历史原报告以便溯源。不启用任何真实Parquet→正式H5转换。

### Windows验收步骤

1. 从仓库根目录拉取主分支并运行新工具的**8项离线测试**（需用户实测）：

```powershell
git pull --ff-only origin main
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_derive_sanitized_unit_evidence_from_existing_three_period_reports.py" -v
```

2. 检查你本地是否仍有之前的两份历史核对报告：

```powershell
Test-Path "H5ParquetReconciler\\reports\\pq-day-vs-minute-2026-08-24.json"
Test-Path "H5ParquetReconciler\\reports\\pq-day-vs-minute-2026-09-30.json"
```

如果显示两个`True`，直接运行（**不要**重新扫描几百MB/GB的原始Parquet）：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\derive-sanitized-unit-evidence-from-existing-three-period-reports.py --existing-report-a "H5ParquetReconciler\\reports\\pq-day-vs-minute-2026-08-24.json" --existing-report-b "H5ParquetReconciler\\reports\\pq-day-vs-minute-2026-09-30.json" --sanitized-out "H5ParquetReconciler\\reports\\sanitized-parquet-h5-unit-evidence-from-existing-v1.json" --assessment-out "H5ParquetReconciler\\reports\\parquet-h5-unit-evidence-from-existing-assessment-v1.json" --offline-existing-reports-only
```

若报告未存于模块目录，不要移动源行情文件或直接读取它们；请先核对这两份既有JSON具体存放位置并复制**仅这两份经脱敏的报告文件**到该模块`reports/`。旧报告文件如已存在于目标路径，禁止覆盖。若新输出名已存在，改用全新`v2`后缀。

### 合理的运行结果

预期两股×两个日期，共4个窗口；四组数字比例都应很接近1。但`schema`、时区、真实单位、`closed_session`和复权口径在历史材料中并没有明确证明，因此**预计**
`ready_to_plan_independent_unit_check=false`、
`amount_physical_unit_certified=false`、
`volume_physical_unit_certified=false`、
`licensed_parquet_to_h5_mapping_certified=false`、
`ready_for_full_market_mirror=false`。

这些字段为false**不是程序失败，而是正确标出真正缺少的证据**。后续重点应在现有真实只读源的**字段Schema/时区**与独立供应商口径文档，或经独立核对的H5单位基准，而非再次生成完全虚构的行情样本。

用户只需提交新`assessment-v1.json`及8项测试摘要；如需进一步深挖，脱敏的`sanitized-v1.json`也可上传。无需上传原H5、商业Parquet、完整行情条目或任何真实源文件路径。
