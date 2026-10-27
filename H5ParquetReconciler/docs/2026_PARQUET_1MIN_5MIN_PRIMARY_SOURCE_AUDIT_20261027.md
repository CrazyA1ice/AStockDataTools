# 2026-10-27：Parquet购入源独立一分钟→五分钟合成核验（主数据源选型）

## 研究目标与当前证据边界

用户拟以**购买Parquet**（2011～2026-09）作为历史主数据源，H5只用于缺口或对照，未来由通达信盘后数据增量更新。前期：
- H5自身一分→五分在2026-09-28三沪市股票144/144根在原容差下一致。
- H5/PQ跨源对齐（候选Parquet五分开始标签↔H5五分结束标签、H5量×100）在四个交易日匹配1,065,216根，任一价格/量/额超容差3,440根，**不能拿跨源一致率来认证Parquet内部的合成方式**。
- 同花顺逐根人工核查有时靠近H5，有时靠近Parquet；其结论不能取代Parquet自身一分→五分的独立周期检查。

因此新增`tools/validate-parquet-1min-to-5min.py`：**只读取同一个购买的Parquet目录下`AllCycleAStockData/1min`与`5min`，完全不加载任何H5。** 默认只取2026-09-28的SH688629、SH688017、SH688172（三只此前跨源存在差异的证券），然后可以扩展到2026-08-24/09-10/09-30及深市、北交所样本。

## 核验方法

**窗口定义的四种候选：**对每根Parquet 5分钟源时间标记T，分别取严格连续、必须实际存在的五根一分钟：
- `five_start_minute_start`：T,T+1,T+2,T+3,T+4；
- `five_start_minute_end`：T+1,T+2,T+3,T+4,T+5；
- `five_end_minute_start`：T-5,T-4,T-3,T-2,T-1；
- `five_end_minute_end`：T-4,T-3,T-2,T-1,T。

对应OHLC：开盘取第一根open、最高max(high)、最低min(low)、收盘取最后一根close；成交量与额分别使用`math.fsum`将5根求和。**任何一分钟时间键缺失则整个五分钟窗口记为不完整，不参加数值符合计数**，不能拿4分钟K线去替代5分钟。

每个候选以整日、上午、下午输出：
- 完整/不完整窗口、四个价格字段符合数、OHLC整体符合数、六字段全部符合数；
- `strict`：浮点绝对容差1e-6、相对1e-10（近似精确）；`existing_tolerance`：沿用前面对账原有price=0.005、量差max(1,1e-5×值)、额差max(1000,0.001×值)，**不能把此容差一致率称为数值完全相等**；
- 成交量同源倍率 ×1、×100、×0.01三项的**非零量窗口符合数**，防止错误倍率或零量样本拉高符合率；
- 五分钟/一分钟量及额之比的p10、median、p90、max，只记录汇总，不导出购买K线数值；
- 重复时间键、非有限数值、缺源、五分钟源标签时间网格异常、OHLC几何、负成交量/额等的可见状态；
- `best_internal_convention_candidate`仅为此日此证券最佳解释；仅在48根5min全有5根1min、六字段全部在**既有容差内**、同源量×1正常、无其它源质量问题时，才将`internal_5min_all_bars_tolerance_match=true`；它**不等于数值逐位相等、交易所权威行情一致或全历史认证**。

扫描复用现有的北京本地交易日时间过滤、代码别名、Parquet RowGroup Footer的时间和symbol min/max保守剪枝，每周期候选源行数默认**上限3000万行**，超额在读取源行情前报错。扫描完成只保存选定股票+日期的一天OHLCVA在本机RAM临时比对，输出JSON没有任何原始OHLCVA数值、无H5读写、无源覆盖、**没有自动并集**。

所有日期和证券的完整覆盖、复权/除权口径以及供应商定版逻辑仍是后续主库的必要校验。**通过内部合成只说明同源周期一致，不能证明交易所逐笔记录必然正确。**

## Windows首轮操作（仓库根目录）

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\validate-parquet-1min-to-5min.py "D:\stock" --date 2026-09-28 --symbols SH688629 SH688017 SH688172 --max-candidate-rows 30000000 --read-only --out "reports\pq-only-2026-09-28-1min-to-5min-top3.json"
```

预期输出：`H5ParquetReconciler/reports/pq-only-2026-09-28-1min-to-5min-top3.json`。只上传新JSON即可，不上传Parquet原始文件。若出现`exceeds --max-candidate-rows`，说明该周期本日候选RowGroup总量超过默认保护值；**不应直接去扫全年**，需先看所报数量、可用磁盘/内存和目的，再考虑小规模提高阈值（最大1亿）；也可以改选更少证券、其他交易日。若2026-09-28的1min Parquet没有当日数据，脚本会输出`not_verifiable_no_parquet_1min_rows`，此时要查实际文件覆盖及月度更新，不允许假称已通过。

## 首轮结果正确后再做跨交易日抽检

为了支持把Parquet真正作为主要历史分钟源，建议再针对：
- 2026-08-24的`SH600000 SZ000001 SZ300750`（若具体证券在这日无数据则换有交易记录者；非股票/上市日期需确认）；
- 2026-09-10的一组`SH688629 SH688017 SH688172`；
- 2026-09-30的一组`SH600000 SZ000001`；
- 北交所股票另择有可靠挂牌日期且两周期均有数据的一只，并核对量纲/时间标签。

建议各日`--out`换成新文件名，**不对不存在或未上市证券强行要求48根**。此时应检查两源周期同日总量、重叠完整性、异常股天比例；仅在核对“价格调整、量纲、时间网格、主库按证券日单源切换与回滚”后，再启动Parquet主库及通达信盘后增量导入。H5保持只读对照。

新增`tests/test_validate_parquet_1min_to_5min.py` **13项合成测试**，其中2项额外使用临时生成的无版权Arrow Parquet文件，专门验证真实两周期读取和在读取前实施行组预算保护；另外测试5分钟结束标记与全零量窗不得认证单位。涵盖四种时标、48根严格/容差一致、错误时标的缺窗、真实缺分钟、OHLC超容差、体量相差100倍、1min源缺失/重复键、量价几何异常、JSON不含源OHLCV。旧测试在用户本机最近成功为180项，后续PR#47（+7）、PR#48（+6）、PR#49（+6）再加本轮（+9）总计**预计212项**，以Windows真实执行的收尾数字为准。
