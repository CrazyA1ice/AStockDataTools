# 2026-10-30：真正新的交易日期——购买 Parquet 优先的私有日线增量物化

## 已通过的真实前置验收

Windows `test_query_private_joined_day_by_version_sha_readonly.py` **16/16 OK（21.229秒）**。本机用**一个不可变逻辑版SHA** `bfedbb6b1f538a2a1ec73bb2bc02233290ebdccfc734ba33caa4ff42e2acdf14` 直接读取3只股票、15条日线（购买Parquet3、H5已经审计的整日缺口候选12）。上传的脱敏SAFE `reports/private-logical-sha-read-423975e70449.json` 记载 `logical_version_parent_delta_parquet_manifest_and_safe_sha_verified=true`，从未读取/更动原市场文件和活动私有指针，`no_live_market_source_freshness_recheck=true`。PR #163合并main，提交`81706893`。

过去反复研究同一15条历史行情至此结束。下一步直接对后续日期查询真实购买数据，进而增加实际物化增量行。

## 新交付：`append-private-purchased-day-date-delta.py`

- 明确以刚才已SHA登记的15根逻辑版本作为**父视图**。检查版本JSON、原父快照、SH600519新股增量Parquet/manifest/SAFE的SHA及全部行完整性，禁止替换来源；父视图的股票集必须包含所有本次请求股票。
- 只能请求**严格晚于2026-10-13的日期**，同一年、连续窗口不超过31天，1～10只原逻辑视图内的不同A股代码。首轮推荐2026-10-14～2026-10-29的3只股票。
- 直接调用已维护的`query-parquet-primary-readonly.py`中`query_bars(...,period="day",local_cache=False)`，对新窗口采购的**原始日线Parquet**做受预算的现场读取。H5原生市场数据**完全不读取、不调用、不用作缺日填充**。对购买源实际返回的每条日线检查有效股票、唯一`股票+交易日`键、毫秒UTC+8日期、OHLCVA有限且合法、原值无数量/金额单位重标定。
- 用`private-parquet-query-cache.py`已经实现的**只读文件stat清单SHA**，在多股票查询之前、之后及发布SAFE前检查整个购买day来源文件清单的尺寸与最后修改时间是否一致。重要：这种stat证明**不是源文件内容SHA或交易所/供应商真实性认证**。若数据源在扫描期间变化，拒绝报告成功；真实商用源不会写入。
- 查询返回有新日线时，只在全新`H5ParquetReconciler/work/unified_parquet/date_deltas/date_delta_<hex>/`写入`day.parquet`及私有`manifest.json`，PyArrow全量写读原值一致后建立SHA证据。历史父Parquet10根和新股delta5根**完全不动**，不启用任何活动指针或改生产查询路径。新日期分区暂不自动加入老逻辑SHA，后续阶段才加入新增日期版本。
- 如果源文件中**根本没有10月14～29的新日期数据**，生成状态`purchased_new_date_not_available_no_partition`的**脱敏SAFE**，准确记录`new_purchased_rows=0`、`new_date_parquet_created=false`，**不创建空Parquet分区**。这不等于交易所期间休市，不等于该日原H5必然存在或任何日期已获得H5缺日审核许可。
- SAFE只写新日线计数、请求区间、父SHA、新分区Parquet/manifest SHA、来源文件**stat摘要hash**以及“没用H5、未修改生产、单位候选未经认证”等声明。不输出原OHLCVA、交易金额、实际股票代码、市场绝对路径；`work/`和`reports/`均由Git忽略。CLI只打印行数/是否创建分区。
- 若写入新私有分区后源数据被改变，程序拒绝生成成功SAFE。可能有未认证的目录遗留，下游读取时**必须要求合法SAFE/manifest/Parquet SHA**，不得把目录存在视为真实成功。

## 本轮暂不做的事情

1. **不自动拿原H5填10月14日以后的缺口**。此前私有H5缺口审核仅涉及2026-10-08、09、12、13，不能把审核结果扩大至后续所有日期。
2. 不构造任何伪造的新日期行；购买源没数据就如实反馈“当前不可用”。
3. 不从新物理分区直接创建正式生产原生H5，供应商数据金额的真正物理量纲和有损整数取整问题仍未解决。
4. 不根据本地私有活动版本指针判断默认行情，它们仍保持未激活。
5. 如果确有新增日期数据，下一步创建**父逻辑版本+新增日期Parquet**的SHA绑定增量v3只读视图/版本继承。若购买Parquet尚未到货，则下一步需要**独立审核新增日期的H5全日完整性**后才能扩展H5补缺来源。

## Windows验证（单物理行）

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-purchased-day-new-date-delta-20261030; if ($LASTEXITCODE -ne 0) { throw "切换失败" }; git pull --ff-only origin feat/private-purchased-day-new-date-delta-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_append_private_purchased_day_date_delta.py" -v; if ($LASTEXITCODE -ne 0) { throw "14项合成测试失败，不读取真实新日期" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $delta="H5ParquetReconciler\work\unified_parquet\date_deltas\date_delta_$rid"; $out="H5ParquetReconciler\reports\private-purchased-new-day-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\append-private-purchased-day-date-delta.py --source-root "D:\stock" --parent-joined-version "bfedbb6b1f538a2a1ec73bb2bc02233290ebdccfc734ba33caa4ff42e2acdf14" --symbols SH600000 SZ000001 SH600519 --from-date 2026-10-14 --to-date 2026-10-29 --delta-dir $delta --out $out --read-only-purchased-source; if ($LASTEXITCODE -ne 0) { throw "真实新交易日期购买源检查/物化失败" }; Write-Host "脱敏SAFE：$out"
```

**新14项纯虚构测试及真正10月14日后行情尚待Windows运行，此PR Draft。** 可能的两种正确结果：有购买日线→实际创建新`day.parquet`；没有购买日线→只给出真实`no_partition`状态SAFE。两种结果都不会把缺口伪装为可认证H5数据。

完成后只上传终端结果与脱敏SAFE JSON；不要把私有新Parquet、已有购买Parquet/原H5或真实价格数据上传GitHub。
