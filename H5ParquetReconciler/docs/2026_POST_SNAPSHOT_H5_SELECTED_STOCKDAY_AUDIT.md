# 2026-10-30：10月14～29日真实购买Parquet未到货后的H5独立股票日核查（只读）

## 真实已验收事实

- Windows `test_append_private_purchased_day_date_delta.py` **14/14 OK（21.029秒）**；真实3只股票（SH600000/SZ000001/SH600519）在2026-10-14～2026-10-29的购买`day` Parquet查询返回**0条**。
- SAFE `reports/private-purchased-new-day-01eb448e2c25.json`：`status=purchased_new_date_not_available_no_partition`、`new_purchased_rows=0`、`new_date_parquet_created=false`、来源文件stat清单共9个文件。`parent_joined_rows_unchanged=15`；历史父分区、原购买Parquet、H5、私有pointer和生产行情查询路由均未更动。
- PR #164 已合并main，`7fb4453`。0个购买新日期**只意味着这3只股票在这次查询的源目录和时间窗中没匹配数据**，不是休市证明，更不能自动宣称H5数据有对应完整日线。此前H5补缺证据只覆盖2026-10-08/09/12/13。

## 本轮功能

新`tools/audit-post-snapshot-h5-stockdays-readonly.py`以同一个已登记的**私有逻辑版本SHA** `bfedbb6b1f538a2a1ec73bb2bc02233290ebdccfc734ba33caa4ff42e2acdf14`作为源边界：

1. 只审计这个父版本已经登记的1～10只股票，日期必须严格晚于该版本最后一天，不得跨年份且1～31天。
2. 用仓库已有`probe-hikyuu-native-day-h5-readonly.py`及`reconcile-local-a-share-h5-parquet.py`的H5日线结构/二分日期定位功能，对`D:\\stock\\HikyuuData\\sh_day.h5`、`sz_day.h5`等**原H5源文件**只读读取所选股票窗口。确认H5Record字段存在、无错误位宽、股票日键`YYYYMMDD0000`合法且不重复、窗口记录有序、原生整数开高低收关系合法、量额整数非负；不将候选量额乘系数写入任何报告。
3. 同时用已验证的购买Parquet`day`只读接口**再独立查询同一个时间窗口**，明确`local_cache=False`，不拿前一轮的无数据SAFE冒充当前实时源证据。每只股票30天以内有界查询，并强制校验购入源只读、安全声明、日期唯一性、OHLCVA合法性。
4. 逐个公历日期生成**只含计数**的脱敏SAFE：`selected_stocks_both_sources`、`selected_stocks_h5_only_candidate`、`selected_stocks_purchased_only`、`selected_stocks_neither_source`，以及汇总。这可直接说明哪些日期在所选股票中存在H5候选，不披露具体股票、价格或商业行情。
5. 核查源H5和购买Parquet文件统计信息（大小、最后修改时间）前后是否变化，并在发布SAFE前重验完整15条逻辑父版本SHA。**文件stat摘要不是源文件字节SHA**，且不会证明整个历史H5排序均正确；源变化/损坏将拒绝发布成功报告。
6. 保留严格边界：`whole_market_date_purchased_absence_certified=false`、`whole_market_h5_date_completeness_certified=false`、`selected_stockday_candidates_authorized_for_staging=false`、`h5_volume_amount_physical_units_certified=false`、`ready_for_full_market_mirror=false`。即便H5返回大量真实股票日，也不能未经独立全市场审计直接建立新Parquet分区、替换原H5、纳入生产查询。
7. 输出只在`H5ParquetReconciler/reports/`新建脱敏JSON，不生成任何Parquet/H5，不改三个不同的私有活动指针。测试输出/临时工作均留在模块工作区，绝不能上传原真实H5或购买Parquet到GitHub。

新增**13项合成测试**，使用临时真实HDF5文件模拟3股不同日期的H5原始整数和购买Parquet来源，并覆盖日期四分类、购买源0条仍只报候选、H5结构错、重复日键、错误日期时钟、无效价格、文件被修改、购买源stat变化、父逻辑版本损坏、禁止超范围股票/日期、报告不可覆盖及越界路径。不需要Windows管理员符号链接权限。

## 本轮Windows受控验收（单物理行）

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-h5-post13-stockday-candidate-audit-20261030; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/private-h5-post13-stockday-candidate-audit-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_post_snapshot_h5_stockdays_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "13项合成测试失败，停止真实H5查询" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\post-snapshot-h5-stockdays-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-post-snapshot-h5-stockdays-readonly.py --source-root "D:\stock" --parent-joined-version "bfedbb6b1f538a2a1ec73bb2bc02233290ebdccfc734ba33caa4ff42e2acdf14" --symbols SH600000 SZ000001 SH600519 --from-date 2026-10-14 --to-date 2026-10-29 --out $out --explicit-source-readonly-audit; if ($LASTEXITCODE -ne 0) { throw "真实H5/购买股票日核查失败" }; Write-Host "脱敏SAFE：$out"
```

**新的13项及真实源H5查询均尚未在Windows执行，PR仍为Draft。**

如果结果确实存在H5候选，只证明**这3只股票**相应日期有H5记录且购买源当时没有这些股票的匹配日线；若下一阶段要填整日，仍必须运行仓库现有`reconcile_section`严格审计整个市场全交易日的购买源缺失、H5全日数量和差集，写新的源报告及离线gate，并让stager在物化前对LIVE源重核，而不是直接把股票日候选变成有效历史库。

如果连H5选定股票也没有后续日期，不应强行运行重型全市场审计：应先找到数据源实际更新日期与正确供应商存储位置。当前仓库主线的全量市场与原生H5金额转换仍未认证，生产H5保持原样。
