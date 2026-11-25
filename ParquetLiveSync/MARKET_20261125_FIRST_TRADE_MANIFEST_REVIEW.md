# 2026-11-25 两只股票首成交开盘候选：SHA 固定诊断清单（不入库）

## 已实际验证的上下游

- PR #256/257 的用户 Windows 回执 SHA 是 `72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837`；原 5206 股已接收、9 股隔离；候选 Parquet 的**实际物理 SHA256** 已核对。
- PR #258/259：两只 QMT 原始 241→240 分钟中的 09:30 为零成交占位，折叠逻辑一致。七只 SZ300119–SZ300125 在 11/20、23、24 每只每天 241 行，在 11/25 均 0 行。
- PR #260：用户 Windows 实机 36/36 合成回归测试通过，2026-11-25 22:38 中国时间真实 QMT 缓存查询确认：`SH605336` 首个正量正额分钟 09:32，open=7.62；`SZ300462` 首个正量正额分钟 09:33，open=9.40，**都严格等于官方 DAY open**。二者 09:31 零成交参考 open 为 7.69 / 9.59，完整生产 `normal_qmt_day` 仍然拒绝。不能把“候选吻合”当作“240 分钟数据入库成功”。

## 本 PR 新增的两阶段、安全且无数据写入流程

`audit_market_first_trade_manifest_readonly.py` **仅调用一次已有的** `audit_market_opening_auction_readonly.run_audit()`。后者先校验已有固定运行回执、实际私有 Parquet 哈希、官方 DAY 来源、上游购买校准及生产转换模块 Git Blob，再只读请求两股 QMT 缓存并在内存中运行原生产 `normal_qmt_day`。本新模块不自行另发 QMT 请求或历史下载、不修改原生 241 分钟、不写项目 Parquet/H5、任务计划、隔离回执、财务/复权状态或企微消息。

只允许已观察到的两只/日期/来源组合：
- `SH605336`：09:31 无成交参考 open 7.69、09:32 首正量正额成交 open 7.62、零成交前缀 2 根。
- `SZ300462`：09:31 无成交参考 open 9.59、09:33 首正量正额成交 open 9.40、零成交前缀 3 根。

输出 `FIRST_TRADE_OPENING_CANDIDATES_VERIFIED_DIAGNOSTIC_ONLY` 的条件：
1. 固定正式回执 SHA `72a7104b...`、官方 DAY 覆盖 Parquet SHA `5519a56731a6bdb09b973fcc9ff7cd5b636f325880a94bbf9ee886a505d305e6`、官方覆盖回执 SHA `5bb4616e7d97cf547cded994fefd05fbacc568a2f573a8ff63e5970564496e2d` 全部一致。
2. 09:30 成交量/成交额确实为零，原生行数 241，折叠后 240。原完整 240 分钟校验依然因 `open` 不一致而失败，不得把原异常隐性清除。
3. 首成交时间、首成交 open 与原报告一致；`first_positive_trade_diagnostic` 的严格官方匹配、真实成交 HLC 和后续 HLC 三门槛都为 true，且原始审计 `admission_authorized=false`。
4. 实际重新计算六项 OHLCVA 的容差判断，除了 open 原异常外，其余五项必须在既有容差内；独立 DAY 高低价包络仍不能被突破。
5. 状态仍全部为 `production_merge_authorized=false`、`original_nine_quarantines_retained=true`、`data_quality_cleared=false`、`project_market_files_modified=false`。

程序输出中 `diagnostic_snapshot_sha256` 只针对完整**诊断 JSON** 计算规范 SHA256，`manifest_sha256` 对清单自本体外的字段计算。它**不是**原始 QMT 241 根行情字节 SHA，也不是行情提供商签名；QMT 数据权限、来源独立真实性及修复所需的存储策略尚须后续独立证据。该程序不能成为 PR #243 的 routine continuation 放行条件。

## 本轮测试

在隔离本地目录，用**与 GitHub Blob 完全匹配的文件字节**执行：
- 开盘价原测试 22/22 PASS；
- 七股跨日缓存测试 14/14 PASS；
- 新增候选 manifest 测试 18/18 PASS，包含二次计数、SHA 固定、错误股票/日期/竞价、首成交时间漂移、原失败被悄悄清除、六字段伪造、非有限值、缺显式授权以及无文件写入路径；
- **54/54 PASS**；Python 语法检查 PASS。

新模块 Blob：`9a3dfc49dd5e30ddcd4b38010d55324fd7e1a7ef`；新测试 Blob：`4c0ec1f4c5e06ef66b6ff58f8f2a67ba0f520316`。尚未在用户 Windows 上执行此次新清单 CLI 的真实 QMT 查询；旧 PR #260 的 36 项 Windows 实机测试及两只首成交真实数据已经确认。

## 七只空缓存股票：单独处理

SZ300119～SZ300125 的 11 月 25 日分钟缓存仍为 0，不能简单靠当前只读代码补齐。后续需要严格限制到这七只、`20261125` 单日的 **显式 QMT 自有缓存下载授权**，而不是下发 5215 只重新下载/覆盖，更不能编辑已有私有日候选文件后复用旧 SHA；若未来下载成功，应在新版本化私有隔离区独立重跑 241 原始网格、购买校准、官方 DAY OHLCVA、物理哈希及冲突回滚门禁，仍不自动入库。

**全部 PR 维持 Draft；本阶段未修改 `main`、每日 20:05 定时任务、5215股官方 DAY 或微信/企微推送。**
