# 2026-11-25 七只 QMT 1min 空帧的四交易日只读覆盖调查

## 实机原始证据

用户在 2026-11-25 22:35 中国时间执行 PR #257 的固定 SHA 真实 QMT 缓存查询。16/16 Windows 离线测试通过，原运行 SHA 为 72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837。QMT 连通，5215只官方 DAY，5206只已接收，九只隔离；其中七只 SZ300119、SZ300120、SZ300121、SZ300122、SZ300123、SZ300124、SZ300125 的 2026-11-25 原始一分钟数据均返回 0 行。两只 SH605336 和 SZ300462 仍为官方 DAY 开盘价冲突，由前一阶段 PR #258 独立处理。

不能仅凭空帧判断是券商权限问题、QMT 本地缓存未下载、当天延迟、证券停牌还是接口口径问题。原生产 fetch_qmt() 确实尝试先 download_history_data 再 get_market_data_ex，但不能从该事实推导出下载已成功。

## 只读取证范围

新增 audit_market_qmt_seven_coverage_readonly.py：

1. 显式要求 --confirm-seven-symbol-cache-query。在进行 QMT 请求前核实原始运行 SHA、九只隔离元数据、实际私有候选 Parquet SHA、七只预期 QMT 缺失证券、当日5215个独立官方 DAY 参考和生产相关模块的固定 Git Blob。
2. 仅调用一次 get_market_data_ex，代码严格固定七只股票，交易日窗口为 2026-11-20、11-23、11-24、11-25；period=1m, start_time=20261120, end_time=20261125, count=-1, dividend_type=none, fill_data=False。不调用 download_history_data，不写行情、H5、Parquet 或市场账本。xtquant 自身可能记录日志/维护缓存，不能保证其私有目录完全无副作用。
3. 只对返回的分钟条目调用原生产 normalize_frame 做时间/价格结构解析，按日期计算行数，分类为：
   - QMT_WINDOW_EMPTY：四个交易日均无条目
   - OLDER_CACHE_PRESENT_NOV25_EMPTY：之前交易日有数据但 25 日仍缺失
   - QMT_STOCK_KEY_MISSING：接口没有返回该证券
   - NOV25_CACHED_FULL_GRID_NOT_VALIDATED：25 日现在出现完整 240/241 分钟网格，但尚未用官方 DAY 与购买校准验收，更未入库
   - NOV25_CACHED_PARTIAL_GRID_NOT_VALIDATED：25 日数据不满足原有全日网格
   - QMT_CACHE_FRAME_INVALID：返回帧异常
4. 所有分类 data_repaired=false；即使某只股票后来有了完整 241 分钟，也不能自动清除原隔离或直接补入既有 Parquet。

## 验收边界

本轮独立模拟 14/14 单测通过、Python 语法检查通过；包括仅一次七股缓存请求、无历史下载、原运行/官方日线证据不一致时提前停止、缺失股票键、空窗、前几日有数而25日无数、240/241 完整但未经校准、异常网格等。代码与测试文件 Git Blob SHA 已对照本轮离线已执行的文件，完全匹配。

依赖 PR #258 / #257 / #256，全部 Draft，新增内容与 20:05 正式任务完全隔离；尚未在用户 Windows 上执行真实四日 QMT 缓存查询。

如果有较早交易日记录而 25 日无记录，可考虑经授权独立试验针对25日的重新下载，但绝不在本审计中执行；如果全部日期为空，应先核实对应 QMT 安装实例、权限与服务端行情范围，再决定是否申请额外数据服务；不自动伪造分钟 K 线。
