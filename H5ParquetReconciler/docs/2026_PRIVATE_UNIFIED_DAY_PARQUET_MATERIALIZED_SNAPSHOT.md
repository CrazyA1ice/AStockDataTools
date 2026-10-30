# 2026-10-30：将购买Parquet + H5完整日期缺口实物化为私有日线Parquet快照

## 先确认这不是另一次金额试验

- 2026-10-30 用户Windows完成`test_audit_real_pq_h5_amount_residual_readonly.py` **10/10 OK（1.345秒）**，真实SAFE `reports/real-day-h5-amount-residual-20260930-c721ea5bafbf.json` 确认两股金额候选均低于原H5整数、残差在 (0.01,0.1] 原始H5整数刻度、最近整数与向上取整2/2、向下取整0/2、但无损严格相等0/2。PR #156已合并main（`e1c3386`）。
- 这不能批准供应商成交额物理单位或通用取整规则；**暂缓重复扩大同一2股票日的金额残差试验**，转向真实私有数据产品。
- 主线：**购买Parquet优先 → H5只补已确认的整股票日缺口 → 可回滚统一Parquet → Hikyuu 2.8.1原生H5镜像 → 通达信日终增量**。历史5min微差仍暂停。

## 本轮真正交付：物化数据，而不仅是一个查询返回

新增 `tools/materialize-private-unified-day-parquet-snapshot.py`，仅在用户明确指定一个之前已准备好的**不可变4日私有补缺overlay SHA**、1～10个A股代码和1～31日同年窗口时才能运行。直接复用已经Windows通过16项测试的 `query-parquet-primary-day-overlay-batch-readonly.py` 的**完整原生读路径**：

1. 从**购买Parquet**读取窗口内每股原始`float64`价格、成交额、数量和原始毫秒时间戳；同一股票日已有购买数据永远优先，不修改、不估计、**不对购买成交额进行舍入或缩放**。
2. 私有补缺部分仅从已验收、**prepared未激活**的overlay里消费（2026-10-08、09、12、13完整股票日）；再次核验stage哈希、购买侧当前整日空缺和原H5源状态。已有私有补缺日线的金额/数量仍按旧方案保留 **`candidate_unverified`** 来源标签，不冒充经过权威物理量纲认证的原购买数据。
3. 所有合并记录必须唯一的`symbol + trading_date`，每个字段非负且有限，OHLC满足价格几何，每股及总量与原批量只读SAFE严格一致，源标签只允许 `purchased_parquet` / `private_hikyuu_h5_gap_candidate`。
4. 只有**全部读数据与原市场源审核通过**才创建用户指定的全新 `H5ParquetReconciler/work/unified_parquet/snapshots/snapshot_<12-32位hex>/`，其中 `day.parquet` 物理落盘，并原值Parquet往返验证，不允许重复key、剪裁日期或部分结果提前完成。
5. 目录中 `manifest.json` 保存SHA256、购买/私有来源计数、版本SHA和精确往返标记（**不包含市场OHLCVA值**）。模块`reports/`下单独生成新SAFE JSON，包含相对私有路径、SHA和统计计数，**不包含原始行情、真实源绝对路径或发行方商业数据**。
6. 临时文件/私有市场产物只在git忽略的`work/`。任何失败都不写成功SAFE；如果失败发生在私有目录创建之后可能留下**未验收的独立目录**，不自动删除、不能按合法快照使用。原始 `D:\stock\AllCycleAStockData`、`D:\stock\HikyuuData` 严格只读。
7. 从不激活私有 `active-day-overlay.json`，绝不替换原购买Parquet、自动切换主查询或生成正式H5。已写私有文件的SHA是检测证据，不保证跨进程原子事务；下游消费前仍应重验SHA。

这是第一个**带购买源优先级、已有真实H5缺口、可在本机使用的私有统一日线Parquet物理文件**。试点只覆盖用户明确选择的证券/日期，**不是A股全市场统一库已完成**。

## Windows 单行PowerShell验收

首轮先运行**10项全部虚构合成测试**。全部OK后才在本机调用现有只读批量验证器，对真实两股日线生成**只在模块私有目录**中的新Parquet快照。推荐仍使用之前已经Windows真正准备过、但未activate的版本 SHA：

`46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03`

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-unified-day-parquet-snapshot-20261030; if ($LASTEXITCODE -ne 0) { throw "switch失败" }; git pull --ff-only origin feat/private-unified-day-parquet-snapshot-20261030; if ($LASTEXITCODE -ne 0) { throw "pull失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_materialize_private_unified_day_parquet_snapshot.py" -v; if ($LASTEXITCODE -ne 0) { throw "合成测试失败，停止真实查询" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $snapshot="H5ParquetReconciler\work\unified_parquet\snapshots\snapshot_$rid"; $out="H5ParquetReconciler\reports\private-unified-day-snapshot-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\materialize-private-unified-day-parquet-snapshot.py --source-root "D:\stock" --symbols SH600000 SZ000001 --from-date 2026-09-30 --to-date 2026-10-13 --version-sha256 "46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03" --snapshot-dir $snapshot --safe-report $out --read-only-sources; if ($LASTEXITCODE -ne 0) { throw "真实私有快照生成失败" }; Write-Host "私有统一日线SAFE：$out"
```

如窗口内两股的实际返回数量/组合与先前真实`2 purchased + 8 overlay = 10`相符，下一步即可编写受限的**只读私有快照加载器**，校验manifest/SHA/行键后为未来本地数据使用方提供快速读取。不要预先假设这次返回必然等于旧实测；每次应现场核对数据源与哈希。

**请只回传10项测试终端结果与新SAFE JSON**。不要上传 `day.parquet`、工作目录的真实行情值、原始商业Parquet、H5或market SQLite。

## 未完成项

- 尚未创建全市场持久统一Parquet，私有快照仅为两股的安全物化试点。
- 未批准H5-gap候选金额单位、真实Hikyuu镜像金额取整方案，不能自动从这些候选`float64`生成原生H5。
- 未接入通达信原生日终采集/增量推送/交易日补全。
