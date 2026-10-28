# 2026-10-28：精确RowGroup读取双顺序真实提速；离线验收和显式复用查询预览

## 实验证据——两个顺序同一股票日均提速

用户在Windows上的两个安全JSON（已含完整价量额、时标和来源的内部对照；输出**不含**付费K线）：

| 顺序 | full Arrow 47组 | restricted Arrow 18组 | full/restricted | 这次调用节省 |
|---|---:|---:|---:|---:|
| full-first | 2.580526s | 0.479882s | 5.377418× | 2.100644s |
| restricted-first | 1.000471s | 0.528956s | 1.891407× | 0.471515s |

原源stat SHA摘要均为
`7b5152e56ef1139256cecc161a9319261f71db3b63d0a5d61cae82bff5549f48`
（9份文件的路径/size/mtime，**不是内容SHA**）；均返回48根，均确认
full Arrow vs restricted Arrow **OHLCVA六字段、源时间标签、源文件和RowGroup来源
逐根完全相同**，并额外与默认ParquetFile RowGroup引擎核验一致。

相比原来47个候选RowGroup（行数上限5,685,792），实际18组的Footer行数总上限
2,213,909（减少3,471,883，约61.1%）；这仅是**实际进入解码候选的RowGroup行上限**
变化，不能代表实际Parquet物理解码记录或磁盘读取字节减少相同比例。
18组的具体ID来自先前完整`ts/symbol`两列键索引，定位建造用了2.361006秒。
两次A/B复用了旧定位文件，未包含新建成本，且原9份Footer/47组完整预检预算仍执行。

### 成本回本分析只是情景估算

计算：单次节省`full_seconds - restricted_seconds`，假设可以稳定重复、locator
永远有效、每次请求不生成新索引、仅摊销一次`2.361006s`键列扫描成本。
`full-first`观测节省2.100644秒：第2次节省合计才超过一次建立成本；
`restricted-first`观测节省0.471515秒：约第6次才超过一次建立成本。

即**2～6次是样本条件下的算术回本范围，不是任意股票/日的预测，不含缓存失效重建、
文件系统缓存顺序、调度/序列化/多股票复用/隐私代价**。此前同一目标股票日私有
OHLCVA缓存命中约0.05秒，对完全相同重复查询很可能更有性价比；精确locator
目标是**不存付费价量额、需要反复读取真实源文件**的工作流。

## 本轮新增：两个隔离工具

### 1. 安全离线双顺序复核

`tools/audit-parquet-exact-rowgroup-ab.py`只读前述2份汇总JSON；
严格审查反序、同源stat、47→18、结果数48、完整价量额来源一致性、
与原引擎验证、安全标志、耗时为正/数值合法、未篡改的速度比率；
生成新`reports/`安全审计报告，包括观测速度和**情景回本次数**。
不打开原始H5/Parquet/私有缓存，不重跑行情，也不导出OHLCVA。
输入可由用户本地编辑，故该审计只证明**提供的报告互相自洽**，并非重新
读取市场源码认证。

### 2. 可显式调用的本地定位查询预览

`tools/query-parquet-exact-locator-preview.py`：

- **默认保守**：复用已有完整键locator之前先核对**真实Footer候选全集、
  原完整5,685,792源行预算、每组ID/键数与来源stat指纹**；
  缩组Arrow读取仅18组，然后再跑**完整Arrow**并比较每根OHLCVA、源时间及
  来源行组；不一致直接报错，不输出成功报告。
- **显式实验快路径**：加`--fast-stat-only`才跳过完整Arrow重查，让重复
  定位查询实际只解码18组相应列并发挥提速；仍做统计签名、
  原完整预算、每个已选择组实际键数/全局总数检查，变化即失败。
  **但locator JSON本身可编辑、未签名，源stat并非文件内容HASH**：
  如果locator被有意改成别的、但键数一致且结构自洽，就可能静默漏某些
  K线，不能用于正式无人值守生产；报告会明显标注
  `fast_path_can_silently_omit_bars_if_locator_is_tampered=true`、
  `full_arrow_equality_checked_this_invocation=false`。
- 严格限制股票+5min+单日、有界结果和候选RowGroup预算；
  CLI只写`H5ParquetReconciler/reports/`新汇总JSON、不保存行情，
  返回原OHLCVA仅在本机进程内存；不读H5、不写私有行情缓存/SQLite、
  不改购买源、2025V3或正式默认`query-parquet-primary-readonly.py`。
- 未实现可自动信任、自动更新、内容验证与回滚的**生产持久索引**，
  不应在未验证成本/新鲜度/可靠性之前把快路径置为默认。

## Windows限定验收命令（仓库根目录）

先拉最新代码并跑完整合成测试；本轮**另新增12项合成测试，尚待Windows验收**：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

对已有报告做**无需行情扫描**的离线审核（只生成安全汇总）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-parquet-exact-rowgroup-ab.py --full-first "reports\pq-SH600000-20260930-rg-reuse-full-first.json" --restricted-first "reports\pq-SH600000-20260930-rg-reuse-restricted-first.json" --read-only --out "reports\pq-SH600000-20260930-rg-reuse-offline-audit.json"
```

对已有旧locator做一次严格全量逐根核验（**包含完整扫描，不能用于测快速模式净延时**）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-exact-locator-preview.py "D:\stock" --symbol SH600000 --date 2026-09-30 --locator-report "reports\pq-SH600000-20260930-5min-exact-rowgroups.json" --read-only --out "reports\pq-SH600000-20260930-locator-preview-verified.json"
```

如果两步无报错，运行一次**本机显式自担定位报告未签名风险**的快速路径：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-exact-locator-preview.py "D:\stock" --symbol SH600000 --date 2026-09-30 --locator-report "reports\pq-SH600000-20260930-5min-exact-rowgroups.json" --fast-stat-only --read-only --out "reports\pq-SH600000-20260930-locator-preview-fast.json"
```

**仅上传三个新`reports/`汇总JSON**，无需购买Parquet/H5或包含价量额的私有
缓存。输出不覆盖既有文件，若路径已存在加`-v2`等新名字。

## 下一轮科学问题

- 真实限定样本中，重复定位读取18组能否稳定维持0.5s级总调用耗时？
  对照报告需要用`total_invocation_wall_seconds_including_validations`，
  而不只是Arrow内部`restricted_engine_elapsed_seconds`。
- 多股票同一月是否可通过一次`ts,symbol`键扫描摊销定位成本？
  需先证明做成**月度多证券只键索引**有净收益；构建完整可信索引后再评估
  分层更新和失效/回滚，避免一直用每股票日2.36秒的单独完整扫描。
- 默认查询、显式私有OHLCVA缓存及源版权限制继续保持不变。
