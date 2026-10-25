# 2025-09-30 五分钟对齐诊断：时间约定基本确定，首末价与量额仍冲突

## 实际依据

用户已在本地执行 `tools/diagnose-5min-alignment.py` 并上传 `5min-2025-09-30-alignment-diagnostics.json`。样本为 SH600000、SZ000636、SH603181、SZ300747、BJ920680。Parquet当天5只证券共240根（每只48根）；H5前4只各48根，共192根；BJ920680在H5当天为0根。因此数字只代表4只可比股票，不能推广成全市场一致率。

| Parquet原始开始时标偏移 | H5匹配K线数 | 其中OHLC全相同 |
|---|---:|---:|
| -5分钟 | 176 | 4 |
| 0分钟 | 184 | 2 |
| +5分钟 | 192 | 63 |
| +10分钟 | 184 | 5 |

**+5分钟是此次样本唯一能使全部192根H5 K线找到Parquet相同证券时间键的约定，并显著提高OHLC完全相同的次数。** 它支持Parquet开始时标、H5结束时标的工作假设，但不等于所有历史年份和供应商都已认证。

在+5分钟对齐下，192条K线的字段差异为：Open 80条、Close 86条、High 8条、Low 8条。四价全部相同63条（32.812%）。对应一致根数分别是Open 112、Close 106、High 184、Low 184。高低价高度一致，而首末价较不一致，下一步必须判别差异幅度、是否集中在特定证券或上午/下午、是否存在窗口边界的相邻收开价关系。

成交量固定候选倍数H5×0.001、×0.01、×1、×100、×1000中，仅×1有10条匹配；成交额只有×1有26条匹配，其余固定倍数均0条。说明简单常数倍数还不能解释大多数差异，不代表数值一定存在不同交易，也不代表当前H5量纲认证已经正确。需直接检查分位数形式的Parquet/H5归一化比值、两边零量、以及相邻边界的价格构造规则。

## 读取表现与风险

Parquet年度2025共有522个row groups，选取5只股票仍读取全部522组，按symbol或日期跳过都是0；Arrow筛选整个6,408万行耗时约15.3秒，比最初Python循环扫描约131秒明显减少了计算时间，但**若重复扫描很多交易日仍产生重复I/O**。后续需建立时间或证券分区的可复用离线索引，而不是扩大多日反复扫整年数据。

`source_units_certified=false`、`safe_to_automatically_union=false`仍成立。当前报告不包含任何原始OHLCV值，不可用来判定某一来源绝对正确。

## PR #8新增的第二轮诊断

同一只读脚本新增 `working_shift_plus5_per_symbol_attribution`，对每只证券给出：

- H5/Parquet自身行数、+5分钟后配对的行数、四价完全一致数、高低价一致数、高低价一致但首末价不同的数量；
- 各字段**发生差异的K线**绝对价格误差p10/median/p90/max，及相对误差分位数；
- Parquet成交量/H5成交量、Parquet成交额/H5成交额的比值p10/median/p90/max，仅对H5分母非零的记录求比值，另外计数两源零量；
- 上午/下午的匹配与开、收、全四价差异次数；
- 对存在开、收价差异且相邻K线都存在的场景，尝试检验首末价格是否等于**另一来源的前一根收盘价或后一根开盘价**。这仅是统计相关性探针，不能单凭匹配次数决定修正原始K线。

运行（必须使用**新报告文件名**，不能覆盖此前上传的v1）：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\diagnose-5min-alignment.py "D:\stock" --date 2025-09-30 --symbols SH600000 SZ000636 SH603181 SZ300747 BJ920680 --read-only --out "reports\5min-2025-09-30-attribution-v2.json"
```

报告及临时数据都保留在 `AStockDataTools/H5ParquetReconciler/` 内；原始 `D:\stock` 行情不改。当前仍未启动H5/Parquet并集转换。
