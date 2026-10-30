# 2026-10-30：私有统一日线Parquet快照的独立只读加载器

## 已完成的真实Windows验收事实

`test_materialize_private_unified_day_parquet_snapshot.py` **10/10 OK（3.372秒）**，随后用户真正物化了一个私有统一Parquet快照，SAFE为：
`reports/private-unified-day-snapshot-ffc5c35e7e00.json`。

- 新私有真实数据文件：`work/unified_parquet/snapshots/snapshot_ffc5c35e7e00/day.parquet`。
- 两只股票，2026-09-30～2026-10-13：总日线10条，其中购买Parquet优先2条、已核验H5整日缺口候选8条。
- SAFE确认原值往返`all_written_values_roundtrip_exactly=true`、`purchased_parquet_priority_verified=true`；购买Parquet、原始H5与生产路由均没有改动，私有pointer未激活。
- 私有Parquet的SHA-256：`9fa9975bc115aa5740bad1be223c48c73da5afc15904f73f00aa0cb002252854`。
- 私有manifest的SHA-256：`1f19443e9ec4ee368fa99a4ca022163e986e096ef4774dce39e787d9f2b3e216`。
- 版本SHA：`46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03`。
- 前一个真实成交额残差样本**仍未取得无损/供应商物理单位认证**；保存的8条H5候选日线保留原来源标签。PR #157已合并main（`af3ec3e`）。

## 本轮新增：只从私有快照快速读，不重复扫描原市场数据

`tools/read-private-unified-day-parquet-snapshot.py`读取上面那份已有的SAFE作为唯一受信入口：
1. 限定模块`reports/`内已存在的SAFE；它必须声明私有物化完成但未激活、购买Parquet优先、原市场文件没改、H5候选单位未获认证、不批准全市场镜像。SAFE中提供精确相对路径、SHA和计数。
2. 路径只能在`work/unified_parquet/snapshots/snapshot_<12..32位hex>`，拒绝父目录/实际快照/Parquet/manifest中的符号链接；文件大小最大30MiB，最多5000根/32个Row Group，manifest及SAFE单份≤200KB，杜绝任意外部行情路径。
3. 前后重新计算`day.parquet`、`manifest.json`及源SAFE的SHA256；核验来源版本SHA、状态、清单总数/各证券分来源计数、Arrow精确schema，以及所有行的股票代码、日期、时间戳（交易日北京时区）、float64 OHLCVA合法性、`symbol + day`唯一键、时间顺序与来源标签。
4. 用户明确传入1～10只股票与**原快照窗口以内**的日期。加载器先读取和验证最多5000条的完整私有快照，再返回筛选出的结果。`read_verified()`可以在本地Python调用时得到完整OHLCVA内存数据，但**CLI只输出脱敏数量、安全状态、源快照SHA**，数据永不上传GitHub。
5. **这验证的是某个私有时间点的快照，不证明它是当前市场最新状态。** 为减少查询耗时，加载器故意不重新扫描D:\\stock购买Parquet或原始H5；原有`query-parquet-primary-day-overlay-batch-readonly.py`依然负责需要真正现场复核源的研究入口。后续可以单独规划“源更新→重新物化新快照”的安全流程，但不能让快速只读入口偷偷刷新或改写源。
6. 无论输入样本验证有多完整，`ready_for_full_market_mirror=false`、`h5_gap_units_remain_unverified_candidate=true`及`production_query_route_modified=false`均持续成立。这个阶段**不生成Hikyuu H5镜像、不激活pointer、不启动通达信自动更新**。

## Windows本机验收（所有命令在一整行）

首先运行**12项纯合成快照单测**，覆盖真正PyArrow压缩写读、全行SHA、按股票和日期筛选、重复主键、伪造SAFE、非法量纲许可、manifest篡改、伪造来源、时间戳错位、schema错误、运行中替换文件、不可覆盖输出及路径穿越。全部通过后再对**已有10条真实私有日线文件**进行一次直接读取验证：

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-unified-day-snapshot-verified-reader-20261030; if ($LASTEXITCODE -ne 0) { throw "switch失败" }; git pull --ff-only origin feat/private-unified-day-snapshot-verified-reader-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_read_private_unified_day_parquet_snapshot.py" -v; if ($LASTEXITCODE -ne 0) { throw "12项合成快照测试失败，拒绝真实快照读取" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\private-snapshot-verified-read-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\read-private-unified-day-parquet-snapshot.py --snapshot-safe "H5ParquetReconciler\reports\private-unified-day-snapshot-ffc5c35e7e00.json" --symbols SH600000 SZ000001 --from-date 2026-09-30 --to-date 2026-10-13 --out $out --explicit-private-snapshot-read; if ($LASTEXITCODE -ne 0) { throw "私有快照读取失败，请保留文件用于排查" }; Write-Host "私有快照只读SAFE：$out"
```

**本轮新增单测/真实快照加载尚未在Windows运行**，不得在报告中预填成功状态。请上传终端测试摘要及新SAFE JSON；**不要上传day.parquet、原购买Parquet、H5或私有实际行情记录**。

## 后续主线

快照只读加载的下一步是**私有Parquet按日期/证券分区的增量物化与只读查询**，尽量不重复扫描全市场；完成可回滚/升级版本协议后，再着手单独受控Hikyuu原生H5镜像。此前成交额物理单位和取整问题仍须由独立供应商元数据验证或明确的非无损候选策略来解决，不可未经授权覆盖生产H5。
