# 2026-10-27：本机Parquet冷热查询已实证约69.86倍；开始首次读取Arrow过滤A/B

## 一、用户本机两份真实安全回执

本机`pq-primary-SH600000-20260930-cache-cold.json`和`pq-primary-SH600000-20260930-cache-warm.json`来自用户已安装PR#61的Windows环境，**每次都正确返回SH600000在2026-09-30的48根5分钟K线**、时标09:30～14:55。

| 指标 | cold（首次、写私有缓存） | warm（命中缓存） |
|---|---:|---:|
| `query_elapsed_seconds_this_invocation` | **3.515286秒** | **0.050318秒** |
| `source_rows_scanned_this_invocation` | 5,685,792 | 0 |
| `source_file_footers_opened_this_invocation` | 9 | 0 |
| `matching_bar_count` | 48 | 48 |
| `query_delivery` | `parquet_source_scan` | `local_private_cache_hit` |
| `local_cache_used` | false | true |

单次热缓存查询相对冷查询**约69.86倍更快，耗时下降约98.57%**；这两个数字由本机上述报告实际耗时得出，不是模拟速度。源文件元信息未变、缓存内容已正确命中，保存的缓存内有用户购买的OHLCVA原值，**只留在本机`H5ParquetReconciler/work/primary_query_cache`，千万不要上传到GitHub或作为安全报告发送**。两份`reports/`汇总JSON不含原始OHLCVA。

**不能推广成任意股票/任意日期/批量全部查询都加速69倍**：此结论仅一只股票、一个交易日、已建缓存的单次重复查询；其失效保护基于源文件列表、大小、mtime，非完整文件内容SHA256。首次新股票/新日期仍扫描5,685,792条原行情。

## 二、为何下一阶段不先大规模重排Parquet

此前真实样本V2已经验证：2026年9月的5min源需要47个同月RowGroup才能恢复48根选中K线，扫描约5.69m条。按股票+日期新建永久覆盖所有历史的存储索引可能产生很大的工作副本、开发成本和供应商复权/量纲风险；仍优先保持购买Parquet主源原封不动。

Parquet RowGroup统计与Arrow过滤只是两类不同的优化机会。PyArrow Dataset的`ParquetFileFormat.make_fragment(file,row_groups=[...])`支持仅扫描指定RowGroup，`Fragment.to_batches(filter=...)`可在C++执行过滤，并**可能**根据元数据下推；但是当一个RowGroup内存在大量不同股票的K线时，不能据此自动声称减少了实际磁盘字节或Parquet解码行数。只有实际查询耗时和同源六字段逐行一致可以证明效益。

## 三、本轮增加：单次冷查询双引擎真实A/B工具

新增独立的`tools/benchmark-parquet-arrow-filter-cold.py`：

- 不修改现有`query-parquet-primary-readonly.py`默认查询引擎、**不使用私有缓存**，只对用户显式指定的**单证券、单周期、至多31日**和既有RowGroup读取预算执行一轮A/B。
- 旧引擎仍调用经过真实数据验收的`query_bars(...,local_cache=False)`；实验引擎使用**完全相同的候选Parquet文件和RowGroup清单**，对每个RowGroup创建Arrow Dataset Fragment，基于原始`ts`区间与证券别名过滤，再转换少量选中记录为Python值；保留源文件相对路径与RowGroup，未对5min时标加5分钟。
- 两引擎的实际每根记录必须**连同OHLCVA六字段、时间标签、源文件、源RowGroup都完全一致**；有任何不一致、重复键、非有限数值、异常OHLC、超过安全行组预算或结果条数，**直接抛异常，不会产生“速度对比成功”报告**。
- 输出到模块`reports/`新JSON**仅含耗时、两引擎匹配根数、RowGroup候选数量、Arrow过滤后返回的记录数量、是否完全相同、安全保护声明**。购买OHLCVA仅在本机内存用于等值校验，**从不保存或打印到报告**。
- 严格区分旧引擎确实接收的`source_rows_delivered_to_python_before_filter`与新引擎`arrow_rows_emitted_after_predicate`：新引擎即使只交付48条已过滤K线，**物理解码的源行数和磁盘实际读取字节仍未知**，报告标记`actual_parquet_rows_decoded_unknown=true`、`actual_disk_bytes_read_unknown=true`，不能偷称“物理只读取48根”。
- 支持`--order rowgroup-first`与`--order arrow-first`两种读取顺序；Windows页缓存可能使第二个引擎受益，因此要**反转一次顺序**对照。任何单次A/B耗时优势都不能忽略OS文件缓存、Arrow版本、CPU/磁盘IO变化及统计波动。
- 此工具只是**实验基准，未自动将Arrow替换为正式查询方式，也不代表2026年9月单股单日的cold query已加速**；是否采用取决于用户Windows真实输出及逐根六字段和溯源一致性。
- `tests/test_benchmark_parquet_arrow_filter_cold.py`新增加**7项无版权临时Arrow合成测试**，验证两个引擎逐行价量/时间/RowGroup等价、两种顺序、空结果、重复拒绝、源行和返回条数预算、故意制造价格差异时拒绝报告、错误顺序拒绝。此前预计全仓276项测试，本轮预计**283项**，但需要Windows实际单测输出证明，不可事先宣称283/283全部通过。

**本轮新增（2026-10-27）**：A/B工具现在在同轮双引擎前后核对候选源文件stat清单SHA256（不是内容哈希）；另新增反序汇总验收工具，核对两轮同源stat指纹、查询范围、源行计数、时间值及两轮各自价量源溯源一致性、计时有效性。参阅[反序冷查询汇总审计](2026_PARQUET_COLD_AB_REVERSED_ORDER_AUDIT.md)。原有两条命令无需变化，得到两个新格式摘要后，按新增文档运行比较工具。未收到真实本机结果之前，不宣称Arrow在cold查询中加速。

## 四、Windows验收（只读、不使用本地私有缓存）

在`D:\ChatGPT\AStockDataTools`仓库根目录，先更新与全套单测：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

A/B对照1：原有RowGroup引擎先执行。

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\benchmark-parquet-arrow-filter-cold.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --max-result-bars 25000 --order rowgroup-first --read-only --out "reports\pq-primary-cold-ab-SH600000-20260930-rowgroup-first.json"
```

A/B对照2：Arrow过滤引擎先执行，降低仅由第二个执行顺序得到的虚假加速结论。

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\benchmark-parquet-arrow-filter-cold.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --max-result-bars 25000 --order arrow-first --read-only --out "reports\pq-primary-cold-ab-SH600000-20260930-arrow-first.json"
```

请上传以上**两份安全`reports/*.json`汇总**，不要上传付费缓存与K线文件。验收必须满足每份`matching_bar_count=48`和`query_output_all_values_times_and_source_provenance_identical=true`；之后比较两个顺序的真实毫秒/秒数。若Arrow引擎没有持续优势，保留旧方案，不盲目迁移；若持续改善且结果完全一致，再考虑作为独立可选查询引擎并验证日线/一分钟/早期历史数据。

无论实验结果如何，下一步仍需推进**通达信盘后完整交易日进入独立增量层、来源指纹与回滚**，不写坏购买Parquet/H5。
