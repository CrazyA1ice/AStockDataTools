# 2025五分钟索引两行组试跑与存储优化V2（2026-10-26）

## 已在用户本机验证的V1试跑

上传的 `pq-5min-2025-index-smoke.json` 显示：2025年Parquet共522个RowGroup，完成前2组，源行247,806，其中A股候选247,776，其他代码类型30；有效证券+时间唯一键247,776、重复键0。时间戳异常、年度之外、非五分钟时标和未知证券代码均为0。生成120,646个股票—自然日分区、122,277条（股票—日期—源文件—行组）定位记录。

该结果说明前**2个行组**能成功建立统计并以checkpoint持久保存，不代表2025全年索引完成，更不能由这两组断言年度没有任何重复键。

V1的存储瓶颈是`row_group_locator`将同一个证券与日期在不同RowGroup出现一次便存为一条独立SQLite索引记录。前两组有122,277条；全年522组如果布局相似，定位关系可能达到数千万条，单纯把第一阶段成功当作全年性能保证风险很高。

## V2改进内容

新的持久索引版本 `parquet-5min-coverage-index-v2` **不改48时段唯一键位图，不改重复键判定公式**，仅把行组定位数据改成：

- `row_group_locator` 主键（symbol，trade_day，file_id），每个股票—自然日—源文件只存一行`group_mask BLOB`。该BLOB采用小端位图，522个行组最多需要66字节位图，不需要为同一股票/交易日反复存储逐组SQLite主键。
- 每次RowGroup完成后在同一个事务内向该位图OR合并新的RowGroup位；此时的年度键统计依然是`SUM(source_rows - bitcount(48时段覆盖位图))`，可检测同正常时段键跨批、跨组、跨文件重复。
- 按日查询通过解码该位图恢复原来的RowGroup编号列表，仍可供原并集预检使用，不改变用户接口`--coverage-index`。
- 年度摘要新增`row_group_locator_entries`（**逻辑行组定位关系数**，便于与V1比较）、`row_group_locator_compact_rows`（V2真正的SQLite物理行数）、`row_group_locator_payload_bytes`、压缩比及不含WAL的SQLite估算占用。
- `--resume`要使用**相同V2索引路径**；V1 SQLite文件不会被升级或覆盖，防止半途中改变索引结构引起兼容问题。V2原始数据读取仍只涉及Parquet的ts、symbol两列，全部中间文件只在`AStockDataTools/H5ParquetReconciler/`，不读取或写出付费OHLCV内容。
- 在采用索引跳过RowGroup前也增加`outside_year`异常检查，避免源文件存在年份偏离记录时错误得出某证券某日没有数据的结论。
- V2使用SQLite写入大量位图UPSERT，**压缩磁盘并不等于已经实测提升CPU速度**。先跑2组验证兼容、空间，再确定522组的执行策略。

## Windows执行步骤（请不要直接跑全年）

从仓库`D:\ChatGPT\AStockDataTools`执行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --max-new-groups 2 --read-only --report "reports\pq-5min-2025-index-v2-smoke.json"
```

V2默认索引路径是：

`H5ParquetReconciler/work/indexes/pq-5min-2025-a-share-candidate-v2.sqlite`

旧V1仍然存在：

`H5ParquetReconciler/work/indexes/pq-5min-2025-a-share-candidate.sqlite`

两者互不覆盖。

在V2单独生成的报告中，校验`row_groups_complete=2`、`index_complete=false`、`unique_regular_session_keys=247776`、`candidate_source_rows=247776`、`duplicate_regular_session_keys=0`；同样应有`row_group_locator_entries=122277`，但物理压缩行数理论上接近120646（具体必须以本机为准）。对新旧SQLite磁盘文件的大小比较时，请在程序退出后通过PowerShell获取真实大小：

```powershell
Get-Item "H5ParquetReconciler\work\indexes\pq-5min-2025-a-share-candidate*.sqlite" |
 Select-Object Name,@{Name="MB";Expression={[math]::Round($_.Length/1MB,2)}}
```

如果测试及V2两组结果正确，再决定是否调用`--resume`处理完522组。之后在`plan-5min-readonly-union.py`中传`--coverage-index "work\indexes\pq-5min-2025-a-share-candidate-v2.sqlite"`，并将新旧单日分类计数逐项对比，确保没有错跳RowGroup。

## 重要边界

V2对最常用的5min年度合法时段做唯一键统计，仍不是官方证券主数据、不保证跨交易所与时区历史一致。没有将任何来源认定为绝对正确，冲突继续隔离，所有源数据库只读。**不建立并集H5/Parquet副本、不上传付费行情。**

本轮单独增加两个压缩索引验证用例，原索引测试9项变11项，全模块合成测试总数由61增加到63项；需用户本机执行确认。
