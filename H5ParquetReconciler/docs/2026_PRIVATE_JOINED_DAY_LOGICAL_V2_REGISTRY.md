# 2026-10-30：将真实父快照10条 + 股票增量5条登记为不可变私有逻辑日线版本

## 前置实际验收

2026-10-30 Windows `test_read_private_day_snapshot_with_symbol_delta.py` **15/15 OK（11.313秒）**。同一次只读联查从父Parquet10条和增量Parquet5条返回**3只股票、15条日线**：原购买Parquet来源3条，已确认的H5整日缺口候选12条。上传的安全JSON为`reports/private-joined-day-view-89a0473ec5ad.json`，记载：

- 父版本SHA：`d625c323406ca92cb05c98e731a6920cbeeb14128e2175cc9f7b46e44946f207`。
- 父Parquet SHA：`9fa9975bc115aa5740bad1be223c48c73da5afc15904f73f00aa0cb002252854`。
- 新股票delta Parquet SHA：`48550c2d9bc0ef84472787c3a5876ff2bfee13a9736ea31cfecc34bff7fa256f`。
- delta manifest SHA：`c5741bf1a0153ebfd1ea81d71927a97d1b4487ac8acbc34bfa91116ee30c0e31`。
- delta SAFE：`reports/private-day-symbol-delta-964332fc7055.json`。
- `parent_delta_full_schema_keys_counts_and_hashes_verified=true`、`no_live_market_source_freshness_recheck=true`、`private_snapshot_pointer_read_or_modified=false`，原购买Parquet/H5和生产路由从未被这个查询访问或更改。此事实由用户真实Windows日志/SAFE共同支持。PR #161合并main（`8217572`）。

这些信息**不能当成数据源2026-10-30仍最新的证明**。尤其H5候选金额量纲未获得权威认证，不允许据此开始真实原生H5镜像或生产写入。

## 本轮开发：新逻辑版本（不复制一条商业行情）

新`tools/register-private-joined-day-logical-version.py`提供：

- `prepare --parent-version <已注册父快照SHA> --delta-safe <已有的私有新股增量SAFE>`：重复校验**整个**父10根与增量5根的Arrow Schema、股票日期唯一性、时间戳、来源计数、所有父版本与delta manifest/SAFE/Parquet/版本文件SHA，并在版本登记前/锁内分别执行验证。通过后在`work/unified_parquet/joined_day_versions/<逻辑版本SHA>.json`写入独立的**内容寻址、不可变**逻辑版本信息，引用两套既存Parquet及其SHA。**不会重编码/复制旧10条或新增5条Parquet文件**，不会新增真实行情记录。对相同前驱指针/相同原始两个分区进行重复登记幂等。
- `activate --version <逻辑SHA> --confirm-private-joined-pointer`：强制显式确认，锁住单独的`work/unified_parquet/.private-joined-day.lock`，检查登记时的前驱指针仍未发生变化、两套真实Parquet仍哈希一致/全行通过，再将**只用于研究**的`work/unified_parquet/active-private-joined-day.json`原子更新。它与已有`active-private-snapshot.json`和`active-day-overlay.json`两类指针全部隔离，**从不影响生产数据库/行情路由**。
- `rollback --confirm-private-joined-pointer`：只回退私有逻辑版本指针。如果没有前驱则关闭指针；有前驱则先复验前驱逻辑版本，损坏即拒绝。保留过去所有Parquet/manifest/SAFE/版本文件，不做商业数据删除或覆盖。
- `status`：只报告当前私有逻辑版本SHA、已验证日线条数和股票数量。若指针未启用，报告`active_joined_version_sha256=null`、`active_joined_rows=0`。不从`D:\stock`读取原始数据。
- **权限边界：** 全部文件仅在Git忽略的模块`work/`、`reports/`中；元数据只保存SHA、来源行数、窗口和SAFE文件名，不上传OHLCVA、真实股票列表、H5/商业Parquet内容。所有路径只允许模块内部且拒绝符号链接/不完整数据/并发争用。原生H5镜像仍被禁用。

新增**14项全虚构PyArrow合成测试**，从旧父3行+新股票2行的真实临时Parquet fixture构造，不触及任何用户实际数据，覆盖：
完整版本登记、不复制父/增量Parquet、登记幂等、输入/时间/行键错误、伪造delta来源、父/增量文件哈希破坏、版本元数据破坏、并发锁、私有指针明确激活与停用、双代回退、过期版本拒绝、源SAFE更新拒绝及Windows普通账户模拟符号链接拒绝。

## 本次真实Windows验收：**只登记，不激活**

只需执行一次以下**单物理行**PowerShell（不需要上传原始行情）：

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-joined-day-logical-v2-registry-20261030; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/private-joined-day-logical-v2-registry-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_register_private_joined_day_logical_version.py" -v; if ($LASTEXITCODE -ne 0) { throw "14项合成逻辑版本测试失败，不执行真实登记" }; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\register-private-joined-day-logical-version.py --action prepare --parent-version "d625c323406ca92cb05c98e731a6920cbeeb14128e2175cc9f7b46e44946f207" --delta-safe "H5ParquetReconciler\reports\private-day-symbol-delta-964332fc7055.json"; if ($LASTEXITCODE -ne 0) { throw "真实15条逻辑版本登记失败" }; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\register-private-joined-day-logical-version.py --action status; if ($LASTEXITCODE -ne 0) { throw "私有逻辑版本状态查询失败" }
```

全部成功后，`prepare`输出新的64字符`version_sha256`、`joined_rows=15`、`joined_stocks=3`、购买3、H5候选12、`private_joined_pointer_changed=false`。紧接着`status`的`active_joined_version_sha256`应仍是`null`，除非用户曾独立启用别的私有联合版本。本轮没有操作任何`activate`/`rollback`命令。

请只回传14项测试摘要与登记/状态的两个JSON文本，不上传真实商业Parquet或私有`day.parquet`。**新测试和真实登记尚未在Windows实际验收，PR必须保持Draft。**

## 与后续真正日线增量的关系

本轮交付的是新的**逻辑版本元数据层**。后续可基于显式逻辑版本做源快照/增量快速读取与私有选择/回滚；下一阶段才引入真正**新交易日**的增量来源（通达信盘后或新到货购买Parquet）——需要新的独立现场来源证据、购入Parquet第一优先，不能拿已有历史H5直接模拟2026-10-14后的行情。真实H5金额整数无损性仍未认证，不允许自动写入生产Hikyuu。
