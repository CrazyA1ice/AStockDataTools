# 2026-10-29：四日H5/Parquet实时复核合并为一次有界扫描

## 真实v2性能证据（仅用户本地安全报告）

用户在Windows通过`test_query_parquet_primary_day_overlay_readonly.py` **10/10**（7.219s，结尾`OK`），上传只含安全指标的`private-day-query-SH600000-20260930-20261013-v2.json`。

- 目标股票SH600000、2026-09-30～2026-10-13，原购买Parquet **1条**、私有日线补全 **4条**，共5条；来源优先级、版本SHA、四日全审计、原市场数据不变。
- `private_version_sha256=46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03`。
- 总耗时 **249.920308秒**：版本核验 **1.273160秒**，现场缺失复核 **247.758501秒**，购买查询 **0.605372秒**，私有阶段解码 **0.257481秒**。耗时比例大约99.1%在四次重复的现场核对。
- 已知最低解码行数 **72,573**、组合返回5条，最低已知每条对应 **14,514.6** 次行级读取；这个数字不包括现场H5/PQ扫描的读取量、SHA字节IO。

## 本轮性能改动

以前调用方对四个已暂存日期分别执行：
`core.reconcile_section(root, ..., from_date=同一天, to_date=同一天)`，导致**重复四次扫描市场H5和购买Parquet**。同样的重复发生在`prepare`/`activate`的私有版本现场校验中。

新增`stage-h5-only-day-to-parquet.py::verify_live_absence_dates`：
1. 仅接受非空、规范ISO日期→正整数审计数量；必须同一年且首尾不超过31天。
2. 事前后均记录并核对3个原生H5及购买Parquet源文件大小/mtime，禁止源变化。
3. **仅调用一次**有界`core.reconcile_section`，保持`a-share-candidate`市场筛选、严格键核对、SQLite有界暂存和原始行情只读；窗口含中间非候选交易日也不自动补或抹掉。
4. 逐个已暂存缺失日核对`h5_unique==expected`、`parquet_unique==0`、`intersection_unique==0`、`h5_only==expected`、`pq_only==0`；任何目标日遇到新到货Parquet、重复键、源异常、数量不一致都直接拒绝。
5. 查询方和prepare/activate方改为调用这个批量复核。单日H5→Parquet暂存原有`verify_live_absence`保持原样；已准备22,191条版本、单条返回OHLCVA和市场原件不改。
6. 安全查询报告新增`live_absence_recheck_scan_count`（命中私有窗口时1，否则0）、相关实际范围内 H5/购买Parquet统计。

**预期收益**：四日现场复核从4次完整源扫描合并为1次范围稍广的扫描，不代表运行时间必然恰好四分之一。仍保留每次查询复核、没有把过期日期证明缓存成可信事实。实际性能与新回归结果均待用户Windows验收。

## Windows验收（仓库根目录）

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_stage_h5_only_day_to_parquet.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_build_parquet_primary_day_overlay.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_query_parquet_primary_day_overlay_readonly.py" -v
```

这三个测试文件预期分别 **10 + 12 + 11 = 33项**（增加3+1+1，历史总28项），在本地完整终端显示`OK`后，再做**唯一一次**真实SH600000安全查询：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-primary-day-overlay-readonly.py "D:\stock" --symbol SH600000 --from-date 2026-09-30 --to-date 2026-10-13 --version-sha256 "46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03" --max-candidate-rows 30000000 --max-result-bars 50 --max-overlay-source-rows 30000 --out "reports\private-day-query-SH600000-20260930-20261013-v3.json" --read-only
```

验收原则：与v2相同 **1购买+4私有=5条**、四个日期都现场重验、`live_absence_recheck_scan_count=1`、原始数据未改、指针未切换；比较`live_absence_recheck_elapsed_seconds_this_invocation`从247.758501秒变化到多少。首次运行热缓存或磁盘占用等会影响时间；报告新计时后须注明测量环境，勿直接宣称稳定提速倍数。

仅上传新安全v3 JSON及三组测试结果，绝不上传`day.parquet`商业行情，亦不为性能关闭安全复核。
