# 22,274条统一日线：已验收双H5缺口，推进购买Parquet优先真实性核验

## 当前已通过的Windows真实行情证据

- 整日缺口：2026-10-09 / SH600000，`PURCHASED=0 PRIVATE_WHOLE=1 PRIVATE_MIXED=0`，完整H5/购买Parquet实时源键与SHA校验通过。
- 混合股票日缺口：2026-04-08，私有SHA清单确定原始证券（终端不打印），`PURCHASED=0 PRIVATE_WHOLE=0 PRIVATE_MIXED=1 SYMBOL_REDACTED=TRUE`，新增12项合成测试PASS，完整实时源验证通过。
- 当前注册版本`e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23`，总22,274条（22,191整日 + 83混合）。2026-07-16的5条继续隔离。**均只读，未生产合并，未改写原始行情。**

## 本轮开发：购买Parquet源优势必须由真实OHLCVA证明

新增`tools/query-registered-private-day-purchased-first-live-pilot-readonly.py`：
1. 从同一注册版本的7项SHA恢复证据和精确83条私有缺失键中，确定2026年确实存在混合缺口的日期（截至目前实机命中2026-04-08）。精确证券代码全程保留在本机Python内存中，不写日志。
2. 在固定上限10只普通A股的受限清单中，先排除同一日期列入私有H5缺失键的证券，再用**实际购买Parquet原始日线查询**确认有一条真实原始OHLCVA；不能靠预期涨跌或文件名猜测。若均未命中则安全拒绝。
3. 保持相同股票与日期，显式调用已经通过实机验收的`query-purchased-primary-all-eight-cycles-readonly.py`私有日线模式。原实现仍在该请求中执行完整H5/购买Parquet现场源状态、83条键、整日22,191条候选SHA与重叠禁止验证。
4. 对比返回记录的**6个原始OHLCVA浮点值、原始毫秒时间戳、原始文件相对路径、物理RowGroup**，必须与独立购买查询**逐项精确相同**，不得发生H5覆盖、复权、隐式修正或时间移动。
5. `bars_by_source`严格只能是`purchased_parquet=1,private_h5_whole_date_candidate=0,private_h5_mixed_stockday_candidate=0`，所有来源安全字段、生产禁止写入字段完整，错误时失败关闭。
6. 只打印交易日期与聚合来源计数及`SIX_OHLCVA_EXACT`标记；**不打印证券代码、不打印价格、不公开私有83个键**。真实检查过程中可能产生两份已有日线查询约定的非价格SAFE验收回执，不生成任何生产市场文件。

测试：`tests/test_query_registered_private_day_purchased_first_live_pilot_readonly.py`包含12项虚构数据合成回归，检查原始OHLCVA完全一致、H5不覆盖、同日私有键排除、假股票日不能通过、异常价格、时间戳/来源文件/行组不符、原始重复、错误来源统计及禁止生产启用。

Windows一行入口：
`H5ParquetReconciler/run-purchased-primary-private-22274-original-day-priority-live-pilot.ps1`。
只运行新增12项测试，恢复已有SHA证据，然后用一条股票日查询完成**一次新的全量实时来源核对**。这是研究级验收，非生产发布；**最新工具/测试尚未经过用户Windows实机验收**。

## 完成第三类来源验收之后的主线

- 针对2011年以前到约1990年的H5日线，按历史年度和交易所证券键独立盘点覆盖；22,274条候选不能代表1990～2010年历史已经进入统一Parquet。
- 交易所官方交易日历与来源日线年月日时间戳要独立核实（非交易日不应被无来源证据的补缺混入）。
- 日线复权因子与字段量纲（volume/amount/价格）要单独认证，不能把K线周期查询成功等价于复权正确。
- 经全历史范围/质量门禁与备份验收后，才可能计划私有候选并入Parquet生产分区及Parquet→H5镜像；本次不修改市场源或生产指针。
- 2025 SZ302132供应商重标记及分钟RowGroup读取超预算性能问题，继续与日线主线隔离，不再提高OHLCVA预算。
