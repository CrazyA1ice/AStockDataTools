# 通用隔离股票日修复准备度证据矩阵（只读）

AStockDataTools 的长期目标是跨日期、证券、数据源与八周期的行情清洗管理，而不是单独修复某一日。新增 market_quarantine_recovery_readiness.py，将真实生产每日暂存回执、质量规则/稳定事件 ID 和本地 TDX DAY 状态→回执→Parquet 证据合并为逐隔离证券日的修复阻塞原因清单。没有写库、没有后台任务、没有调用 QMT、没有申请外部供应商账号。

## 证据来源和真实含义

- QMT 生产每日暂存的 JSON 与已接收候选 Parquet 经过实际字节 SHA 比对；已接收候选 SHA **不等于被隔离的 QMT 原生 1 分钟数据 SHA**。
- 通用质量规则/待办输出保留每个原隔离的日期、证券、周期、来源和已检测规则，引用既有稳定 incident ID；不能因为某个后续来源检查通过就自动关闭旧隔离。
- TDX DAY 覆盖链只读核对 work/state.json、选定日回执、物理 DAY Parquet SHA、schema 和目标证券的真实合法日线成交记录。TDX 原始 ZIP 的 SHA 仅为回执中的声明值，本模块没有核验 ZIP 实际字节。
- 官方交易日证券全集、TDX 提供商身份、原始 QMT 分钟来源、购买源分钟校准、六字段分钟↔日线、全部八周期和正式修复事务均仍未认证。

每个证券日输出原 producer receipt SHA、已接收候选 SHA、TDX 状态/回执/DAY 文件 SHA（如有）、当地日线开盘价、原检测问题、尚未满足的证据阻塞项及下一只读审核方向。状态永远保持 BLOCKED_REVIEW_ONLY_NO_REPAIR；生产合并、QMT 历史下载、市场写入和自动清隔离权限均为 false。

## 可复用、严格的失败规则

默认一次最多 64 条原隔离记录，上限允许显式设为 128；超出 fail-closed 而不截断。日期区间继续由原 producer adapter 限制为不超过约 180 天。审核后会重新读取整个窗口的原生产回执和候选文件实际 SHA；同日多股票的 TDX DAY 来源 state/receipt/Parquet SHA 必须完全相同。

只有“该日期不在当前 DAY 覆盖模块范围、该日未登记、目标证券不在 DAY 文件里、目标 DAY 无活跃成交”四种特定情况才可标为本地参考证据缺失；这些都**不等于证券实际停牌或应当移出股票集合**。凡是状态篡改、文件 SHA 不符、schema 损坏、回执错误、未知异常，一律停止，绝不把坏证据伪装成无行情。

原 OHLCVA 冲突证券后续可单独申请原生 QMT 首笔成交只读复核；其他隔离可单独申请来源/缓存覆盖核查。以上仅为建议名称，本模块绝不调用历史下载、不填补分钟数据、不修改 QMT 自有缓存，也不更改 5,206 条已接收候选与九条隔离。

## 只读运行方式

Windows 中使用 SHA 固定的独立工作树，正式 module-root 必须指向本机已有生产数据目录（下方工作树占位需替换为实际固定版本）：

    & "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_REVIEW_WORKTREE\ParquetLiveSync\market_quarantine_recovery_readiness.py" --module-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --start-day 2026-11-25 --end-day 2026-11-25 --summary-only

此日期只是用户已提供回归记录的样例，不是算法内的固定日期。移除 --summary-only 可展示逐个股票日的阻塞项与原稳定事件 ID。程序仅打印结果到标准输出，不持久化报告。

## 已有验证与尚未完成部分

前置 PR #270 固定提交 ad1dee94bf1732e9fb5b4256d8b373841e60b227 已在用户 Windows 通过 279/279 项实机回归，真实九只隔离、47 个事件及代表股票 DAY 来源链未改变。

本轮新增 29 个测试方法，使用本来就存在的生产回执和质量模块契约，测试合成的回执+候选字节、跨日期、两种隔离原因、来源漂移、坏证据、缺证据、重复 case、有限审计预算和 CLI 无私有路径泄漏。**目前这 29 项仅已编写并提交，尚未在用户 Windows 上执行**，不能宣称 308 项已经通过。

下一阶段先做 Windows 308 项联测和原九只股票的真实只读证据矩阵，随后再设计独立审核的版本化私有修复候选及可回滚事务，不能提前解除 PARTIAL 或入库。

新增第 29 项为真实临时 Arrow DAY Parquet、state/receipt 文件及原 QMT 生产格式暂存回执的完整只读 E2E。依赖用户本机既有的 pyarrow 26.0.0，在本轮工具环境尚未执行；它不会使用真实 QMT 或修改生产行情。
