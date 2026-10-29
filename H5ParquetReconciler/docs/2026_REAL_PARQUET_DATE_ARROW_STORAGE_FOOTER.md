# 2026-10-29 | 三周期 Parquet 日期列存储类型与 float64 数值安全诊断（仅Footer）

## 依据：用户Windows已完成的真实只读验收

- 新12项测试：`Ran 12 tests in 5.965s / OK (skipped=1)`，唯一跳过项是 Windows 本机缺少创建符号链接权限；**小型合成PyArrow Parquet Footer真实集成测试已实际通过**。符号链接拒绝逻辑存在，但该子测试并未在此环境执行，不应算12/12全部实测。
- 用户已确认三份购买Parquet的2026-09文件存在，并成功对3份文件执行`probe-parquet-arrow-footer-schema-readonly.py`，SAFE `parquet-3period-arrow-schema-footer-v1.json`显示三周期每种OHLC价格、金额、数量角色全部为 **float64**，日期角色已识别但`date_type=unknown`、`timezone=unknown`、额/量物理单位均`unknown`，无源码行数据读取或生产数据修改。
- 三文件footer计数（仅2026年9月）：日线2个row group、118208行；5分钟47组、5685792行；1分钟233组、28547414行。另一个SAFE `parquet-h5-unit-evidence-with-footer-assessment-v1.json`确认4个旧股票日期窗口的金额/量跨周期聚合相对差均低，但独立的闭市/复权口径、日期编码及物理单位仍未证明，正式H5写入门禁依旧关闭。

## 本轮修复：为何日期字段已识别但日期类型仍显示 unknown

**`recognized_alias_presence.date=true`只证明有一个叫datetime/timestamp/date等的字段，不能证明该列Arrow类型是timestamp或date32**。它也可能是字符串、int64或其它存储。先前审核器的`date_type`只能接受已标注Calendar/Timezone的类型；原脚本为保证不误推断`YYYYMMDD`、北京时间等语义，对string/int等类型正确返回unknown，但无法区分“字段缺失”和“字段存在但编码不明”。

本轮在**同一只读Footer工具**中追加白名单型安全诊断：

- `date_role_match_status`：`matched`/`missing`/`ambiguous`，分别表示恰好找到一个日期别名字段、无字段、同时找到多个可能别名。
- `date_arrow_storage_family`：仅由Arrow dtype判断，允许固定枚举如`utf8`、`large_utf8`、`int32`、`int64`、`float64`、`date32`、`timestamp_us`等，遇到不支持的Arrow类型标`unsupported`。**不回传任何原始列名、列值、自由文本metadata或日期内容。**
- `date_raw_calendar_encoding_certified=false`：仅据字符串/整数Arrow dtype无法认证它存的是YYYYMMDD、Unix秒/毫秒，还是特殊来源编码。此布尔值始终false。
- `date_time_label_semantics_certified=false`：即使Arrow标注timestamp，也无法从Footer证明购买分钟线是开盘标签、收盘标签还是其它规范，始终false。
- `numeric_binary_float_roles`：由Arrow Schema识别`open`、`high`、`low`、`close`、`amount`、`volume`中哪些角色采用float32或float64，只列出固定角色名称，不输出数据值。前一份真实2026-09报告预计列出全部六个。
- `binary_float_to_native_h5_precision_certified=false`：二进制浮点的十进制量化/精度损失尚没有经过真实数值样本的独立核验，禁止默许舍入，始终false。

其余路径边界和Parquet FOOTER预算（≤16MiB），3文件明确选择、文件不发生size/mtime变化、`ParquetFile.schema_arrow`、`ParquetFile.metadata`、`close()`、报告固定白名单不输出用户私有路径保持不变。脚本报告format升级为v2，原先的3份v1 SAFE应完整保留，不覆盖。

## Windows测试命令（**所有PowerShell指令各自一整行，不使用反引号换行**）

在仓库根目录：

```powershell
git pull --ff-only origin main
```

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_probe_parquet_arrow_footer_schema_readonly.py" -v
```

预期由原先12项增加5项到**17项**；Windows旧符号链接子测试仍可能显示`skipped=1`，但**重要的实际合成Parquet Footer集成测试必须为ok**。这是预期，Windows运行结果尚未取得。

设置本机真实购买Parquet根目录：在当前PowerShell会话中自行替换以下示例，**不要把私有根目录提交公开仓库**：

```powershell
$ParquetRoot = "D:\\YOUR_PRIVATE_PARQUET_DATA\\AllCycleAStockData"
```

依次确认三份Parquet存在：

```powershell
Test-Path "$ParquetRoot\\day\\2026-09.parquet"
```

```powershell
Test-Path "$ParquetRoot\\5min\\2026-09.parquet"
```

```powershell
Test-Path "$ParquetRoot\\1min\\2026-09.parquet"
```

三项都返回True后，仅执行一次**3份既有真实Parquet Footer的只读检查**，不读取行情记录：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\probe-parquet-arrow-footer-schema-readonly.py --source-root "$ParquetRoot" --day-relative "day/2026-09.parquet" --min5-relative "5min/2026-09.parquet" --min1-relative "1min/2026-09.parquet" --existing-sanitized "H5ParquetReconciler\\reports\\sanitized-parquet-h5-unit-evidence-from-existing-v1.json" --schema-out "H5ParquetReconciler\\reports\\parquet-3period-arrow-schema-footer-v2.json" --enriched-out "H5ParquetReconciler\\reports\\sanitized-parquet-h5-with-real-footer-schema-v2.json" --assessment-out "H5ParquetReconciler\\reports\\parquet-h5-unit-evidence-with-footer-assessment-v2.json" --footer-metadata-only
```

新v2 SAFE中检查每周期的`date_arrow_storage_family`（重点）、`date_role_match_status`及`numeric_binary_float_roles`，将v2的**Schema SAFE**和**assessment SAFE**上传用于下一轮分析；无需上传原始Parquet/H5/stock.db，也无需泄露真实源码或私人目录。

如v2文件已存在，三项输出统一改v3以防覆盖。**schema知道日期存储族不等于知道时间标签和单位语义**。如果实际是字符串/整数日期，下一轮应先阅读供应商的数据字典或已有时间标签核对代码，不能凭猜测直接将其解释为某个日历或Unix时间单位。
