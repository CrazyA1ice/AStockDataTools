# 2026-10-30：统一日线Parquet私有快照的不可变登记、显式切换与回滚

## 真实已验收事实

2026-10-30 Windows `test_read_private_unified_day_parquet_snapshot.py` **12/12项OK（5.361秒）**。此前生成的私有统一日线快照 `work/unified_parquet/snapshots/snapshot_ffc5c35e7e00` 已在本机成功加载10根（日线，SH600000/SZ000001，2026-09-30～2026-10-13）：**购买Parquet2根、原H5已验整日补缺候选8根**。本次上传的SAFE为`reports/private-snapshot-verified-read-e4ea16e0e26a.json`。核验三方SHA、完整Arrow Schema/行键/源计数都成功，没有读取或改写原始商业市场文件。**注意：这次是快照完整性，不代表与实时市场数据保持同步**。PR #158已经合并main（`d0d76eb`）。

## 本轮功能

`tools/version-private-unified-day-parquet-snapshot.py`为已成功读取的**私有物理快照**新增完整的模块内元数据版本生命周期：

- `prepare --snapshot-safe <已有SAFE>`：完全重新验证这份SAFE所绑定的Parquet和manifest SHA-256，读取并检查全部行的schema/唯一股票日/日期/来源总数，才创建内容寻址的不可变`work/unified_parquet/snapshot_versions/<sha256>.json`。记录上一私有已激活版本SHA（如无则为null）。不改指针，登记同一内容/同一上一指针幂等，不覆盖已存在数据。SAFE中只记录相对私有路径、hash和行数，不泄露真实OHLCVA。
- `activate --version <sha256> --confirm-private-pointer`：必须明确确认。锁住模块内`.private-snapshot-version.lock`，检查版本内容hash、记录的上一指针恰好等于当前指针，再次验证原快照全部行；**仅**以临时文件+os.replace原子更新`work/unified_parquet/active-private-snapshot.json`，不动原Parquet、H5或任何生产查询路由。
- `rollback --confirm-private-pointer`：锁住私有指针，检查当前版本与上一版本的证据；若上一版本文件完整，原子回退至上一个版本；首个版本的回退则停用私有指针。**从不删除**Parquet/manifest/历史版本文件，任何源hash损坏拒绝将被破坏版本作为新活动快照。
- `status`：只报告私有指针当前版本SHA和已验证总根数；指针缺失则报告空；无原H5/购买Parquet访问、不打印商业OHLCVA；若SHA或指针被篡改立即拒绝。

**两套私有指针完全隔离**：本轮`active-private-snapshot.json`和此前`active-day-overlay.json`互不影响。更不会自动影响交易软件、生产查询路径、行情数据库。

新增**14项虚构数据测试**，复用之前真正写入临时Arrow Parquet、生成临时SAFE/manifest的测试fixture，覆盖：
1. 全行验证后登记、不激活、不可变内容hash。
2. 重复登记幂等、无覆盖。
3. 源Parquet篡改/自改manifest后虽然重签SHA也必须检查重复股票日。
4. 版本元数据被篡改拒绝。
5. 并发锁、指针伪造或符号链接拒绝。
6. 显式启用后回退首版、双版本链回退、旧版本过时激活拒绝。
7. 上一个版本原文件损坏不能回退成该破损版本。
8. 登记后SAFE哈希变动/manifest变动不能启用。

**这些新增14项测试尚待Windows实际运行；正式原生H5金额映射和生产自动写入仍明确禁止。**

> **Windows回归修复（2026-10-30）：** 首轮14项测试中13项`ok`，仅`test_forged_or_symlink_private_pointer_rejected`因测试程序自行创建符号链接时遇到`WinError 1314`而报错。这是非管理员Windows账户的文件系统创建权限，不是私有指针校验器允许了符号链接。PR分支提交`4ed93f1`已改为用`unittest.mock.patch.object(Path, "is_symlink", ...)`确定性模拟指针指向符号链接，依然要求`read_pointer()`拒绝并报出`symlink`，**没有跳过验证**。首轮命令自动中止，真实`prepare`及`status`均未运行；新14项通过情况待Windows复测。

## Windows本次建议只运行“prepare”和status，不触及指针

在仓库根路径（PowerShell一整行）：

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-daily-snapshot-version-pointer-20261030; if ($LASTEXITCODE -ne 0) { throw "switch失败" }; git pull --ff-only origin feat/private-daily-snapshot-version-pointer-20261030; if ($LASTEXITCODE -ne 0) { throw "pull失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_version_private_unified_day_parquet_snapshot.py" -v; if ($LASTEXITCODE -ne 0) { throw "14项虚构版本测试失败，停止" }; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\version-private-unified-day-parquet-snapshot.py --action prepare --snapshot-safe "H5ParquetReconciler\reports\private-unified-day-snapshot-ffc5c35e7e00.json"; if ($LASTEXITCODE -ne 0) { throw "私有版本登记失败" }; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\version-private-unified-day-parquet-snapshot.py --action status; if ($LASTEXITCODE -ne 0) { throw "私有版本状态核验失败" }
```

预期`prepare`输出不可变版本SHA，`status`仍显示`active_version_sha256=null`、`verified_active_snapshot_rows=0`。**如果用户此前已单独激活另一私有快照**，status可能不是空，这不是错误，应该以真实值为准。本次绝不调用activate/rollback。

准备之后仅需终端测试结果和版本SHA/状态JSON文本，不上传原真实`day.parquet`、原H5或购买Parquet，也不用重复跑原市场全面扫描。

## 下一阶段：不把登记当增量完成

现在新增的是元数据登记/原子版本切换/回退**基础设施**，并非真正自动增量写库。下一步用新的`day`股票日期分区进行增量物化：新源日线不能覆盖原购买Parquet，也不能覆盖已经在旧版本中锁定的股票日期；必须在候选来源日线经过现有严格LIVE来源验收后创建**新的**Parquet目录，再由本版本系统记录 lineage。未经认证的成交额单位继续保留候选性质。

主线是购买Parquet优先→H5真缺整日补齐→私有可回滚统一Parquet→原生Hikyuu H5镜像→通达信收盘增量。5min历史时间标签与微差探索继续暂停。
