# 2026-10-28：3股票共享键列扫描已实证，推进单月多日期一次建定位的有界试点

## 前一轮本机真实证据（用户2026-09-30的三股票安全报告）

股票：SH600000 / SZ000001 / SZ300750，日期2026-09-30，数据仅为购买Parquet 5min。
- 3只股票各有48条5分钟原始时间键，总计144键；分别在18、19、17个
  精确RowGroup有目标键；SH600000逐组ID和计数与旧单股票报告一致。
- 三只股票的Footer独立候选组各47、每股候选行数上限5,685,792；
  理论上分别进行3次独立键列扫描需检查总计17,057,376行。
- 全3股票共享RowGroup并集仍47组，**实际只扫描一次两列共5,685,792行**，
  理论避免11,371,584行重复键检查（**66.67%预算减少，不是物理IO实测**）。
- 实际`source_key_scan_seconds=2.104793`，包括预检的
  `whole_planning_seconds=3.113772`；这不是与3个单股票同期、同OS缓存
  环境A/B跑出的净加速。
- 三股票**真实有键RowGroup并集38组**，只有9组对三股票均无目标键；
  即继续添加股票时，精确行组并集也可能迅速覆盖绝大部分47组。
- Stat-only SHA同此前单股票结果，9份源文件未变；全候选键行已扫完，
  只读两列，所有读取器显式关闭，未读取H5、OHLCVA或更改源文件。

**决策**：单日多股票共享扫描确有减少重复键列检查的结构性收益。
但如果每个交易日都重新扫描同一整个月的大多数RowGroups，仍会重复劳动。
先观察**同一个月的多天是否可用单次有限键扫描**，再决定是否建立
可信的持久月度索引；不要直接扫描2011–2026全量Parquet。

## 本轮新增：多股票×同月日期范围的单次两列扫描

`tools/plan-parquet-5min-multiday-shared-keys.py`：
- 输入2～8个互异合法A股、明确的`--from-date`/`--to-date`，
  必须同一自然月，不超过31个日历日、248个证券日输出项。
- 以源文件真实Footer对**全部股票**进行保守时间/symbol统计筛选，
  形成所有候选组的并集，统计每只股票单独请求的来源行上限；
  所有源文件Footer都按来源清单逐一检查。错误月份的文件必须有Footer
  证明实际时标完全不重叠，才能安全跳过。
- 默认最多30M个并集候选源行、1000个RowGroup、
  每个证券日最多25000键、所有证券日加起来25000键；
  在读数据前完整预检并集预算，任何超限失败退出而不留半成品。
- 在全部并集每个RowGroup上**只读取一次`ts/symbol`**，
  按原UTC+8北京时间解码交易日和分钟键，拒绝重复
  `(symbol, raw_timestamp)`、未对齐分钟、跨区间、统计与真实键冲突、
  不完整行组读取或全体源行计数不守恒。
- 输出所有指定日历日（包括**0键的周末/停牌日**）每只股票实际有键的
  源相对路径/RowGroup ID/匹配数，**不会虚构任何K线**；报告仅包含
  日期粒度统计、不包含来源原始毫秒时标及OHLCVA价量额。
- 所有源文件采用`ExitStack`持有Reader并在成功/异常时
  `close()`；扫描前后用源stat清单核对完整来源文件集合，没有假定
  stat是密码学文件内容指纹。
- 只读源`D:\stock`，仅创建新
  `H5ParquetReconciler/reports/...`安全JSON；
  不创建/复用未经验证的生产索引、不会改现有默认查询、
  不读取H5/私有行情cache、不会自动合并或补缺。

### 科学限制

这份新报告是**可编辑的试点定位摘要，不是受信任的生产索引**。
即使输出每只证券日都有48个5min键，也仅证明原始源键存在，
不验证完整K线价格/量额合理性、停复牌、交易所标准盘中时钟或历史真值。

`theoretical_rows_avoided_vs_independent_symbol_scans`是将同一日期区间
每股独立Footer候选行上限相加再减去一次并集行数；
**不是**以每天独立扫描为基线的N股票×M日期节省，也不代表磁盘IO减少。
真实总耗时取`whole_planning_seconds`，还需与独立单股票/多日期
同机反序A/B的总耗时比较，不能拿旧2.36秒的异时单日结果当严格对照。

## Windows验收命令

仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_plan_parquet_5min_multiday_shared_keys.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

首轮针对**已证实有数据的3只股票和整个2026年9月**，扫描一次完整月份，
而不是先做高成本全股票或全历史扩张：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\plan-parquet-5min-multiday-shared-keys.py "D:\stock" --symbols "SH600000,SZ000001,SZ300750" --from-date 2026-09-01 --to-date 2026-09-30 --max-candidate-rows 30000000 --max-candidate-groups 1000 --max-keys-per-stock-day 25000 --max-total-keys 25000 --read-only --out "reports\pq-202609-three-symbol-month-shared-5min-keys.json"
```

如曾有同名文件，改用`-v2.json`结尾，勿覆盖。
**只上传这份新安全JSON和本机测试总结**；不得上传购买Parquet、
付费价量额、`work/`私有cache。运行结果里对2026-09-30三股票
均应`matching_source_keys=48`，精确有键组数18/19/17，其他日期
是否是48取决于真实数据，不能自动填缺。全部2026-09范围的
源stat SHA应与旧报告相符（在源数据未变的前提下）。

## 后续门槛

- 先确保**2026-09-30子集结果与旧同日共享报告的每组ID和计数相同**，
  验证跨日期一次扫描没有漏掉原本所在RowGroup。
- 检查整个9月各股票日的0键/非常规键天数，找出现实回源核对样本；
  不做全市场完整性结论，也不把非交易日0键误判为源缺陷。
- 比较单次整月规划成本与**多证券×多日期**重复键扫描理论成本，
  再评估共享locator是否需要可验证完整性、失效重建与回源审计。
  若存在实用场景，后续才研究在模块`work/`内的只索引键
  持久层及其安全版本控制，绝不可用未签名可编辑报告直接生产剪枝。
- 历史主数据源Parquet优先、H5只读对照、通达信盘后完整证券日增量层
  和独立回滚机制依然是主线；索引试点不应长期阻塞数据主库工作。
