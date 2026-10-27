# 2026-09-28 Parquet五分钟47个RowGroup：先做3组键列成员关系试验

日期：2026-10-27。用户上传`pq-5min-2026-09-28-top3-footer-read-plan.json`：
- Parquet 2026年9个文件、407个RowGroup；`--plan-only`只读元数据；
- 时间范围可安全排除前8个月360个RowGroup；**需要的47组全在`2026-09.parquet`，恰是该月文件的全部47个RowGroup**；
- RowGroup symbol min/max对目标三只（SH688629/SH688017/SH688172）**一组也不能排除**：剩余47组，潜在待解码**5,685,792行**、元数据标注的未压缩大小143,128,330字节。
- 结果与之前实际定向三证券诊断47组、568万行一致，说明Footer成本预检可靠，**但不能证明每组实际上有这三只股票**。从min/max宽泛不能推出每一RG包含每一symbol/day；没必要现在就为整个2026构建V3索引。

## 当前最省钱的决策证据：先读3个RowGroup的两个键列

新增脚本`tools/probe-parquet-5min-rowgroup-membership.py`：
1. 沿用已验证的9月28日单日`h5-parquet-5min-2026-09-28-exact-residual-masks.json`，自动选出原异常top3；**不手填来源未证明的样本**。
2. 使用现有`core.row_group_overlaps_timestamp`+证券别名/minmax剪枝得到原本必读的47组；默认`--max-groups 3`、限制1～8组。对47组固定抽**第0、23、46候选组**（不是随机抽取/不声称代表性），检查目标代码/日期的真实key是否存在。
3. 每个选中RowGroup只读取`ts`和`symbol`两列；复用V3的Beijing timestamp→(交易日、48个五分钟槽位)映射，对目标3只单日统计`source_rows_same_symbol_day`、`unique_regular_five_minute_slots`、`duplicate_slot_rows`；记录异常时间或未识别证券代码的**计数**，不回传具体付费数据。
4. 检验本次扫描的键列行数=对应Footer源行数，避免部分读取假装完整；**仅能证明实际被采样的3组有无目标证券当日的键**。其余44组的真实键分布**未知**，不能据此跳过任何未扫描RowGroup，也不能计算全月准确提速率。
5. 新报告在`H5ParquetReconciler/reports/`、不覆盖同名文件。报告显式`not_a_completed_index=true`、`safe_to_automatically_union=false`；不开H5源文件、不读Parquet价量额、不改变市场文件或正式证券单位判定。
6. 新增6项**纯合成**回归测试：3/47确定性采样、时间与证券元数据保守过滤、目标符号不同来源编码/重复slot、未样本组不可剪枝、异常键计数、字段缺失/行数守恒失败。Windows本机完整测试待验收。

注意：本工具**并非零行扫描**。对3个样本RowGroup需读取约3×12万行的`ts/symbol`两列；与原约568万行的**六列量价诊断**相比，此次只研究抽样行组的键，不扫描原行情OHLCV。

## Windows执行

仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\probe-parquet-5min-rowgroup-membership.py "D:\stock" --date 2026-09-28 --baseline-report "H5ParquetReconciler\reports\h5-parquet-5min-2026-09-28-exact-residual-masks.json" --top-symbols 3 --max-groups 3 --read-only --out "reports\pq-5min-2026-09-28-top3-key-pilot-3groups.json"
```

上传`H5ParquetReconciler/reports/pq-5min-2026-09-28-top3-key-pilot-3groups.json`即可。若已存在请换一个新文件名；不要上传源行情H5或Parquet。**这一步不生成SQLite索引，也不触碰既有2025 V3。**

## 下一步如何根据结果决定

- 如果样本中的绝大多数RowGroup**没有**目标证券9月28日的key，证实`symbol min/max`剪枝过于粗糙，值得考虑**只针对9月相关RowGroup建立可回滚的精确证券/日定位索引**，并配套同源指纹、完整性、异常数据安全阀。因样本不具统计代表性，不能据3组估计最终必读RG数。
- 如果这3组**每一组都含**目标证券当天的K线，说明仅靠symbol/day定位在这些抽样组可能跳不过任何组；先确认供应商Parquet源布局是否真的按交易日集中，避免建立昂贵而收益有限的索引。
- 如果有异常时间/重复slot，需单独检查该月的元数据/源质量，再决定是否索引。**禁止拿未经完整审核的局部索引做自动并集或源覆盖**。
