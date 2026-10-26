# 2026 五分钟×100残余冲突：由聚合上下界进入单日精确互斥字段类别

更新时间：2026-10-26。**本轮只增加代码和合成测试，没有运行用户D盘原始付费数据**；需用户Windows本机运行验收。完整背景与前一轮只读JSON的严格集合下界见`2026_5MIN_X100_OFFLINE_RESIDUAL_TRIAGE_20261026.md`。

## 一、用户已上传并通过统计守恒的真实聚合证据

此前四个交易日2026-09-24/28/29/30的两源已配对K线1,065,216，H5五分钟`transCount×100`候选后，任一量价差U=3,440（0.32294%）；其中候选量差V=3,097，金额A=2,812，价格P=1,893；U−V=343确定仅金额和/或价格冲突，V∩A≥2,469，V∩P≥1,550，A∩P≥1,265，三项同差≥922。无法从这一JSON推出7种具体互斥类别的精确个数。

| 分组 | 两源匹配K线键 | 候选五分钟成交量残余 | 候选volume差占匹配 |
|---|---:|---:|---:|
| SH其他代码段 | 325,872 | 1,742 | 0.53457% |
| BJ代码段 | 65,088 | 806 | **1.23832%** |
| SH688/689代码段 | 118,272 | 549 | 0.46418% |
| SZ300/301代码段 | 269,760 | **0** | 0% |
| SZ其他代码段 | 286,224 | **0** | 0% |

在SZ两个候选代码组中，只存在**2+1=3条成交额差异**，不是成交量/价格冲突。四日成交量残余依次为09-24 744、09-28 **910**、09-29 832、09-30 611。**选择09-28作为单日精确字段交集的第一步**：有真实残余、数量最多；不因9月28日候选volume数最大而声称总量价残余也最多。

## 二、新增的精确互斥分类

直接在已存在的`tools/reconcile-local-a-share-h5-parquet.py`里重用有界的H5—Parquet SQL键匹配，在候选量`H5_5min.volume×100`与`Parquet.volume`之间保持原严格容差（`max(1, 1e-5×max(Vh,Vp))`），价格仍为逐字段绝对差>0.005元，成交额仍用原先`max(1000,0.001×max(Ah,Ap))`判断。

为**每一个两源同键**计算且仅计算一个互斥mask：

- `none`
- `volume`
- `amount`
- `price`
- `volume_amount`
- `volume_price`
- `amount_price`
- `volume_amount_price`

字段名`exact_residual_field_mask_counts`是这8个互斥类别的**实际逐行精确计数**，不是从V/A/P边际数倒推的模型估计。并新增`exact_field_mask_by_day`、`exact_field_mask_by_prefix`及最多16组`exact_residual_top_stock_days`（仅股票代码、日期、冲突计数和mask计数，不输出任何K线OHLCV原值、实值比率或逐条证券成交量）。`_internal_residual_stock_days`只用于计算和排序，写入报告前删除。

工具在最终完成一个有界扫描时，强制检查：

1. 8个mask必须互斥且合计刚好等于`matched_keys`。
2. 除`none`外7项总和恰好等于之前的`candidate_value_mismatch_with_original_price_and_amount_rules`。
3. 具有`volume`的mask总数恰好等于候选V；具有`amount`的恰等于旧成交额差；具有`price`的恰等于旧OHLC至少一字段不同数。
4. 每一个日期、代码前缀组的8项、各字段边际总量与原扫描逐组统计一致；**只有Parquet有键而H5无键的前缀或日期不能被算作两源匹配组**；跨组8项合计回到全局8项。
5. 如果有计数不守恒，**失败退出、不生成标记成功的报告**，不会伪装成已验证的精确冲突表。

将旧的候选字段计数及生成的历史JSON保持原样，**不在真实源文件里改动量纲**。这是附加报告，`source_units_certified=false`，`safe_to_automatically_union=false`，更不修改`D:\stock`或构建股票并集。

新增4项纯合成测试`tests/test_reconcile_5min_x100_exact_residual_masks.py`：8类互斥测试、跨交易日与代码前缀的守恒、Parquet独有无H5键不假装匹配、恶意改写总/子分组计数则拒绝、日线/其他周期不适用等。原测试不应受影响，Windows最新整套仍需验收。

## 三、Windows只选9月28日，不重扫4天

在`AStockDataTools`仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

全部测试通过后，执行**单日、候选A股代码段**完整但有界的5min对账：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2026 --periods 5min --universe a-share-candidate --from-date 2026-09-28 --to-date 2026-09-28 --batch-size 8192 --read-only --out "reports\h5-parquet-5min-2026-09-28-exact-residual-masks.json"
```

该命令**会读取9月28日对应的H5/PQ 5min K线**（有界，但不是“仅旧JSON离线”），用原已验证的时间转换和严格量价容差获得精确互斥字段分类。Parquet行组元数据可跳过不相关日期的组；不要把它误以为0 I/O。需要避免重新运行四日大扫描。

**上传`H5ParquetReconciler/reports/h5-parquet-5min-2026-09-28-exact-residual-masks.json`**，可进一步核对9月28日候选量差是否回归先前的910条，并分析各种量价相交情况、最集中异常股票日和接下来只读精细核验的目标。若同名报告已经存在，必须换一个新`--out`名而不要覆盖旧报告。无须上传付费原始行情、SQLite索引或大文件。

## 四、后续

如果9月28日的单日互斥结果通过全部校验、与老报告该日的候选V=910及金额828、价格588一致，可以为其余9月24/29/30日提供同方案（是否值得做需看结果），并按`exact_residual_top_stock_days`里的实际异常股票代码调用现有`diagnose-5min-alignment.py`和`validate-5min-against-h5-1min.py`进行更窄的数据源/时间窗独立验证。证券是否真实上市、不同数据商口径和最终来源优先策略需另行认证；不得从mask分类直接启动自动合并。
