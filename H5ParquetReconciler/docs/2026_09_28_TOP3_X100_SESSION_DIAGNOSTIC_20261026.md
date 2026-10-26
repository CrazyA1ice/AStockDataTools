# 2026-09-28 精确残余分类后的三证券分时与边界归因

更新：2026-10-26。输入由用户本机完成扫描的`h5-parquet-5min-2026-09-28-exact-residual-masks.json`，以及旧版Markdown（旧`value_mismatch_rows=265354`是**未换算H5五分钟成交量**的原基线，不能错读为换算后的剩余量价冲突）。

## 1. 单日真实证据

2026-09-28 两源5min重叠 266,256 根，H5-only 0，Parquet-only 1,008根（21个**整证券日**×48），无部分日内缺根、无重复键、`scan_complete=true`、`issues=[]`。H5 5min `transCount×100`候选后，完全符合现有严格价量额规则的**265,227根**，任一冲突 **1,029根**（0.38647%）。

8种排他mask：none 265,227；**volume 47**；**amount 2**；**price 117**；**volume_amount 392**；**volume_price 37**；**amount_price 0**；**volume_amount_price 434**。字段边际从互斥计数反推：V=47+392+37+434=**910**，A=2+392+434=**828**，P=117+37+434=**588**；准确一致于前面的离线报告按日边际。

按代码前缀的候选任意冲突：SH_other **535**、BJ **336**、SH688/689 **158**、SZ300/301 **0**、SZ_other **0**。其中北交所113/117根纯价格差；沪市SH_other、SH688/689有大量量额价联合差。BJ在16,272个匹配键中有336个候选冲突（2.065%），不代表已认证的证券板块、不能将其视为数据商故障真值。

## 2. 选择高信息量、低成本的三个证券

旧报告已经给出实际冲突前16名的代码，排前三：
- **SH688629**：33/48根K线触发任一候选量价差；其中`volume_amount_price=28`、`volume_amount=4`、`volume=1`；
- **SH688017**：32/48根触发；`volume_amount_price=25`、`volume_amount=7`；
- **SH688172**：30/48根触发；`volume_amount_price=19`、`volume_amount=8`、`volume_price=2`、`volume=1`。

三只合计**95根冲突K线**（占全日1,029根的9.23%），其中**72根量、额、价三者同时冲突**（占全日434根该类的16.59%）。具有明显的相邻K线差异模式研究价值，但**尚不能证明是单纯跨K线重分配，也不能认证某供应商“正确”**。

## 3. 本轮新增工具及检验重点

新增`tools/analyze-5min-x100-focused-sessions.py`，完全复用经过之前测试验证的`diagnose-5min-alignment.py`源读取和`analyze-5min-session-conservation.py`量额守恒、邻根相关及OHLC边界检查，新增**候选H5五分钟成交量×100**归一化（不修改任何原始tuple）。只需一个**已有的单日精确8mask报告**及`--top-symbols 3`，从报告自动选出排名最前的三个证券，拒绝手写没有事实证据的推荐股票。

逐只证券：
- 四源（匹配H5 5min与Parquet 5min）有界键数、缺根/双侧独有键，**只在两源有相同键的部分**做量价比较；
- ×100候选后的8类mask以及上午09:35—11:30、下午13:05—15:00的互斥计数；**逐证券必须与原单日精确mask报告中的计数逐项一致**，若无法复现代表数据已变化/代码映射变动，直接拒绝生成可信报告；
- 各时段（包括整体匹配键）成交量与成交额的净差、绝对差、相互抵消比例、累积失衡、相邻连续K线的差分相关，跨午休绝不连成相邻交易根；
- 相邻K线边界附近的`open/close`是否接近另一源前/后根的`close/open`，只输出次数与匹配分母，作为时标/分笔归属假设；
- OHLC内部基本几何约束违法条数，**不导出H5/Parquet原始价格、成交量、成交额、源表或每根交易值**；
- 保持`safe_to_automatically_union=false`、`unit_mapping_certified=false`，不修改数据源，不进行“正确供应商”的无证推断。

新增`tests/test_analyze_5min_x100_focused_sessions.py`的5个合成回归测试；最新Windows全部回归待验收。

## 4. Windows下一步只需要三个股票一个日期

仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\analyze-5min-x100-focused-sessions.py "D:\stock" --date 2026-09-28 --baseline-report "H5ParquetReconciler\reports\h5-parquet-5min-2026-09-28-exact-residual-masks.json" --top-symbols 3 --read-only --out "reports\h5-parquet-5min-x100-2026-09-28-top3-sessions.json"
```

**上传`H5ParquetReconciler\reports\h5-parquet-5min-x100-2026-09-28-top3-sessions.json`**；不要重复整四日、全市场对账，不上传收费原始OHLCV。命令会读取选中股票所在的H5数据集，并尝试利用PQ rowgroup time/symbol元数据跳过其他股票；若PQ没有细粒度symbol统计，仍可能读取多个包含全股票的rowgroup，所以不承诺绝对零大文件I/O。

## 5. 下一步再区分北交所价格-only模式

本阶段`exact_field_mask_by_prefix`已经证实BJ有**113根纯价格差**，但未给出对应**真实**证券代码分布。因此暂不臆造BJ代表股票。若top3沪市样本支持边界错位，则做BJ定向`price-only`身份索引（仅symbol/day+分类计数，源只读、只输出聚合）再跑1-3只真实高风险北交所股票。H5 1min的可用性和时标也需独立确认，不能由5min的午间/前后根观察推导官方时标。
