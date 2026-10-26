# 2026年五分钟双源成交量100倍线索与并行候选验证

日期：2026-10-26。依据用户本机上传`h5-parquet-5min-2026-09-24-30-quantity-diagnostic.json`及同名Markdown。真实H5/Parquet源均未修改，项目无需重新下载源数据。

## 实测证据（不假设原因）

2026-09-24、09-28、09-29、09-30四天全候选A股双源五分钟重叠键**1,065,216**，H5独有0、Parquet独有4,080（85组整证券日H5无键候选）；总量价冲突1,060,937，OHLC价格冲突1,893，量额冲突1,060,937，量额与OHLC可有重叠，`scan_complete=true`、`issues=[]`。

新上传的`quantity_scale_diagnostics`将原1,060,937个量额冲突精确拆为：
- `volume_only=1,058,125`
- `amount_only=0`
- `both=2,812`
- `neither=4,279`

因此**当前99.598%的量额超容差完全由成交量产生**，独立成交额超过旧容差的仅2,812/1,065,216≈0.264%。

在两侧成交量都非零的1,060,935个重叠键中，有**1,059,453（99.8603%）**的`Parquet.volume / H5.volume`接近**100倍，容差1%**，不在这个候选档内有1,482。双侧均零4,279，单侧为零2。全部1,060,935个非零成交量对在未变换基线的`>5%`相对差档。

在两侧金额均非零的1,060,840个重叠键中，**1,046,098（98.6103%）**接近1倍，其他14,742。金额实际超旧容差2,812（含可能的零值差异），非零金额对0.01%以内456,766，0.01～0.1% 470,248，0.1～1% 119,210，1～5% 11,243，超过5% 3,373。不同阈值的计数不能直接当作同一“金额完全相等”的数据量。

核对现有源码`tools/reconcile-local-a-share-h5-parquet.py`中`store_h5`：H5`transCount`只有在`period=day`时乘100，在`period=5min`时不乘100。由此形成非常强的**候选假设**：H5分钟`transCount`可能是“手”，Parquet五分钟`volume`可能是“股”，但实际上市交易单位和源供应商文档仍未验证。尚不能因为比值≈100直接更改源字段、判定另一个源是错误数据或自动合并。

## 本轮实现：同一批真实重叠数据平行计算一套候选

针对**有界5min且H5/PQ同证券同候选五分钟键**，现在不修改SQLite`h`表里的H5原值、不修改Parquet、也不修改已有`value_mismatch_rows`、`volume_mismatch`、`amount_mismatch`、`price_mismatch`或源时标映射。

在先前`quantity_scale_diagnostics`增加`h5_volume_times_100_candidate`，逐键比较

`abs(Parquet.volume - H5.transCount*100) > max(1.0, 0.00001*max(abs(Parquet.volume),abs(H5.transCount*100)))`

并汇总如下只读聚合：
- `compared_overlap_keys`：候选分母，仅同键重叠。
- `legacy_volume_mismatch`：原比较口径不同计数，必须和旧统计一致。
- `candidate_volume_mismatch`：H5分钟成交量乘100之后，**仍然**超出完全相同容差的数量。
- `legacy_mismatch_resolved_by_candidate`：原口径冲突，但候选比较通过。
- `legacy_match_broken_by_candidate`：原口径通过、候选比较反而冲突。**不隐瞒反例**。
- `candidate_value_mismatch_with_original_price_and_amount_rules`：在H5量乘100候选、而OHLC和金额继续完全采用原规则时，任一字段仍然不一致的键数。与原`value_mismatch_rows`并排比较，不能把仅量额的改善错说为全K线完全一致。
- `candidate_volume_mismatch_by_day`、`by_day.*.candidate_h5_volume_x100_mismatch`及`by_code_prefix_group.*.candidate_h5_volume_x100_mismatch`：能确认是否局限特定日期/候选代码前缀组。全体候选数与原基线及逐日分桶必须守恒。
- `factor_certified=false`、`source_values_modified=false`、`needs_independent_day_volume_and_vendor_unit_validation=true`；无任何单条采购源量价数值被写入报告。

新增3项纯合成测试：单位候选在匹配时确实减少冲突、遇到相反情况也统计新增冲突并保留量价旧值；仅有PQ独有时不得错误把它计入候选；旧day/非有界流程不受影响；中文MD同时显示旧口径和新候选数量。未在用户本地Windows运行，仍须用`unittest`回归确认。

## Windows下一次本机验收

在仓库`AStockDataTools`根目录，用已合并的`main`运行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2026 --periods 5min --from-date 2026-09-24 --to-date 2026-09-30 --universe a-share-candidate --batch-size 8192 --read-only --out "reports\h5-parquet-5min-2026-09-24-30-volume-x100-candidate.json"
```

只能在模块`reports/`生成新JSON和MD，不能覆盖已上传的`quantity-diagnostic.json`。无需重扫2026年10月尾部和旧的单源V3索引。仅需上传该新JSON（也可附测试日志）。检查`results["5min/2026"].quantity_scale_diagnostics.h5_volume_times_100_candidate`：如果候选成交量冲突大幅下降、按日/前缀一致，并且残余误差主要可由单位/数据精度解释，下一轮再用**H5和Parquet相同证券同日的日线总成交量与5min汇总**进行独立交叉验证，结合数据商字段文档正式认证倍数。未经这些证据，`safe_to_automatically_union=false`不变，绝不写原始`D:\stock`。 
