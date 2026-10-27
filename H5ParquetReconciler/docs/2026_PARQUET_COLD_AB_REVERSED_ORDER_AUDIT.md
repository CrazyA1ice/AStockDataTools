# 2026-10-27：Arrow与RowGroup冷查询反序复核（只读、安全摘要）

## 目的与当前证据

此前真实的 `SH600000 / 2026-09-30 / 5min` 查询：RowGroup传统方式的首次查询耗时3.515286秒，已有私有缓存的重复查询耗时0.050318秒，约69.86倍加速。**这不是Arrow冷查询的速度结论**。新基准 `benchmark-parquet-arrow-filter-cold.py` 可在同一个本地数据源上比较两种读取引擎，分别执行`rowgroup-first`与`arrow-first`以初步观察执行顺序、OS页缓存的影响。

本轮加入源数据`source_stat_manifest_sha256`：基于输入范围内**全部候选年度文件的相对路径、文件长度和mtime_ns**计算SHA256，基准开始与结束各取一次，变化则不生成成功报告。它**不是Parquet文件内容SHA256，不检测保持stat不变的内容修改**，也不能证明操作系统缓存真正处于冷状态。

新增 `tools/compare-parquet-arrow-cold-ab.py`：只读取两个安全摘要JSON，**不打开任何付费原始行情、H5、SQLite、私有缓存或Parquet Footer**，不重新跑基准；严格验证相反顺序、同证券/周期/日期、逐次OHLCVA/时标/源文件+RowGroup等值判定为真、同源stat摘要、同候选行组预算、同基线源行与Arrow过滤后输出计数、正有限耗时，以及所有只读/隐私保护标志。发生任一异常，拒绝写比较报告。

工具的三个可能结论：

- `arrow_faster_in_both_orders`：两次单轮测试均观测到Arrow快，**不足以启用默认生产引擎**；应重复多组证券/日期/周期、隔离冷启动条件并测总耗时。
- `baseline_faster_in_both_orders`：两次均观测到既有RowGroup方式快，保留原引擎；不为了新技术替换原方案。
- `mixed_or_equal_order_sensitive`：结果混合或持平，数据不足，优先排除顺序/缓存干扰，不推广任何加速倍数。

报告只写聚合时长、源行预算、匹配数量和保守分类，不输出K线的开高低收、成交量或成交额；不会把Arrow过滤后输出48根错写为物理解码48行或只读48行。

## 2026-10-27 Windows实机回归修复

本机合成测试记录为`Ran 297 tests in 17.426s / FAILED (failures=5, errors=2)`。其中6项均由Arrow Fragment创建处遗漏显式文件系统触发（`cannot construct a FileSource from a path without a FileSystem`），并非证明真实数据不一致；另1项是测试断言期望了第二层预检上限错误，实际先命中第一层RowGroup上限一致性校验。

修复为`pyarrow.fs.LocalFileSystem()`，显式传入`ParquetFileFormat.make_fragment(str(path), filesystem=..., row_groups=[group])`，保留原有目标RowGroup、过滤条件、价量额对比、安全预算及只读行为。同时分别测试两层上限检查，并新增加带空格绝对路径的Arrow Fragment合成回归。**用户随后提供2026-10-27 Windows 全套测试日志：298 项测试、16.243 秒、最终 OK，先前失败的全部7项及新增带空格路径测试均通过。此为本地合成测试验收，不能替代真实购买 Parquet 的冷查询性能与来源一致性验证。**

已完成上述 298 项合成测试验收；**下一主线是只执行下面三个 Windows 命令**：按 RowGroup 优先、Arrow 优先跑两个只读真实 A/B，然后离线比较两个报告。请使用首次生成、尚不存在的报告文件名（工具拒绝覆盖）；如果之前试跑产生同名文件，改用末尾 `-v2.json` 并在第三个命令内同步改名。

真实 A/B 应分别核验 `matching_bar_count=48`、`query_output_all_values_times_and_source_provenance_identical=true`、两轮源 stat 指纹一致，以及时间方向；否则保留原正式 RowGroup 查询引擎，不许因合成测试 OK 就声称 Arrow 更快。

## Windows运行（仓库根目录）

先更新代码并运行合成单测：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

首次A/B，RowGroup优先：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\benchmark-parquet-arrow-filter-cold.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --order rowgroup-first --read-only --out "reports\pq-primary-cold-ab-SH600000-20260930-rowgroup-first.json"
```

第二次A/B，Arrow优先：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\benchmark-parquet-arrow-filter-cold.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --order arrow-first --read-only --out "reports\pq-primary-cold-ab-SH600000-20260930-arrow-first.json"
```

只读取以上两份`reports/`内的无OHLCVA摘要，生成第三份只读聚合验收报告：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\compare-parquet-arrow-cold-ab.py --rowgroup-first "reports\pq-primary-cold-ab-SH600000-20260930-rowgroup-first.json" --arrow-first "reports\pq-primary-cold-ab-SH600000-20260930-arrow-first.json" --out "reports\pq-primary-cold-ab-SH600000-20260930-reversed-audit.json" --read-only
```

**请只分享三个`reports/`摘要JSON，勿上传`work/`私有行情缓存、Parquet、H5或任何原始OHLCVA。** 所有输出留在`H5ParquetReconciler/reports/`；不能覆盖既有报告，重复运行先换新文件名。全程默认查询引擎不变，2025年V3五分钟主索引保持只读和未完成状态。

## 验收限制与测试

本轮新增纯合成`tests/test_compare_parquet_arrow_cold_ab.py`，以及对原A/B测试的源元信息变化保护，涵盖顺序反转、数据源stat不一致、数量不守恒、缺失安全标志、NaN/无效计时、路径逃逸与已有文件拒绝覆盖。**Windows 用户本机完整结果：`Ran 298 tests in 16.243s`、`OK`，全部已通过。** 无任何付费行情文件进入测试记录；真实 Arrow/RowGroup 冷查询双顺序的性能结论尚待实测，不能提前认证。

即便stat清单完全相同，两轮仍可能受OS页缓存、内存页面、后台任务、PyArrow版本等干扰；第三份审计JSON的分类只是**方向性观察**。Arrow实测若持续显著较快，下一步再做正式引擎的受控可选化；若未证明收益，则继续构建原始数据只读前提下的定位/分区索引，切勿直接改写购买源数据。
