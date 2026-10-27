# 2026-10-28：SH600000真实完整键扫描确认18/47组；复用定位结果的实验A/B

## 已收到的真实报告（不是估计）

用户本机的`pq-SH600000-20260930-5min-exact-rowgroups.json`，
包含**47组Footer候选、5,685,792行完整ts+symbol键扫描、18组有键、
29组无目标证券日键、48条目标键**。真实的目标行组ID为
`[1,2,7,8,9,10,12,15,18,20,23,25,31,32,35,36,37,40]`，
数据都出自`AllCycleAStockData/5min/2026-09.parquet`，
安全汇总不含OHLCVA。完整键扫描含Footer预检耗时**2.361006秒**。
当时9份源文件元数据stat摘要为
`7b5152e56ef1139256cecc161a9319261f71db3b63d0a5d61cae82bff5549f48`，
核对前后未变化；这**不是源文件内容SHA256**。

这和之前Arrow过滤后18组实际有输出相吻合，意味着单股票日Footer组定位非常宽泛。
**但目前只是完整键定位，尚未证实源六列数据读取确实加速**，更未证明把建立locator
成本算进去还能在单次查询获益。单次新目标日建立locator要先解码569万行的ts/symbol，
有明确的时间成本；现有显式私有OHLCVA缓存针对重复相同查询的0.05s命中模式通常更好。
仍需评估不保留付费OHLCVA但重复访问相同证券日的应用场景是否值得建索引。

## 新增代码：仅实验对照，不改变正式查询

- `tools/benchmark-parquet-arrow-filter-cold.py::arrow_filtered_query(...,allowed_rowgroups=...)`：
  仅新增可选`frozenset((相对路径,组ID))`**子集入口**，先完成原有的全部Footer候选
  和完整源行预算检查，严防缩小子集绕过源行成本防护；不传参数则旧行为原样。
  记录实际要扫描的行组数和对应Footer上限，不能冒充物理读行数。
- 新增`tools/benchmark-parquet-exact-rowgroup-reuse.py`，**只接受**
  `H5ParquetReconciler/reports/`目录下已有的完整键扫描JSON、限制128KiB，
  核对股票/日期/周期、候选47组/5,685,792行、源stat清单SHA和9文件、
  强制全键扫描标志、安全标志、每行组ID属于当前**真实Footer候选全集**、
  组ID不重复、每组键计数总和守恒。
- 对同一请求运行**full Arrow**与**restricted Arrow**两种引擎方式；
  其中restricted只访问已确认的18组；可用`--order full-first`或
  `--order restricted-first`初步控制系统缓存/执行顺序偏差。
- **无论是否提供`--verify-rowgroup`，都强制执行完整Arrow读，并与缩组查询
  比较开、高、低、收、量、额、原始时间、文件和行组来源**；
  同时用真实full结果反查每个行组`matching_key_count`，防止手工改过的报告
  让“漏一根”静默通过。加`--verify-rowgroup`会在同一次执行额外用原默认引擎
  逐根复核（更耗时）。
- 校验源stat签名自始至终一致；若比对失败、不在候选全集、超原全量预算、
  原始源发生变化，直接报错不保存成功报告。
- 命令行只保存新`reports/`中的安全统计JSON：独立计时、组预算、结果48根
  和安全标志，**不保存付费OHLCVA、私有缓存、任何原始时标**。不修改Parquet、
  H5、TDX或2025年V3索引，不切正式默认引擎。

注意：report本身是用户本地可编辑JSON，不是密码学签名；
因此强制完整查询逐根比对只证明**这次实验**没有漏K线，不能将未经持久信任链
认证的report直接用于无人值守生产剪枝。源stat可能在大小和mtime都不变时内容变化。
建立locator的2.361s与生成report的历史成本没有计入这两次引擎耗时，不能把
单次引擎A/B数值写成“整个工作流净加速”。

## Windows验收（仓库根目录）

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

下面两轮直接复用已存在的`reports/pq-SH600000-20260930-5min-exact-rowgroups.json`，
**不再执行耗时2.36秒的完整键扫描构建**。先完整组：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\benchmark-parquet-exact-rowgroup-reuse.py "D:\stock" --symbol SH600000 --date 2026-09-30 --locator-report "reports\pq-SH600000-20260930-5min-exact-rowgroups.json" --order full-first --verify-rowgroup --max-candidate-rows 30000000 --read-only --out "reports\pq-SH600000-20260930-rg-reuse-full-first.json"
```

再反序：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\benchmark-parquet-exact-rowgroup-reuse.py "D:\stock" --symbol SH600000 --date 2026-09-30 --locator-report "reports\pq-SH600000-20260930-5min-exact-rowgroups.json" --order restricted-first --verify-rowgroup --max-candidate-rows 30000000 --read-only --out "reports\pq-SH600000-20260930-rg-reuse-restricted-first.json"
```

**只上传以上新生成的两个reports/汇总JSON**，不要上传任何Parquet/H5、
`work/`缓存或原始OHLCVA。如果文件名已存在，使用`-v2.json`新名，
不要覆盖。当前工具的full和restricted均会读取原版全部**9份Footer**并检查
原先完整的47组预检预算，只是在OHLCVA/ts/symbol数据列上缩减实际扫描的组。
量化净收益需要分别考虑locator建立/失效/复用频率；本轮重点验证
完整和缩组**同引擎、同源精确一致**和缩组读取成本。

## 阶段性验收门槛

期望统计：`full_footer_candidate_row_groups=47`，
`restricted_row_groups_actually_scanned=18`，
`row_groups_not_read_in_restricted_scan=29`，
`matching_bar_count=48`，
`all_output_ohlcva_time_and_provenance_identical=true`，
`legacy_rowgroup_exact_equality_verified_this_run=true`。净加速或减读字节
**必须按Windows两次真实输出判定**，不得编造或外推。新加合成测试尚待实机运行；
不影响上轮已验收的298项及其后其它代码。
