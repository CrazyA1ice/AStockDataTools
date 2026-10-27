# 2026年五分钟Parquet定向访问：只读Footer扫描成本预检与完整V3索引接入

更新：2026-10-27。用户Windows本机**180项测试全部通过**（6.256秒），2026-09-28的H5 1min到5min单日三证券144/144内部一致已确认。研发重点从反复复测行情转为**降低对Parquet大行组重复解码**。

## 1. 已测量的瓶颈及不能误解的结论

此前`analyze-5min-x100-focused-sessions.py`只请求SH688629、SH688017、SH688172三只股票在2026-09-28的一日5min数据：
- Parquet原始年度文件9个，407个RowGroup。
- 360个RowGroup被时间区间跳过，余下47个被解码；由于RowGroup内部包含大量股票，**底层共解码5,685,792条源行，最终仅选中144根股票K线**。
- H5与PQ之间95根有候选量价残余；H5 1min以**结束标签**重聚合至5min，144/144根OHLC、额及候选量一致。这支持不同供应商五分钟切分/边界解释的研究假说，仍未证明某源错误。

仅用RowGroup `symbol` 元数据`min/max`，遇到混排股票时可能无法进一步剪枝。即使已有`allowed_groups`接口，旧聚焦诊断也**没有主动接入完整V3覆盖索引**。现有用户2025年的V3索引即使存在，也**不能用于2026年Parquet源文件**，而且不完整V3索引不可用于安全跳读。

## 2. 新增功能和安全门槛

扩展`tools/analyze-5min-x100-focused-sessions.py`，在原命令中增加：
- `--plan-only`：从此前完整单日精确mask JSON自动选择top3股票。此模式**不加载H5市场K线、不迭代Parquet数据行**，仅读2026年9个Parquet文件的Footer/RowGroup元数据，按**运行时相同的过滤顺序**（若有完整索引先剪枝；再日期时间最小/最大值；再证券代码别名min/max）输出可证明的候选组数及行数、元数据缺失时的保守候选数、各文件统计。RowGroup没有可靠证券元数据时**绝不跳过**。输出`candidate_source_rows_upper_bound`代表待解码rowgroup总行数，**不是**用户选中股票144条K线的条数，也不等于实际运行耗时。
- `--coverage-index "work/indexes/pq-5min-2026-a-share-candidate-v3.sqlite"`：仅可在**完成且来源指纹匹配**的2026年度V3键索引存在时使用。**直接复用**既有`plan-5min-readonly-union.py:validated_parquet_locator`的源Manifest/版本/完成状态/RowGroup checkpoint/不正常时间键安全校验。仅验证通过后，将`allowed_groups`传入既有`diagnose.load_parquet`以跳过不含目标证券/日期的行组；不通过就拒绝，不允许自动降级为“信任部分索引”。
- 默认不传索引、不传`--plan-only`仍然沿用**此前经过真实报告核对**的原始Parquet加载及候选8mask校验路径，向后兼容。若使用完整索引进行实际诊断，其8种量价冲突分类仍需与母报告逐只股票一致，否则失败。
- 报告只包含Footer计数、股票代码、日期和安全标志；不包含任何付费OHLCV，不修改H5/PQ原文件，仍`unit_mapping_certified=false`、`safe_to_automatically_union=false`；不会自动创建年度索引，不会自动跑全年扫描。
- 新增`tests/test_analyze_5min_x100_metadata_plan.py`共**7个合成测试**，验证日期/代码统计剪枝、完整索引行为、缺少min/max保守处理、空索引、坏输入以及CLI纯Footer模式**不会调用H5/Parquet K线读取函数**。最新Windows测试仍待验收，预期180→**187**。

## 3. Windows下一步：只读Parquet Footer预检（不解码行情）

仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\analyze-5min-x100-focused-sessions.py "D:\stock" --date 2026-09-28 --baseline-report "H5ParquetReconciler\reports\h5-parquet-5min-2026-09-28-exact-residual-masks.json" --top-symbols 3 --plan-only --read-only --out "reports\pq-5min-2026-09-28-top3-footer-read-plan.json"
```

此命令仅需2026年原Parquet文件的元数据访问，**不要求重新计算原144根真实对账结果**。将新生成`H5ParquetReconciler/reports/pq-5min-2026-09-28-top3-footer-read-plan.json`上传即可。重点核对计划行组数与先前实际观察47/407、5,685,792条源行是否一致；若不一致需调查与原诊断一致的Parquet文件清单与源文件变化，不能直接当作提速效果。

### 只有用户已经拥有完成的2026 V3索引时

如本机**已经存在**完成、未变更源的`work/indexes/pq-5min-2026-a-share-candidate-v3.sqlite`，才可在上述`--plan-only`命令中加：

```powershell
--coverage-index "work\indexes\pq-5min-2026-a-share-candidate-v3.sqlite"
```

不会因为有2025索引或一个未完成的2026索引就跳读数据。**不要现在直接运行2026年V3全年度索引构建**：建索引第一次仍需解码全年ts/symbol，须先结合元数据报告、磁盘预算、完整需求与已有2026索引清单评估一次性成本。前轮V3测试已有中途恢复、`--max-new-groups`、`--max-index-mib`和`--max-run-seconds`控制。

## 4. 下一阶段建议

若元数据计划仍显示47组、约568万候选行，说明纯Footer min/max无法压缩读取。之后可以选择：（a）在确有多次2026定向查询需求时，评估复用V3索引的全年度一次性成本；（b）研究Arrow Dataset带条件推送的扫描，做**A/B相同证券同日精确结果校验和真实耗时对比**，但不得仅凭API调用就宣称数据解码减少；（c）获取供应商K线分钟起止规则，可能比重新扫描最有价值。不要未经验证就把候选H5×100作为正式转换规则，也不要自动覆盖任意一种来源。
