# H5一分钟缺失后的第五阶段：五分钟跨窗口量额守恒诊断

更新：2026-10-25。仓库：`CrazyA1ice/AStockDataTools`，模块目录：`H5ParquetReconciler/`。

## 一、用户本机最新证据

用户已执行 `tools/validate-5min-against-h5-1min.py`，上传 `5min-1min-independent-2025-09-30.json`。对2025-09-30日五只样本股票：

- SH600000、SZ000636、SH603181、SZ300747：各有48根H5五分钟K线、48根Parquet五分钟K线，但当天**H5一分钟记录均为0**，状态为 `no_records_on_date`，1min→5min无法验证。
- BJ920680：H5五分钟0根、Parquet五分钟48根；H5一分钟证券dataset缺失，状态为 `missing_dataset`，不能误判为逐根量价冲突。
- 四只匹配股票的Parquet/H5五分钟**全天成交量合计比例**分别为：0.9999889、0.9999908、0.9999606、0.9999626。
- 四只匹配股票的Parquet/H5五分钟**全天成交额合计比例**分别为：1.0000025、0.9999998、1.0000039、1.0000003。

上述量额比例与V2报告的逐根开收价和量额存在显著不一致不矛盾，**提示可能存在时间窗口分配/聚合口径差异**，但不能证明是哪一方将某笔成交归到错误的五分钟窗口。H5一分钟缺失并不是交易所分钟成交缺失；这只能表明用户当前H5 1min文件未包含该日该股可用记录。

## 二、本轮新增：五分钟各交易时段量额守恒与相邻窗口消差检验

脚本：`tools/analyze-5min-session-conservation.py`。单日、最多20只股票，本地只读；重用既有Arrow筛选Parquet年度文件及H5五分钟读取，不读取H5一分钟，不再建立大规模SQLite索引。

对于**双方都存在的同一证券与五分钟结束时标**，分别计算全日、上午（09:35—11:30）、下午（13:05—15:00）的：

1. Parquet/H5成交量、成交额合计比例、**净差百分比**与**逐根差异绝对值之和百分比**。如果全天净差很小而逐根总绝对差很大，提示相同总量可能被重新分配。
2. `cancellation_fraction = 1 - abs(sum(Parquet - H5)) / sum(abs(Parquet - H5))`。接近1表示正负差异总量抵消，不代表这些差异一定来自相邻窗口；若为0说明没有可抵消的正负差异。
3. 五分钟相邻窗口中差额异号的对数、连续差额滞后1相关性和累计差额最大偏移。**跨午休、跨股票、缺一个五分钟K线处不允许当作连续相邻窗口**；上午、下午按段单独诊断。
4. 开、收价格不一致时，重新检查H5当前Open与前一根两种来源Close、Parquet当前Close与下一根两种来源Open之间的关系，并提供同源对照，避免仅依据80/80、86/86跨源相等就草率推断具体边界算法。
5. 记录双方OHLC内部几何约束的异常根数，例如high低于open/close或low高于open/close。
6. BJ920680等只有Parquet的股票明确报告`no_comparable_bars`，其差集不进入共有键量额比例分母。

**所有报告都是聚合计数/比值/字段类别，不导出原始OHLCV。** 目前也不依此进行自动冲突裁决或生成H5/Parquet并集。

## 三、Windows验收与运行

在 `D:\ChatGPT\AStockDataTools` 仓库根目录执行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\analyze-5min-session-conservation.py "D:\stock" --date 2025-09-30 --symbols SH600000 SZ000636 SH603181 SZ300747 BJ920680 --read-only --out "reports\5min-session-conservation-2025-09-30.json"
```

严格只在`AStockDataTools\H5ParquetReconciler\reports\`生成新报告；已有JSON不会被覆盖。H5、付费Parquet的`D:\stock`文件仍然只读。

## 四、判读与开发优先级

- **净差小、毛差大、同日内正负抵消且相邻反号较多**：支持量额在五分钟窗口间重新分配的假设，后续再用可靠一分钟或成交明细证实具体窗口边界；仍不能把任一来源当成真值。
- **净差小、毛差大但相邻反号不明显**：可能涉及其他时间段补偿、校验误差、时间聚类问题，不能声称相邻窗口分配已得到验证。
- **上午和下午分别有显著净差，但全天近零**：可能跨午间或收盘边界导致时段间补偿，需要更严格地处理午休/集合竞价；不应盲目平移K线。
- **H5与Parquet共有5min全天净差小，Parquet独有股票有大量记录**：这是不同问题。首先确认差集有效性与股票上市/停牌信息；共有键量额的近似守恒不代表Parquet独有记录可以无冲突复制到H5。
- 用户最终目标仍是**来源可追踪、冲突隔离的H5与Parquet并集库**。等差集与重复键校验完成，可考虑先做明确时间互补部分的只读并集计划，不必要求历史全部量价冲突都已由一个修正公式解决；若尚不明确，冲突保持隔离，绝不擅自覆盖已有来源记录。

本轮新增7项合成测试，原19项核对+10项V2+8项V3+7项本轮，共44项；GitHub合并不代表在用户的Windows环境已全部通过。
