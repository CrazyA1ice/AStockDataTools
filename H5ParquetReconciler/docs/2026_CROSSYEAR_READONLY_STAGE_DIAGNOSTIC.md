# 2026-10-30：2025年度日线跨年实测未能执行——只读安全诊断

## 用户Windows实际反馈（事实，不应推断）

- 已确认修复后的2025年度及2026月度合成回归：`Ran 18 tests in 3.810s, OK`。先前2025年1月重复记录的测试误报已修复，目标日跨行组重复键已通过合成拒绝测试。
- 真实`D:\\stock\\AllCycleAStockData\\day\\2025.parquet`与`day\\2026-08.parquet`均存在；目标SAFE`real-h5-parquet-crossyear-day-factors-20250930-20260824-v1.json`不存在。
- 原只读跨年工具的真实运行再次输出统一安全拒绝：`Cross-year sampled real H5/Parquet verification refused; sources or SAFE incomplete`。**没有成功的跨年报告、没有已验证的跨年4/4倍率结果。** 不能仅凭这一句判定年度行组过大、H5历史缺失、SAFE失败、字段类型不符或跨源倍率不一致。
- 原始2025 Parquet年度文件据先前用户Footer清单为**1,333,385行、12个行组**；2026-08月度文件**117,969行、2组**。这份旧清单只证明文件Footer当时记录的总范围，并**没有**给出2025-09-30当天究竟命中多少个行组；不能据此调高原有15万行读预算。

## 本轮新增工具与隐私约束

`tools/diagnose-real-h5-parquet-crossyear-readonly.py`，与此前跨年主工具**分开**，不修改主工具查询、行数和行组预算。诊断只接受与之前完全相同的三份历史SAFE和2025-09-30/2026-08-24两只指定股票，输出单独新文件至模块`reports/`。

- 先只审查先前2026-09-30 raw H5↔Parquet、同日真实native HMAC两股2/2与2026-09-28/29留出四条4/4的SAFE；任一链条无效会显示`last_stage=prior_safe_chain`，不会打开实际市场数据。
- 检查指定2025年度及2026-08月度源文件，两个真实H5日线源文件；文件缺失/不安全/不是本模块固定的源时只提供有限枚举阶段，不返回本机路径。
- **仅查看**年度文件Arrow schema、全部12个（实际以本地metadata为准）RowGroup的int64 `ts` min/max Footer与行数；统计与2025-09-30重叠的候选行组数和这些候选组行数。若候选行组>2，报告`last_stage=annual_target_rowgroup_selection`；若候选组行数>150000，报告`last_stage=annual_target_row_budget`，**不读取这些数据行**。若缺任一Footer最小/最大时间，报告`annual_footer_timestamp_statistics`。
- 只有元数据满足现有门禁才按原有工具的相同受限读取路径实际读取指定两股票日。若年度Parquet目标读取出错，报告`annual_bounded_day_read`；若原始H5缺历史目标日，报告`annual_target_original_h5_read`；若2026月度Parquet或H5失败，分别是`monthly_bounded_day_read`、`monthly_target_original_h5_read`。不会扫全年度或跳过失败项。
- 即使诊断在内存中能进行四条样本的候选比对，诊断SAFE也**不输出或认证**价量额/倍率匹配数，只输出`status=ready_to_rerun_original_proof`，需要再次执行原跨年主工具生成正式的脱敏候选计数SAFE。
- 文件stat/Parquet Footer前后核查；不输出任一源文件绝对路径、证券代码、用户数据OHLCVA、原始整数或时间戳、HMAC或异常原文；只输出预定义枚举阶段、元数据行数/行组数及布尔状态。不得据诊断结果自动修改源文件、调高年度预算、生成H5或启动全市场镜像。源文件并未做全内容SHA256，不可据此声称字节级不可变。
- 7项新合成Parquet/H5测试验证成功阶段、历史SAFE伪造、源缺失、Footer统计缺失、候选行预算超限、跨行组重复日线失败阶段及输出文件禁止覆盖。**待用户Windows运行**，不预先宣布测试通过。

## 用户Windows命令——每块一条单行PowerShell

更新：

```powershell
git pull --ff-only origin main
```

运行**7项新合成诊断回归**：

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_diagnose_real_h5_parquet_crossyear_readonly.py" -v
```

先确认新诊断报告不存在：

```powershell
Test-Path "H5ParquetReconciler\\reports\\real-h5-parquet-crossyear-2025-2026-diagnostic-v1.json"
```

输出必须是`False`。只有7项测试全部OK且新文件路径未占用，才运行一次诊断：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\diagnose-real-h5-parquet-crossyear-readonly.py --parquet-root "D:\\stock\\AllCycleAStockData" --h5-root "D:\\stock\\HikyuuData" --prior-raw-safe "H5ParquetReconciler\\reports\\real-parquet-h5-raw-day-unit-factor-candidates-20260930-v1.json" --prior-native-safe "H5ParquetReconciler\\reports\\real-hikyuu-native-20260930-hmac-v3.json" --prior-heldout-safe "H5ParquetReconciler\\reports\\real-h5-parquet-heldout-day-factors-20260928-29-v1.json" --out "H5ParquetReconciler\\reports\\real-h5-parquet-crossyear-2025-2026-diagnostic-v1.json" --diagnose-read-only-crossyear
```

分享`reports/real-h5-parquet-crossyear-2025-2026-diagnostic-v1.json`和7项测试日志即可，**不能上传原始Parquet或H5**。诊断SAFE即使`status=blocked`也会生成；切勿因诊断被阻断而直接运行一条取消预算的命令。

## 如何决定后续动作

- `prior_safe_chain`：重新核对三份脱敏SAFE内部必要字段及hash链，不补造真实成功证据。
- `annual_target_rowgroup_selection`或`annual_target_row_budget`：针对真实2025年度Footer实测的行组覆盖模式讨论是否设计新的**只读**更精确范围访问；没有实际证据前不扩大年度读数。
- `annual_bounded_day_read`：核对合成测试未覆盖的真实年度schema/key/日期行为；先保持读取上限。
- `annual_target_original_h5_read`：再核查真实H5历史目标日覆盖情况，不能将文件存在误当股票-日期存在。
- `monthly_bounded_day_read`或`monthly_target_original_h5_read`：聚焦2026-08，避免重复排查已通过的2025年度阶段。
- `ready_to_rerun_original_proof`：代表两固定日期的只读读取及聚合逻辑通过阶段核查，下一步仍需正式主工具产生计数结果；**不代表供应商单位或格式互转已认证**。
