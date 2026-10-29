# 2026-10-29：从合成格式验收转向真实 Parquet 物理量纲的脱敏证据要求

## 已经完成：不再重复合成H5试验

用户 Windows 实测：

- Hikyuu 2.8.1 `core311` 单独导入和原生 `Stock.get_kdata` 已经正常工作。
- `synthetic-parquet-h5-decimal-gate-v1.json`：程序内部生成6条完全虚构 Decimal Parquet → Hikyuu 40字节复合 H5，全部与原生读取过的旧合成 H5 整数一致；相关测试13/13全部OK。
- `synthetic-decimal-h5-native-reread-v1.json`：新的两份**转换产出的**虚构 H5 再由真实 Hikyuu 原生驱动读取，`SH600000=3`、`SZ000001=3`，`new_native_h5_read_status=native_h5_six_synthetic_rows_matched`，`new_generated_h5_native_driver_certified=true`。对应9项离线测试全部OK。上传的日志粘贴了两遍，但复用同一`run001`及同名SAFE实际上不能进行第二次独立运行；记录为**一轮成功**即可。

**本结论只适用于完全合成数据。** 用户报告也明确 `licensed_parquet_units_verified=false`、`licensed_parquet_to_h5_mapping_certified=false`、`ready_for_full_market_mirror=false`。因此**禁止开始商业Parquet → 正式Hikyuu H5镜像写入**。

## 本轮新增只读的报告审核工具

`tools/audit-sanitized-parquet-h5-unit-evidence.py`

这是一个**不读取任何行情源**的脱敏JSON材料审核器：只准接受模块 `reports/` 目录中已经存在、经过人工或其他只读流程脱敏的证据JSON，不接受商业Parquet路径、真实H5路径、stock.db路径、原始逐行报价或行情文件。它仅生成新的`reports/<NEW>.json`安全审核结果，不能让实际源文件被修改。

**不要把这个工具等同于真实Parquet数据扫描器。** 本轮不写这样的扫描器，也不执行任何实际行情文件访问。真实物理单位核验必须依赖以后用户提供的、另行批准的真实只读配对证据与来源文档。

### 当前最小证据内容

针对相同的2只证券（按历史合成试点名称`SH600000`、`SZ000001`）和至少两个**实际有交易的交易日**，优先跨两段日期窗口（例如你先前已经做过的2026-08/09采样），整理三种周期`day/5min/1min`的：

- 数据类型：时间戳Arrow逻辑类型与时区、价格列类型、成交额列类型、成交量列类型；类型未知请填`unknown`，禁止猜测。
- 每一证券-日期的行数：`day_rows`、`min5_rows`、`min1_rows`；是否完整收盘、分钟时间网格是否已验证、复权口径是否一致。禁止用`239`或`48`作为任何交易日普遍必然的行数。
- 同一证券、同一交易日、同一复权/覆盖口径下，日线金额与5分钟/1分钟金额**未归一化、同单位前提**下的相对差异；成交量同样两组差异。四项用**Decimal字符串**写，例如`"0.000002"`，不写原始成交额、成交量或任何OHLC值。
- 可信来源文件文档是否明确说明`amount`是元/万元等、`volume`是股/手等。没有就填`"unknown"`；即便文档自称明确，也不能仅凭文字、单个聚合比例或合成数值做自动认证。

工具**不接受字段自由扩展**，避免无意提交用户真实行情、私有路径或文件名。输入格式精确如下（下例完全**虚构**，不得当作真实核验依据）：

```json
{
  "format": "AStockDataTools sanitized Parquet H5 unit-evidence intake v1",
  "sanitized_aggregates_only": true,
  "no_raw_market_rows": true,
  "independent_unit_reference": "none",
  "schemas": {
    "day": {
      "date_type": "timestamp_ns",
      "price_type": "decimal128",
      "amount_type": "decimal128",
      "volume_type": "int64",
      "timezone": "Asia/Shanghai",
      "amount_unit_declared": "unknown",
      "volume_unit_declared": "unknown"
    },
    "5min": {
      "date_type": "timestamp_ns",
      "price_type": "decimal128",
      "amount_type": "decimal128",
      "volume_type": "int64",
      "timezone": "Asia/Shanghai",
      "amount_unit_declared": "unknown",
      "volume_unit_declared": "unknown"
    },
    "1min": {
      "date_type": "timestamp_ns",
      "price_type": "decimal128",
      "amount_type": "decimal128",
      "volume_type": "int64",
      "timezone": "Asia/Shanghai",
      "amount_unit_declared": "unknown",
      "volume_unit_declared": "unknown"
    }
  },
  "windows": [
    {
      "symbol": "SH600000",
      "date": "2026-08-17",
      "day_rows": 1,
      "min5_rows": 48,
      "min1_rows": 239,
      "closed_session": true,
      "time_grid_checked": true,
      "same_adjustment_basis": true,
      "day_vs_5min_amount_relative_gap": "0.000001",
      "day_vs_1min_amount_relative_gap": "0.000002",
      "day_vs_5min_volume_relative_gap": "0",
      "day_vs_1min_volume_relative_gap": "0"
    }
  ]
}
```

说明：示例`windows`只有一个窗口，**故意不能通过证据数量门槛**。实际输入必须为2只证券 × ≥2日期，共至少4个不重复窗口；真实聚合差异必须从已有可信只读核对报告取得，不得复制上面虚构值来冒充已核验数据。输入中的每种周期`schema`需要包含全部7项字段，只是前面示例的`schemas`已示范。

### 运行方式

1. 使用已经存在的只读 H5/Parquet 核对报告**人工整理**真正的聚合元数据，不要直接上传任何 H5、Parquet 或股票逐行数据。将符合上述格式的文件放在模块目录`H5ParquetReconciler/reports/sanitized-parquet-h5-unit-evidence-v1.json`。如果目前没有足够事实材料，不要编造数据或运行伪造的报告。
2. 先运行新增**11项离线测试（待用户Windows实测）**：

```powershell
git pull --ff-only origin main
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_audit_sanitized_parquet_h5_unit_evidence.py" -v
```

3. **仅在已有真实脱敏证据JSON时**运行审核器：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\audit-sanitized-parquet-h5-unit-evidence.py --sanitized-report "H5ParquetReconciler\\reports\\sanitized-parquet-h5-unit-evidence-v1.json" --out "H5ParquetReconciler\\reports\\parquet-h5-unit-evidence-assessment-v1.json" --offline-evidence-only
```

报告中`ready_to_plan_independent_unit_check=true`**只说明证据覆盖较充分，值得继续制定真实只读验证计划**；`amount_physical_unit_certified=false`、`volume_physical_unit_certified=false`、`licensed_parquet_to_h5_mapping_certified=false`、`ready_for_full_market_mirror=false`始终为false。

### 必须避免的错误结论

- Hikyuu存储的`openPrice`等整数和`transAmount`等的解码比例，是**Hikyuu自有存储协议**，不能直接推断购买Parquet存放的真实物理单位。
- 跨周期金额/数量聚合一致，并不能独立证明成交量是“手”还是“股”；如果同一数据源三周期同样使用错误/不明的比例，仍会互相匹配。
- 只读文件元数据/Schema 也通常**无法独立证明**某一数值列是“元”还是“万元”。后续要取得购买数据供应商字段定义、经独立验证的H5/交易所基准或可追溯的配对窗口，再进行保守的倍率推断，且须排除复权、时间网格、不同来源覆盖问题。
- 此工具**不会**实际进行上述真实数值扫描，也不会批准任何写入正式镜像。
