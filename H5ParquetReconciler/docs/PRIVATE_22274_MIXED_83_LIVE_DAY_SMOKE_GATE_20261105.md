# 22,274条日线主线：83条混合股票日真实查询验收（2026-11-05）

## 已完成的真实源验收（Windows报告）

- 注册版本：`e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23`。
- 现有`run-purchased-primary-private-22274-day-mainline-live-pilot.ps1` 完成离线证据8/8、八周期私有日线13/13、融合规则15/15，共**36/36**合成测试PASS。
- 已完成一次实际H5/购买Parquet完整来源SHA/键复核，并成功通过八周期显式私有日线查询返回`SH600000` **2026-10-09**一条私有整日候选：
  `PASS_REAL_2026_10_09_SH600000_DAY=1 PURCHASED=0 PRIVATE_WHOLE=1 PRIVATE_MIXED=0`。
- 这是**整日H5缺口**成功，并不能推出**83条混合股票日**或购买来源优先的真实用例已经通过；不得直接宣称可生产合并。

## 本轮开发：真实混合股票日的最小单条样本

- `tools/query-registered-private-day-83-mixed-live-pilot-readonly.py`：
  1. 使用已注册SHA，离线重解析七项实际证据，并检查本地私有配置与当前SHA绑定完全一致；
  2. `KEYS.verified_existing_plan`及`MIXED.read_verified_key_manifest`完整验证原始已注册的83条私有symbol/day键；
  3. **检查2016年恰好1条、2026年恰好82条，排除2026-07-16五条隔离项**，只从2026年安全样本中按(日期、代码)固定排序取第一条；
  4. 在Python内存中以该样本的原始证券标识执行`ALL.query_bars(..., period="day", private_day_evidence=...)`，让现有融合引擎再次做**完整实时H5/购买Parquet来源核验**，精确核对结果应该是购买0、整日H5候选0、**混合H5候选1**；
  5. CLI**只输出候选日期与来源计数**，不将私有股票代码、83条键、OHLCVA或市场值写入Git、公开报告或终端。
- 使用之前已经独立验收的、按SHA注册的原始候选，不重复物化/注册22,274条数据，不改写H5或购买Parquet，不新建生产指针，不改动现有八周期默认查询。
- 真实查询内部沿用现有安全实现，可能生成最多两份不含原始OHLCVA的模块`reports`安全JSON回执，并读取原始市场数据完成实时检查；**并非无扫描的离线演练**。
- 新增`tests/test_query_registered_private_day_83_mixed_live_pilot_readonly.py` **12项仅虚构数据合成测试**，核对83条键分布、隔离日拒绝、A股身份、时间键、配置变更拒绝、来源守恒、匿名输出与拒绝生产激活。
- 新Windows一键入口：`run-purchased-primary-private-22274-mixed-83-live-pilot.ps1`。只运行新增12项测试（不重复先前已通过的36项），重新解析SHA证据后，**只执行一条混合股票日真实查询**。
- **本轮工具与12项测试已提交但尚未经过Windows实机验收**。如来源漂移或股票日元数据不一致，必须失败关闭，不能自动使用过期候选。

## 待完成

- 首次83条混合候选真实样本通过后，再验证购买Parquet已有股票日时坚持购买来源，继续进行官方交易日历、复权因子和约1990年以来的历史日线覆盖范围独立验收。
- 2025 `SZ302132` 供应商历史代码回填及分钟RowGroup性能问题单独保留；**不增加该查询OHLCVA上限，也不阻碍日线主线**。
