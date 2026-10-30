# 2026-10-30：私有统一Parquet的实际增量物化——增加新股票，不复制原有10条日线

## 已验证前置

- Windows `test_version_private_unified_day_parquet_snapshot.py` **14/14 OK（3.523秒）**。
- 已有真实私有两股日线快照`snapshot_ffc5c35e7e00`（购买Parquet 2根、H5完整缺失日候选8根）登记成**不可变私有快照版本**：
  `d625c323406ca92cb05c98e731a6920cbeeb14128e2175cc9f7b46e44946f207`。
- 本地`prepare`输出`rows=10`、`previous_version_sha256=null`、`private_snapshot_pointer_changed=false`；`status`输出`active_version_sha256=null`，没有启动任何生产或私有活动查询。
- PR #159 已合并main（合并提交`999fb615`）。此前H5-候选金额的原始整数0/2无损、半偶舍入2/2匹配只是小样本证据；**不认证供应商金额物理量纲或生产H5写入策略**。

## 新增：实际“新增股票集合”的数据分区（不是只新增报告）

新工具`tools/append-private-unified-day-symbol-delta.py`：

1. **父版本必须真实已经通过SHA登记**，显式传入上面64字符父快照版本 SHA。内部用已验收的`version-private-unified-day-parquet-snapshot.py`的`load_version`、`check_version_snapshot`，再次验证原先私有Parquet/manifest/SAFE的全部行与哈希。父快照文件不会复制、重新编码或修改。
2. 允许选择**1～5只此前不在父快照里的新股票**；日期窗口严格沿用父快照的原窗口，且新股票不与父`per_symbol_counts`重复。整个有限试点合并股票数量不能超过10。**本轮属于增加股票覆盖，不是增加新交易日；新日期增量另立阶段，避免把两种增量混为一谈。**
3. 显式同一私有`origin_private_version_sha256`作为已有H5整日缺口overlay来源。复用已在Windows验证过的`query-parquet-primary-day-overlay-batch-readonly.py`：先现场验证购买Parquet新日线是否优先，已购买整日有数据则不会从H5覆盖；已审计的H5整日缺失部分才可补充；对4个H5候选日重新做现场source-date审计。所有源文件仍严格只读。
4. 经`materialize-private-unified-day-parquet-snapshot.py`既有严格`normalize_rows`复核来源、股日唯一键、窗口范围、字段有效性与计数；新返回为空立即拒绝，不生成虚假增量。
5. 新增记录**物理落盘**到全新的`H5ParquetReconciler/work/unified_parquet/snapshot_deltas/delta_<12..32位hex>/day.parquet`，实际Arrow往返对比全部OHLCVA，SHA256绑定元数据`manifest.json`；父10条Parquet丝毫不触动。不创建/切换私有快照或生产查询活动指针。
6. 模块`reports/`另生成脱敏聚合SAFE，明确增加行数、购买与H5补缺来源计数、父版本SHA、增量SHA；**任何用户真实OHLCVA、原始成交额或市场源绝对路径均不出现在SAFE**。
7. 若真实数据源/父快照/私有overlay在生成过程变化，fail-closed拒绝生成成功SAFE；若写入私人目录后发生磁盘故障可能留有未认证的未完成目录，下游必须要求合法manifest+SAFE哈希才能消费，不得视为成功写入。
8. **增量文件还没有和父快照组成一个新的逻辑可读版本**：本轮交付独立Parquet物理增量和父版本绑定，下一轮将做父+增量的联合只读解析与不可变版本递进；不谎称全市场/新交易日/自动盘后更新已经完成。

## Windows单行验收：虚构12项全部通过后执行一个真实新增股票

父快照的原窗口固定为2026-09-30～2026-10-13，原已有股票为SH600000和SZ000001。选择新股票**SH600519**作为独立小范围试点（不是数据存在性的预先保证；若新股票在源中确无记录，工具安全拒绝，不生成SAFE）。

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-day-parquet-new-symbol-delta-20261030; if ($LASTEXITCODE -ne 0) { throw "切换失败" }; git pull --ff-only origin feat/private-day-parquet-new-symbol-delta-20261030; if ($LASTEXITCODE -ne 0) { throw "pull失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_append_private_unified_day_symbol_delta.py" -v; if ($LASTEXITCODE -ne 0) { throw "12项测试失败，不读取真实源" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $delta="H5ParquetReconciler\work\unified_parquet\snapshot_deltas\delta_$rid"; $out="H5ParquetReconciler\reports\private-day-symbol-delta-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\append-private-unified-day-symbol-delta.py --source-root "D:\stock" --parent-version "d625c323406ca92cb05c98e731a6920cbeeb14128e2175cc9f7b46e44946f207" --overlay-version "46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03" --new-symbols SH600519 --delta-dir $delta --out $out --read-only-market-sources; if ($LASTEXITCODE -ne 0) { throw "真实新增股票私有Parquet物化失败" }; Write-Host "新SAFE：$out"
```

**本轮新增12项合成回归尚未Windows验证，故PR保留Draft。** 成功时请提交终端结果及新SAFE JSON，无需也不应上传`day.parquet`、购买商业行情或原生H5。若测试失败，自动停止真实数据查询并上报报错即可。

## 安全与待做

- 真实日线来源为购买Parquet优先、已验证H5完整缺日候选；H5补缺的量/额单位依旧是待官方核对的候选解释，绝不能把目前试点输出直接纳入生产Hikyuu原生H5。
- 物理增量只是一个新的私有`work/`文件，不是自动发布。不会修改`D:\stock\AllCycleAStockData`、`D:\stock\HikyuuData`或`active-private-snapshot.json`、`active-day-overlay.json`。
- 后续：父+增量的只读拼接验收，支持按股票快速查询及版本升级；再实现**真正新交易日增量**（需真实新增购买行情或经独立审计的H5缺日），之后再研究原生H5镜像和通达信盘后增量来源。
