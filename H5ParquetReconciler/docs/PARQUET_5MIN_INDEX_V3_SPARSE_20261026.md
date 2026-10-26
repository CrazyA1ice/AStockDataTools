# 2025五分钟Parquet索引：V1/V2实测复盘与V3稀疏行组列表（2026-10-26）

## 1. 本机实际数据

用户提交了完整的V1/V2前两个RowGroup的JSON、SQLite文件与测试输出。**63项合成测试全部通过**，两版本的源行数247806、候选行数247776、唯一规则五分钟键247776、重复键0、证券—交易日分区120646、逻辑行组定位关系122277均相同，时间标签等异常为0。

我们直接检查了两份SQLite内部B-tree占用：

|指标|V1|V2|
|---|---:|---:|
|SQLite文件字节数|6,074,368（约5.79 MiB）|6,176,768（约5.89 MiB）|
|`daily_coverage`表占用|3,342,336字节|3,342,336字节|
|`row_group_locator`表占用|2,715,648字节|2,818,048字节|
|行组逻辑定位关系|122,277|122,277|
|定位表物理行数|122,277|120,646|

V2的120646条BLOB仅覆盖前2个RowGroup，长度都为1字节。其中单行组01为58136条，单行组02为60879条，同时位于两个行组03为1631条。总计 **119,015个证券—日期分区仅位于一个行组、1,631个分区位于两个行组**，仅1.35%的逻辑关系压缩收益，SQLite文件反而大102400字节。

**因此不能宣称V2比V1更省空间，也不能直接启动522个行组的V2全面构建。** 前2组位图长度短，本身不足以预测后面高编号行组的空间损失。尤其一个分区只出现在第522组时，V2需66字节的绝对位置位图，即使只有1个RowGroup ID。

## 2. V3稀疏定位编码

本轮在 `tools/index-parquet-5min-coverage.py` 中增加**独立V3格式** `parquet-5min-coverage-index-v3`，将每个（证券、日期、源文件）的行组定位从绝对位置BLOB位图改成**按升序存储的无符号LEB128变长整数序列**：

- 每个RowGroup ID编码为 `row_group_id+1`：ID 0—126仅1字节，ID 521仅2字节，不在高编号行组前面填充零字节。
- SQLite `group_id_union` 在行组事务提交时合并两个列表、重新排序去重，允许非连续group ID，保持 `index_matches_and_groups` 查询行为不变；数据编码不合法直接报错。
- `row_group_locator_entries`仍报告**全部逻辑定位关系**，`row_group_locator_compact_rows`仍报告**实际SQLite行数**，`row_group_locator_payload_bytes`代表真实变长列表的字节数；这三个值是客观测量，不能把“物理行数少”误称为总磁盘占用必然下降。
- 源48个五分钟规则时段的 `daily_coverage.slot_mask`、去重公式、源时间异常分类、行组事务 checkpoint、文件指纹与原始许可数据只读均保持原来逻辑。
- V3缺点是某证券在**很多连续行组**出现时需要多个1—2字节的整数编号，可能反而比V2密集位图更大。V3针对稀疏高编号最坏情况优化；究竟哪种整体方案快、占用小，必须在多行组真实测试上比较。

## 3. 绝不覆盖旧索引

V1保留：`work/indexes/pq-5min-2025-a-share-candidate.sqlite`

V2保留：`work/indexes/pq-5min-2025-a-share-candidate-v2.sqlite`

V3新建：`work/indexes/pq-5min-2025-a-share-candidate-v3.sqlite`

*禁止对V1/V2使用V3的`--resume`，也不迁移、合并SQLite文件。* 三个索引同属于 `AStockDataTools/H5ParquetReconciler/`，购买的 `D:\stock` 原始文件全程只读。

## 4. Windows验收：先2个行组，再小幅扩至10个

在`D:\ChatGPT\AStockDataTools`仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --max-new-groups 2 --read-only --report "reports\pq-5min-2025-index-v3-smoke-2groups.json"
```

确认源行247806、候选247776、唯一247776、重复0、stock-day 120646、定位逻辑122277与V1/V2一致；这时V3的位图payload理论上122277字节（V2为120646字节），不承诺V3的2组SQLite文件一定更小。

确认V3功能和数据正确后，适当续建8组，形成累计10组，不要直接跑全部522组：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 8 --read-only --report "reports\pq-5min-2025-index-v3-smoke-10groups.json"
```

检查`row_groups_complete=10`、`index_complete=false`、`row_group_locator_compact_rows`、`row_group_locator_payload_bytes`和平均行组耗时；已扫描10组也不足以保证全年性能和磁盘量。

```powershell
Get-Item "H5ParquetReconciler\work\indexes\pq-5min-2025-a-share-candidate*.sqlite" |
 Select-Object Name,@{Name="MiB";Expression={[math]::Round($_.Length/1MB,2)}}
```

由于V1、V2只索引2组，而V3以后会索引10组，**不能直接比较不同完成组数的SQLite尺寸并得出算法优劣结论**；应只比较同为2组阶段的尺寸，10组阶段用于评估增长速度、重叠比例与运行成本。

所有运行报告及SQLite中间文件仅在 `H5ParquetReconciler` 内。这个工作仍是**索引构建**，非H5与Parquet真正数据并集；索引未全部完成前不得用于快速跳过行组开展自动补录。

本轮预计合成测试64项（原63＋1项增量测试），以用户本机实际测试结果为准。
