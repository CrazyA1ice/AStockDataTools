# 2026-10-28：受限多股票同日共享RowGroup键扫描试点

## 研究动机（承接实测）

过去仅SH600000的2026-09-30 Parquet 5min精确定位中，完整候选为47组、
5,685,792条源记录上限，只有18组有48根K线。单证券独立键列扫描
耗时2.361006秒；复用18组在本机A/B中先后表现出1.891～5.377倍
查询速度差异。但快速查询的源stat仅证明文件路径/大小/mtime相同，
旧locator可编辑无签名，不足以直接用于无人值守生产剪枝。

若要为3只股票分别建立证券日定位，**重复扫描同一份源数据的相同
键列**可能浪费时间。与其直接构建2026全月索引，先用一个日期、2～8只
真实A股观察共享扫描收益，再决定是否值得建设全月持久索引。

## 本轮新增的只读试点

`tools/plan-parquet-5min-multisymbol-day-keyscan.py`：

- 接受2～8个互异的A股候选证券、一个明确日期、`--read-only`，
  限制最多30,000,000个候选源行（可调整但原`request_dates`硬上限
  100,000,000）、1,000个组、每只最多25,000个选中键。
- 读取请求年份所有 Parquet 源文件的Footer；错月文件必须有实际
  RowGroup Footer 时间范围**完全无交集**才能安全忽略；各股票分别进行
  保守的时间与symbol统计筛选，形成所有股票候选组的并集。
- **严格先算出并集完整预算、并验证来源文件都在`AllCycleAStockData`
  以内；超过预算立即终止，绝不先进行部分真实键列扫描。**
- 在并集每个候选组上只读取一次`ts`/`symbol`两列，
  全部候选行组（不是抽样）逐批扫描；按北京时间单日+正规minute key筛选，
  校验重名证券、选中键重复、时间错日、每组读取行数完整性、
  per-stock键数上限和整体总行数守恒。
- 记录**每只证券**的独立保守Footer候选行组/源行数上限，以及共享并集
  组数量/行数上限、实际检查的键行数和每只股票真实包含键的行组号与键数；
  只写安全的行组Locator+统计，**不输出原始时间戳、不读取付费OHLCVA列**。
- 读前/读后使用**完整年份所有源文件的stat manifest**检查数据源
  是否变化；使用`ExitStack`确保所有打开的`ParquetFile`在
  **正常完成和任何异常路径**均显式关闭，防止上轮Windows `WinError 32`。
- 新摘要在模块`reports/`下使用`open("x")`创建，禁止覆盖；
  不生成可供无审计生产剪枝的索引、不写`work/`、不触碰旧2025 V3
  索引和H5、不自动融合/导入、不修改`query-parquet-primary-readonly.py`。
- 这只是同日多股票键规划实测。单次扫描的有效性可以逐股票与旧
  `plan-parquet-5min-exact-rowgroups.py`输出对账；**本轮不自动切换
  查询引擎，也不声称实际总延时、磁盘IO或月底索引大小已优化**。

共享union Footer候选源行数上限应不超过将各证券**独立扫描**各自候选组
行数上限之和，报告`theoretical_rowgroup_row_upper_bound_saved_vs_independent_scans`
是这一差值，并**非**实测省下的物理字节或CPU时间。

## Windows本机命令

仓库根目录`D:\ChatGPT\AStockDataTools`：

```powershell
git pull --ff-only origin main

.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_plan_parquet_5min_multisymbol_day_keyscan.py" -v

.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

等完整单测无报错后，针对已知购买源2026-09月，选3个沪深不同板块
且曾在2026年样本内被证实有对应数据的证券：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\plan-parquet-5min-multisymbol-day-keyscan.py "D:\stock" --symbols "SH600000,SZ000001,SZ300750" --date 2026-09-30 --max-candidate-rows 30000000 --max-candidate-groups 1000 --max-keys-per-symbol 25000 --read-only --out "reports\pq-20260930-three-symbol-shared-5min-keys.json"
```

若SZ300750当日无对应数据，报告仍会如实显示0键，
不会谎报缺少或自动补全；不应据此推断整个月缺失。
**仅需回传新生成的安全JSON及测试终端摘要，不要上传购买的原始Parquet、
真实OHLCVA或私有工作目录。**如果输出路径已存在，改用新文件名。

## 验收/未来决策门槛

先核对SH600000这只股票的`matching_source_keys=48`、
`exact_row_groups_containing_keys=18`，与已成功核对的单股票报告一致；
其余股票需根据真实数据单独判断。三只股票共用一次完整
`ts/symbol`键扫描的`whole_planning_seconds`、
`union_source_key_rows_examined_once`，应与单股票日建locator
历史2.361006秒一起评估，但**不是严格相同系统缓存和进程条件下的A/B**。

若所有目标股票组定位与独立基线相符且共享扫描有可观摊销优势，再研究
限定为2026-09、限制内存的完整月度多证券键定位索引；
同时必须建立可靠的来源失效机制、内容校验或有界全量回源纠错，
并明确未经验证的本地JSON无法作为生产自动跳读凭证。
