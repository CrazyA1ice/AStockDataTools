# 2026-10-28：精确定位查询端到端耗时拆解与重复Footer预检复用

## 三份用户Windows真实安全报告

`pq-SH600000-20260930-rg-reuse-offline-audit.json`：
在`SH600000/2026-09-30/5min`同一股票日及同一源stat清单下，
full Arrow查询47组，精准Arrow只查18组，逐根与完整Arrow及默认RowGroup数据
一致。full-first时2.580526s→0.479882s（5.377418×），
restricted-first时1.000471s→0.528956s（1.891407×）；
旧locator构建成本2.361006s。只在该有限样本里可作**2～6次查询回本情景**估计，
不是实际生产净收益证明。源stat为路径/大小/mtime而非内容SHA。

`pq-SH600000-20260930-locator-preview-verified.json`：
48根、47组全预检、18组数据列扫描，严格full Arrow逐根相同。
`restricted_engine_elapsed_seconds=1.573799`、总耗时**5.763604s**，
full Arrow复查2.136311s。

`pq-SH600000-20260930-locator-preview-fast.json`：
48根、47组全预检、18组实际数据列扫描，**跳过本次完整复查**；
仅有源stat签名和选择组计数校验，
`restricted_engine_elapsed_seconds=0.646492`、总耗时**1.641963s**。
约0.995471秒在Arrow计时范围外，占整个快速调用约60.6%，
但来源报告不能再细分来源。这是**当前优化的切入点**。

验证报告还明确：用户可编辑的locator JSON**未签名**；源stat**不是内容hash**。
快速模式即使总键数和所选行组数一致，**恶意修改报告仍可能漏数据**，
不可自动生产剪枝。两个报告只读、未改行情、没输出付费OHLCVA。

## 本轮代码改变：复用一次已经验证的预检上下文

原`query-parquet-exact-locator-preview.py`先调用`query.prepare_query()`
取得47组真实Footer候选并校验locator，但`arrow_filtered_query()`内部**再次**
调用`prepare_query()`，快速模式共**两次**、默认带full复查共**三次**。
真实报告不能证明所有额外耗时都是这个问题，但代码确有可避免的重复工作。

现在`benchmark-parquet-arrow-filter-cold.py::arrow_filtered_query()`
新增内部`prepared_context`参数，仅由受控定位预览传入**本次已完成的**
`query.prepare_query()`对象（不是跨调用、跨进程缓存）。
- 再验证请求的股票、周期、日期、数据根路径、原始全量候选源行预算、
  最多结果条数、时间范围及证券别名完全匹配。
- 独立核验上下文中全量Footer候选行组ID不重复、来源路径不得跳出
  `AllCycleAStockData`、各组Footer行数之和与原先完整预算完全一致。
- 仅省去同一次调用里冗余的`prepare_query()`；**不会**让子集跳过
  原47组的预检安全预算，也没有让locator默默成为受信任的生产索引。
- 既有`arrow_filtered_query(...)`的默认路径（不传prepared_context）
  行为不变，旧Arrow反序A/B及其它脚本仍各自独立安全预检。

定位查询默认模式复用同一个已预检上下文运行restricted与full的逐根对照；
显式`--fast-stat-only`只运行restricted。在两种模式下均保留：
源文件stat签名读前/读后、locator身份/组数/组内匹配键数验证、
合法候选组全集及原始预算、源文件只读、安全报告不输出OHLCVA。

### 时长字段语义变化，不能与旧字段直接当作同口径对照

预览新报告新增：
- `full_footer_preflight_executions_this_invocation=1`；
- `prepared_preflight_context_reused_for_arrow_scans=true`；
- `source_manifest_before_seconds`；
- `full_footer_preflight_seconds`；
- `locator_validation_seconds`；
- `source_manifest_after_seconds`；
- `arrow_engine_seconds_are_scan_only_in_prepared_mode=true`。

**注意**：本轮`restricted_engine_elapsed_seconds`记录使用已备好的
ParquetFile上下文后**Arrow实际过滤扫描和结果构建的耗时**，
**不再包含重复Footer预检**；所以不要直接拿它与旧版的0.646492秒比较得出
“纯Arrow变快了”。评价真正优化是否有效，应以
`total_invocation_wall_seconds_including_validations`与新增细分字段为主；
受OS缓存、顺序、负载影响，最好在同机重复多轮并保留不同报告。
本轮**尚无新代码运行后的真实Windows耗时**，不能预报节省量。

## 本轮Windows验收命令

在`D:\ChatGPT\AStockDataTools`仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

先跑默认完整校验（新摘要名，不覆盖已有报告）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-exact-locator-preview.py "D:\stock" --symbol SH600000 --date 2026-09-30 --locator-report "reports\pq-SH600000-20260930-5min-exact-rowgroups.json" --read-only --out "reports\pq-SH600000-20260930-locator-single-preflight-verified.json"
```

再手动运行一次显式实验快路径：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-exact-locator-preview.py "D:\stock" --symbol SH600000 --date 2026-09-30 --locator-report "reports\pq-SH600000-20260930-5min-exact-rowgroups.json" --fast-stat-only --read-only --out "reports\pq-SH600000-20260930-locator-single-preflight-fast.json"
```

只需分享**上述两份新`reports/`安全JSON**以及完整单测结果；
无需源Parquet/H5或`work/`目录。若文件已存在使用另一个新名字。

## 下一步决策门槛

只有**单次完整预检复用成功**、同股票日48根与full Arrow仍严格一致、
快速模式耗时实测有益、源stat稳定、不泄露付费OHLCVA后，
才考虑更广泛的月份/股票小范围样本；**在选择可用的月度多证券键索引前，
先评估真正用户用例是否需要反复只读原Parquet**。
目前正式默认查询、已有私有OHLCVA缓存、2025年V3索引和源行情均不修改。
