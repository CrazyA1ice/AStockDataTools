# 2026-08-24 Parquet日线 vs 1分钟/5分钟真实报告：OHLC全严格一致，量额小幅差异

日期：2026-10-27。用户Windows上传`pq-day-vs-minute-2026-08-24.json`，由PR#53中的`tools/validate-parquet-day-to-minute.py`生成，检查购买Parquet同源的SH600000、SZ000001、SZ300750。

## 真实数据结论（不是合成测试）

| 股票 | Parquet day | 1分钟 | 5分钟 | 1min→5min六字段严格 | day vs 两分钟周期OHLC | day vs 分钟量 | day vs 分钟额 | 现有跨周期容差 |
|---|---|---:|---:|---|---|---|---|---|
| SH600000 | 存在 | 241 | 48 | 48/48 | 四价全严格一致 | 严格一致 | 未过严格但**通过现有容差** | 六字段全通过 |
| SZ000001 | 存在 | 241 | 48 | 48/48 | 四价全严格一致 | 严格一致 | 未过严格但**通过现有容差** | 六字段全通过 |
| SZ300750 | 存在 | 241 | 48 | 48/48 | 四价全严格一致 | 未过严格但**通过现有容差** | 未过严格但**通过现有容差** | 六字段全通过 |

来自报告`relative_ratio_day_over_intraday`（两种分钟聚合的值相同）：

| 股票 | 日线量 ÷ 分钟合计量 | 量相对差（近似ppm） | 日线额 ÷ 分钟合计额 | 额相对差（近似ppm） |
|---|---:|---:|---:|---:|
| SH600000 | 1.000000000 | 0 | 0.999999975 | **0.025 ppm** |
| SZ000001 | 1.000000000 | 0 | 0.999999967 | **0.033 ppm** |
| SZ300750 | 0.999992843 | **7.157 ppm** | 0.999999982 | **0.018 ppm** |

1 ppm = 0.0001%。最大相对差来自SZ300750日线量，约0.0007157%。**不能称为源数据逐位数值一样**：严格`raw_all_three_periods_strict_agree=false`对3股均正确，不能偷改为true。计算量额比率来源为原JSON保存的**九位小数**，只能解释到报告精度，不能追溯来源绝对差额或证明源字段小数截断、供应商盘后修订等成因。当前看不到日线/分钟明显数量倍率差异，候选**×1**符合现有容差，×100和×0.01均不符；`source_daily_adjustment_or_quantity_units_certified=false`仍必须保持。

质量证据：三股票日线存在，1min严格241个交易时段含09:30额外开盘键、5min严格48个起始标签，时间网格缺/多均为0；分钟→五分钟每股票48/48六字段严格一致；日线OHLC与1min及5min均四价严格相等；源扫描`duplicate_keys=0`、`nonfinite_source_rows=0`、`invalid_timestamp_rows=0`，日线几何没有异常。读取开销：日线2 RowGroup/117,969源行；五分48组/5,666,976源行；一分钟20组/2,377,661源行。**无需为解读已存在的报告再次读取共8,162,606条源行**。

## 新的无行情扫描离线解释工具

新增`tools/audit-parquet-day-minute-report-offline.py`：
- 只接受先前`Parquet three-period full-day conservation v1`结构JSON，检查报告格式、股票列表/证券日期、三周期元数据、源异常计数与保护标志；
- 分开输出：`strict_ohlc_agree`、`strict_all_six_raw_agree`、`existing_tolerance_all_six_raw_agree`、严格与宽松不符字段；从报告比率计算量额差异的**相对ppm幅度**；
- 另一个**仅用于分析的小差异识别门槛**默认10 ppm（参数`--review-ppm`可变），要求1min→5min严格48/48、全241+48时间网格、日线健康、两个分钟周期OHLC严格相等且六字段均落在原容差内、所有4个量额比率有效且≤门槛、量额×1为候选；输出`strict_OHLC_and_minute_aggregation_small_daily_quantity_gap_review`，**这不是来源官方质量认证或自动入库许可**。不满足则单独标记需调查、不允许把普通容差误称为严格值。
- 离线仅读报告已有JSON，不读H5、Parquet源，不需要重复大规模行组扫描；只保存字段级布尔与ppm，无原始付费开高低收、量、额。不覆盖报告，不自动合并。
- 8项纯合成测试，涵盖0.025 ppm、7.157 ppm、显式门槛收紧、来源状态矛盾、非法比率、缺分钟、异常源、隐私/安全保护。

### Windows使用（位于仓库根目录）

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-parquet-day-minute-report-offline.py --report "H5ParquetReconciler\reports\pq-day-vs-minute-2026-08-24.json" --out "H5ParquetReconciler\reports\pq-day-vs-minute-2026-08-24-offline-assessment.json"
```

输出仅是新安全汇总JSON，**不读取任何行情数据文件**；上传必要时只需新离线报告。旧成功测试基线180，PR#47/48/49/50/51/53各新增7+6+6+13+3+8项，新增本轮8项，若本地均通过则总计**231项**。以Windows实际运行为准，切勿声明本轮测试已经通过。

## 下一步主数据源选择

Parquet历史主源仍是用户已选的优先方向。**这一次仅证明2026-08-24的三股票日线/分钟内部同价、量额偏差很小，但并未证明所有年代、市场或与交易所逐笔100%一致**。下一步可以只再运行一次9月30日的现有day↔minute脚本，然后选择2016/2022少数历史股票日，再进入可追溯的标准化主库（历史Parquet优先、H5补空、通达信盘后新增完整日）。每个证券日的时间标签、原始来源指纹、单位说明与可回滚必须在独立库里保存。
