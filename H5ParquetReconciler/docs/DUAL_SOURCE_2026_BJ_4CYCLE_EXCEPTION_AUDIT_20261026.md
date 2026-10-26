# 2026-09-29成交量异常：北交所两证券、Parquet缺日线12组的定向核查

更新：2026-10-26。由用户本机两份**已完整运行**的报告归纳：`h5-day-vs-5min-volume-2026-09-29-anomaly-id.json`和`pq-day-vs-5min-volume-2026-09-29.json`。本文没有上传或复制付费行情OHLCV。

## 一、新增真实证据

| 2026-09-29日线—5min成交量对照 | H5内部，5min transCount × 100 / day transCount × 100 | Parquet内部，5min volume和 / day volume |
|---|---:|---:|
| 完整48个五分钟结束时标的证券—交易日 | **5,548** | **5,558** |
| 差≤0.1%（最小绝对容差1） | **5,547（99.982%）** | **5,556（99.964%）** |
| 差>0.1% | **1** | **2** |
| H5旧分钟未归一化 vs 日线乘100的通过数 | **0** | 不适用 |
| 对于Parquet乘/除100的额外备选，通过数 | 不适用 | **两方向均0** |
| 有5min、有day键 | 5,548 | 5,558 |
| 有5min、无day键 | 0 | **12** |
| 扫描是否成功且未写源 | 是 | 是 |

实测H5异常证券日：**BJ920121@20260929**。实测Parquet异常证券日：**BJ920069@20260929**、**BJ920121@20260929**。

报告直接支持：H5内部两个周期使用“日线成交量×100、五分钟成交量×100”的工作规则时极高一致；购买Parquet内部day与5min直接同量纲时极高一致。**BJ920121是两个相互独立数据源都有日—分总量不一致的共同异常**，比仅一方单独错误更需要核查分钟收盘口径、停牌/临时事件或交易统计口径差异，不应直接指定“某一供应商数据错了”。

Parquet的`stock_days_only_five_minute=12`目前只在原聚合报告里有计数而无证券名单，不等于12只股票都漏上市或可以无条件合并。应补齐仅含身份字段的证券—日期列表，再对可能的不同步和数据商发行范围差异作判断。

## 二、本轮新增仓库代码

1. 增强`tools/inspect-parquet-day-vs-5min-volume.py`：在原双源内部Parquet日—分守恒计数之外，输出`missing_day_stock_day_examples`（最多24组）与`missing_five_minute_stock_day_examples`。每项仅包括证券、日期、源记录键数和是否完整48根标准候选收盘时标；保留所有原聚合计数和严格校验。
2. 新增可选`--focus-symbols BJ920121 BJ920069`，为指定1～12只候选证券执行**四条序列的同日交叉证据**：H5 day、H5 5min、Parquet day、Parquet 5min。只读H5所选证券的`datetime/transCount`，采购Parquet仍通过时标页脚筛选及`ts/symbol/volume`三列扫描。
3. `focused_four_cycle_stock_days`逐证券日包含：四周期记录键数、48根时间标签完整性、H5内部原始日—分钟计数守恒、PQ内部日—分体量守恒、H5日线候选×100 vs Parquet日线、H5分钟候选×100 vs Parquet分钟和；同时列出两源5min时间键交集、双向差集和换算后**原严格容差**及0.1%容差的逐根冲突计数、相对误差分桶、最多12个异常结束时间标签。不输出原始行情成交量、成交额、价格或实际金额。
4. 保护现有`scan_complete`、`unit_mapping_certified=false`、`safe_to_automatically_union=false`，拒绝不存在/符号错误的聚焦证券请求、源目录之外的报告路径、覆盖已有报告。新增2项纯合成测试，覆盖BJ共同异常、单源异常、无Parquet day但分钟完整48根、敏感值不进入报告、H5文件缺失及用户输入限制。原5项单源Parquet测试仍保留。

**说明：** 新报告支持证据归因而非裁定。若某个异常同时出现在H5/PQ日分对照中，但两个供应商彼此的分钟成交量都一致，则该异常可能属于共同日线与分钟统计口径不一致；也不能仅凭统计命中声称某笔成交或具体原始K线错误。下一步结合证券上市状态、日线字段定义与A股官方交易时间的证据才能给出结论。

## 三、本机下一步只需9月29日一条检查

仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\inspect-parquet-day-vs-5min-volume.py "D:\stock" --year 2026 --from-date 2026-09-29 --to-date 2026-09-29 --batch-size 8192 --focus-symbols BJ920121 BJ920069 --read-only --out "reports\pq-h5-bj-focused-2026-09-29.json"
```

**上传`pq-h5-bj-focused-2026-09-29.json`即可。** 上一轮H5证券异常身份已确认不必再次运行，也不必重做前4天全市场量价对账；新版同一次扫描即可输出12个缺日线证券日的身份证据和指定两证券的四周期交叉比较。

依然不改`D:\stock`、不自动做数据并集、不开付费CI/大型附件上传。批准并集前须正式认证证券主数据、时间口径、成交量单位及冲突保留策略。
