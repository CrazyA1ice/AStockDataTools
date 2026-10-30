# 2026-10-30：真实两分区Parquet日线联合只读视图（父10条 + 新股增量5条）

## 已完成的真实 Windows 验收

- PR #160 的 `test_append_private_unified_day_symbol_delta.py` **12/12项OK（5.314秒）**。本机私有 `SH600519` 已物理新增5根真实日线：购买Parquet 1根，H5已审计的整日缺口候选4根；新私有增量Parquet与manifest落盘。没有覆盖父快照原有10根、原购买Parquet、原Hikyuu H5，活动私有指针/正式路由不变。
- 新增物理分区路径：`work/unified_parquet/snapshot_deltas/delta_964332fc7055/day.parquet`。
- 增量脱敏SAFE：`reports/private-day-symbol-delta-964332fc7055.json`；delta Parquet SHA：`48550c2d9bc0ef84472787c3a5876ff2bfee13a9736ea31cfecc34bff7fa256f`，manifest SHA：`c5741bf1a0153ebfd1ea81d71927a97d1b4487ac8acbc34bfa91116ee30c0e31`。
- 原父快照不可变登记 SHA：`d625c323406ca92cb05c98e731a6920cbeeb14128e2175cc9f7b46e44946f207`，原私有H5整日缺口overlay来源 SHA：`46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03`。
- 因此目前是**两份已物化私有Parquet（10+5）及各自SHA证据**；还不是一个已经激活的全市场主库，也不能混淆“文件相互可联读”与“一个被提升的生产版本”。

## 本轮交付

`tools/read-private-day-snapshot-with-symbol-delta.py`以显式`--parent-version`及`--delta-safe`建立**不重新落盘、只在内存完成的联合逻辑视图**：

1. 父文件必须已SHA登记为私有不可变snapshot版本，调用已有`ADD.trusted_parent`重复核验父版本JSON的内容寻址SHA、父SAFE/manifest/Parquet的SHA及已物化全部行的schema/股日唯一键/来源计数；父版本与delta中记录的父版本、版本文件SHA、父SAFE、父Parquet、父manifest SHA必须全部一致。
2. delta只能指向模块内部 `work/unified_parquet/snapshot_deltas/delta_<12..32hex>` 的`day.parquet`与`manifest.json`，所有符号链接/路径穿越、超限大小、文件哈希变化即fail-closed。增量SAFE必须证明真实市场文件与生产路由未改、私有pointer没改、H5候选量纲未认证、不批准H5正式镜像。
3. 增量schema必须**逐字节匹配原父快照的Arrow schema**；其每股计数和来源标签、日期窗口、毫秒时间戳、OHLCVA有效性、行排序、完整股票日唯一键全部独立校验，并要求delta新增股票不在父股票集合中且总计不超过10只。
4. **先读取并校验父与delta全部数据**，再过滤用户明确选择的股票集合和日期区间；只允许原父日期窗口内的查询。检测到父+delta重复股票日也拒绝。最后重新复核父版本/源SAFE/Parquet及delta/manifest/SAFE的SHA，杜绝中途被替换后还返回成功SAFE。
5. CLI仅写模块`reports/`下新的**脱敏统计SAFE**：父10+delta5完整行数、整体股票数、选中行数及购买/H5来源分解、两套SHA、无生产修改声明；Python函数`read_joined()`可在本地进程中取得各股完整OHLCVA，但绝不将付费市场记录上传或提交仓库。
6. 这个**私有历史快照联合读取不重新访问D:\\stock**，所以不能证明原市场文件当前是否已到货、是否保持新鲜。若需要现场发现新行情，仍使用已有受预算保护的batch live校验器创建新delta；绝不可在只读查询中偷偷更新市场/激活pointer。
7. 原8+4根H5候选金额与数量仍标记待核实的量纲候选；正式Hikyuu日线镜像金额无损映射未认证，`ready_for_full_market_mirror=false`。

### Windows：先合成15项全通过，再实际读取15条私有历史日线

所有PowerShell命令使用**单物理行**：

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-day-snapshot-delta-joined-reader-20261030; if ($LASTEXITCODE -ne 0) { throw "switch失败" }; git pull --ff-only origin feat/private-day-snapshot-delta-joined-reader-20261030; if ($LASTEXITCODE -ne 0) { throw "pull失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_read_private_day_snapshot_with_symbol_delta.py" -v; if ($LASTEXITCODE -ne 0) { throw "15项联合视图测试未通过，不读取真实快照" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\private-joined-day-view-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\read-private-day-snapshot-with-symbol-delta.py --parent-version "d625c323406ca92cb05c98e731a6920cbeeb14128e2175cc9f7b46e44946f207" --delta-safe "H5ParquetReconciler\reports\private-day-symbol-delta-964332fc7055.json" --symbols SH600000 SZ000001 SH600519 --from-date 2026-09-30 --to-date 2026-10-13 --out $out --explicit-private-joined-read; if ($LASTEXITCODE -ne 0) { throw "真实私有父快照+增量联读失败" }; Write-Host "联合SAFE：$out"
```

**此PR尚未完成Windows测试；不能预先宣称15条均成功联读。** 若测试过关但现场私有SHA有变化应直接停止；不会自动覆盖数据或生成伪造成功SAFE。

## 下一阶段

若父10+delta5真实联读成功，再把**包含父SHA+delta SHA的私有联合逻辑视图**登记为独立不可变逻辑v2版本，并补显式版本回退/选择API；之后再扩展新的日期分区（必须有真实更新来源证据）和全市场覆盖。初版目标是避免频繁全量Parquet重编码，且不得把H5候选单位未认证的行情当作已可生产交易使用。
