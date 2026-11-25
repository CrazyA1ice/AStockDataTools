# 2026-11-25 两只股票 09:30 集合竞价开盘价专项取证

## 上一阶段真实证据

用户在 Windows 通过 PR #257 验证：16/16 离线测试通过，Python 经 Windows CRLF 规范化后的 update_market.py Git Blob 与固定值一致；2026-11-25 22:35 QMT 客户端真实连接成功并进行了仅一次 9 只缓存查询。结果：7只 SZ300119～SZ300125 返回零行，2只 SH605336（官方 DAY open 7.62、QMT 原始首条 open 7.69）、SZ300462（官方 DAY open 9.40、QMT 原始首条 open 9.59）返回各 241 分钟，但均被原生产官方 DAY materialized open 校验拒绝。0/9 获得新有效候选。数据质量和隔离均不得自动清除。

注意：原始 QMT 09:30 开盘价不是必然等于实际转换后 240 分钟的开盘价；需要以真正生产的 09:30 处理函数验证。

## 新增内容

- audit_market_opening_auction_readonly.py：显式需 --confirm-two-stock-cache-query。在接触 QMT 前校验原交易日运行 SHA、候选物理 Parquet SHA、两只预期隔离股票、5215只官方日线参考、购买分钟校准 SHA、固定生产模块 Git Blob。仅调用一次 xtdata.get_market_data_ex 读取 605336.SH、300462.SZ 的 20261125 现有缓存分钟数据，count=-1, fill_data=False, dividend_type=none，绝不调用历史下载或市场写入。
- 只在内存中，以原 market_month_storage._fold_241_day 函数折叠 241→240 分钟，随后用原 update_market.verify_materialized_ohlc 与完整 normal_qmt_day 交叉校验。任何结果不同，返回 FOLD_AND_PRODUCTION_VALIDATION_DIVERGED，不作推测。
- 每只输出：09:30 / 09:31 原始 open、09:30 原始成交量/成交额、折叠类型（REAL_AUCTION_FOLDED_TO_0931 或 ZERO_PLACEHOLDER）、真实折叠后 open、官方 DAY open、差值、当下实际容差（rel=0.006、abs=0.04）、原生产拒绝原因。输出官方 DAY 源 SHA 绑定；绝不把「校验一致」当作已修复。
- 测试：14/14 离线 mock 通过，覆盖真实成交折叠、零成交占位、容差、时区和时间网格、代码漂移、证据不匹配、恰好一次限定股票查询、禁止历史下载、禁止项目数据写入；语法检查通过。源/测试 Git Blob 均与本轮已执行测试文件一致。

## 重要边界

1. 本分支是在 PR #257 之上，继承 PR #256 的只读取证模块。所有 PR 均 Draft。
2. 官方日线提供独立参照，但只有源哈希证明数据不被改动，并不自动证明交易所口径绝对正确。需要按 09:30 成交情况与物化开盘价分类后，再决定是否另做交易所/TDX 原始文件复核。
3. 不降容差，不替换 QMT，绝不删除当次隔离证据、覆盖原 Parquet/日线或强行将 PR #243 判为成功。
4. 不发送企微、不注册新行情计划任务。QMT 查询 API 可能更新 xtquant 本身的缓存/日志，无法承诺客户端完全零副作用。
5. 本地离线测试通过不代表已在用户 Windows/QMT 上取得实际 09:30 数值；首次真实查询仍需用户在已安装 QMT 的 Windows 环境执行固定 SHA 版本。

## 后续决策

- REAL_AUCTION_FOLDED_TO_0931，且转换后仍高于官方开盘：真实 09:30 成交已保留，不能以「算法丢失集合竞价」解释，需要核查官方 DAY 来源、原始 QMT 09:30 开盘价与复权口径。
- ZERO_PLACEHOLDER，转换后 open 来自 09:31：需要以独立、可信的 09:30 开盘成交证据判断是否 QMT 源缺少集合竞价；不能凭同日收盘价猜测。
- 若折叠与完整验证不一致：保留隔离，先审计算法及版本漂移，绝不继续修复。

目前无写库修复授权流程，只有只读取证流程。
