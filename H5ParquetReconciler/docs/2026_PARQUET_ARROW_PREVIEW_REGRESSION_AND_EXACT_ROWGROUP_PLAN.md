# 2026-10-28：Arrow预览真实回归波动；下一步转向精确证券日RowGroup定位

## 一、本机第三份真实报告：结果完全一致，但速度并非稳定胜出

用户提交 `pq-primary-arrow-preview-SH600000-20260930-verified.json`。
查询`SH600000/2026-09-30/5min`：
- `matching_bar_count=48`，`rowgroup_exact_equality_verified_this_invocation=true`，同一次预览中逐根对齐OHLCVA、原始时间标签、源文件与行组。
- 仍有`candidate_row_groups=47`、`candidate_source_rows_upper_bound=5,685,792`；元数据源文件9份，stat摘要`7b5152e56ef1139256cecc161a9319261f71db3b63d0a5d61cae82bff5549f48`且查询期间稳定（该摘要并非内容SHA）。
- Arrow过滤后仅交付48条，**只有18个RowGroup交付了匹配结果**；实际物理解码行数和磁盘字节未知。
- 当前预览Arrow耗时`2.972944s`，同行验证的默认RowGroup引擎耗时`1.791278s`。本次Arrow约为基线的**1.66倍耗时**，即相较基线**耗时增加约66.0%**；此前两次 A/B 算出的Arrow优势分别为3.213×、1.392×。两类结果都是真实观察，不能用之前的优势否认新结果。

这不是逻辑错误，也不能从单次反转断定性能退化原因。预览采用Arrow先跑、再运行基线的验证顺序，OS页缓存、磁盘状态、后台负载等都有影响；先不调生产引擎，不把`--verify-rowgroup`下的两段耗时误认为严格受控的多轮冷热基准。

**阶段性结论**：Arrow对该证券日的结果质量已证明可与旧引擎严格一致；性能方向在三份真实样本的不同运行间出现反转，**不满足默认替换条件**。既有正式RowGroup查询及显式私人缓存保持原样。

## 二、从替换查询引擎转向减少47个候选行组中的无效扫描

上一轮的Arrow报告与本轮预览均指出：47个Footer候选组中，只有18个组交付目标查询范围的记录。**另外29个组虽属于安全候选，但在该次Arrow过滤后没有目标结果。** 这里的18和29不是未经证实的物理读取数量，亦不能证明这29组在其它日期、其它证券上可跳过。

这意味着基于Footer的时间区间/证券min-max过滤可能过粗。若能以**同一源stat指纹下的完整键列扫描**确认具体哪些行组存在该股票当天的键，将来可针对后续同一证券/日期的重复非缓存查询只解码有真实成员的行组；是否有净收益还取决于建立索引的成本、数据新鲜度、维护频率和后续请求数量。

### 本轮新增：只读、完整的两列键扫描规划工具

`tools/plan-parquet-5min-exact-rowgroups.py`：

1. 仅支持单只A股候选股票、单个5min日期，复用`query.prepare_query()`的源文件安全预检、证券别名与全候选RowGroup集合。
2. 默认最多3000万候选源行、1000个候选行组、25000个匹配键；超过预算则失败退出，禁止悄悄漏掉未知RowGroup。
3. **扫描每个候选RowGroup的全部`ts`和`symbol`两列**，检查扫描行数=Footer行数；只对所选证券+日的实际键确认是否包含，拒绝重复时间键、非法对齐时间、计数不守恒。
4. 扫描前后校验全年度源文件stat清单一致；只输出模块`reports/`汇总JSON（行组ID、匹配键个数与时间成本），绝不写付费OHLCVA、无源行情改写、无自动并集。
5. 这只是**候选定位的独立研究数据**，不会被正式查询自动采用，也不创建持久索引；不是归一化、复权或全市场质量认证。仅能证明当前键列扫描覆盖与当前stat签名对应的行组。

新增6项合成测试，验证全组扫描与只含他股键的排除、空结果不捏造数据、重复时间键、严格预算、数据源指纹漂移、仅新报告可写/不能覆盖。尚待用户Windows测试结果，不能预报通过数。

## 三、Windows本机有限验收

在`D:\ChatGPT\AStockDataTools`仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

随后才运行这条目标日两键完整定位命令：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\plan-parquet-5min-exact-rowgroups.py "D:\stock" --symbol SH600000 --date 2026-09-30 --max-candidate-rows 30000000 --max-candidate-groups 1000 --max-result-keys 25000 --read-only --out "reports\pq-SH600000-20260930-5min-exact-rowgroups.json"
```

只需上传`H5ParquetReconciler/reports/pq-SH600000-20260930-5min-exact-rowgroups.json`，不要上传付费Parquet/H5、原始行情、私有缓存。目标文件已存在请换新名字，因为默认拒绝覆盖。

**验收要点**：目标48根对应完整的48个原始时间键（目前验证的原数据为48根），`candidate_row_groups=47`，`two_key_columns_source_rows_examined=5,685,792`，行组有键个数有可能为18（来自之前Arrow过滤结果的可对照观察），实际以真实报告为准。扫描绝不应导出OHLCVA。键列扫描本身会解码约568万行的两列，**首次定位也有成本**；不能宣称已经提高首次查询速度。

## 四、之后的主线门槛

只有完整键定位给出无遗漏、源stat一致、精确组列表后，才考虑为**重复但不采用私有OHLCVA缓存的查询**提供可选行组定位缓存，并强制源stat变化失效与全输出逐根对照。需要累计建立成本与后续查询净收益实测，避免把索引成本从查询前移后假称免费提速。**2025 V3主索引62/522的持久性和范围不受本工具影响。**
