# 通用 DAY 证券日清单交叉对照（只读、来源未认证）

## 为什么需要这一阶段

AStockDataTools 是持续管理、清洗、跨源审计与维护八周期行情数据库的工具。2026-11-26 Windows 实机验收已经验证现有 TDX DAY 覆盖的 **222/222** 项回归，以及 2026-11-25 九只隔离股票在同一份 DAY Parquet 中各有一条合法记录、物理文件及回执 SHA 一致。

**关键限制：** 该 DAY 文件有 5,572 行，但不能把 5,572 误当作“交易所当日应交易 A 股股票数”。TDX 源数据可能同时包含不同证券类别；没有独立来源认证，也不能把七只缺失的一分钟数据判为已经恢复。

## 新的长期能力：两份被声明来源的日清单对照

`market_day_universe_crosscheck.py` 使用已经验证的真实 TDX DAY 来源链（`state.json → 单日回执 → 日线 Parquet`），与操作者另外**明确提供**的本地证券日参考 JSON 进行差异分类。

参考 JSON 必须来自用户已经有权限取得的数据；程序不会主动扫描本机目录、爬网、调用 QMT、创建第三方账户或伪造独立清单。给 JSON 起“official”名字、填“FULL_DECLARED”或选择不同的 source_id，都**不是**独立来源、证交所认证或全市场完备性证明。

参考 JSON 格式（完全虚构的测试例子）：

```json
{
  "format": "astock_declared_day_symbol_universe_v1",
  "trading_day": "2025-06-18",
  "source_id": "declared-reference-v1",
  "coverage_claim": "PARTIAL_DECLARED",
  "symbols": [
    {"symbol": "SH600000", "trading_state": "TRADED"},
    {"symbol": "SZ300888", "trading_state": "NO_TRADE"},
    {"symbol": "BJ920021", "trading_state": "UNKNOWN"}
  ]
}
```

`coverage_claim` 只能取 `FULL_DECLARED` / `PARTIAL_DECLARED`；`trading_state` 只能取 `TRADED` / `NO_TRADE` / `UNKNOWN`。输入最多 15,000 个规范化、互不重复的 SH/SZ/BJ 证券代码，JSON 最多 4 MiB。对需要的原始参考清单文件，必须从用户认可的来源证据中取得**该文件真实字节的 SHA256** 并作为单独参数提供。程序先核对文件字节 SHA 再解析 JSON，拒绝目录越界、符号链接、重复 JSON 键、重复证券、错误日期和不合法交易状态。

**TDX 侧**使用原 `market_live_day_overlay_audit.inspect` 的固定日回执来源链，再完整扫描相同日线文件，核验全部行的北京时间时标、规范交易所代码、OHLC 区间和成交量额配对，完成后再核对文件、state/receipt 和参考 JSON 的字节 SHA。需要传一个当日已存在且正成交的 `--anchor-symbol` 来启用原验收入口；不允许强行让所有参考清单证券都必须在 TDX 中找到，否则就无法报告“参考有、TDX 缺”的关键异常。

## 差异类别

- `declared_traded_missing_in_overlay`：参考声明有成交，但 TDX 覆盖没有该代码。
- `declared_traded_zero_in_overlay`：参考声明有成交，TDX 却是零成交。
- `declared_no_trade_but_active_in_overlay`：参考声明未成交，TDX 有正成交。
- `overlay_code_not_in_declared_reference`：TDX 有规范代码，但参考清单没列；**不等同于非法证券、股票多出或 TDX 错误**。
- `declared_traded_and_overlay_active`：双方对“有成交”这一声明一致；仍不是市场行情准确性认证。
- `declared_unknown_present_in_overlay`、`declared_unknown_absent_from_overlay`、`declared_no_trade_absent_from_overlay`：单独记录未知和无成交，不把证据不足误判成没有交易。

`has_declared_conflict` 只指上述**被声明数据之间**的交易状态冲突，不会被解释为来自交易所的真实错误判断。股票代码形状本身不能证实其 instrument type 是 A 股，也不能从该文件推断 5,572 行都是有效股票。

## 只读 CLI

只有在你**确实已有合法的独立参考 JSON 及其预期 SHA**时才执行（示例路径需替换），否则只跑合成回归，不要把现有 DAY 同源数据复制成假“独立来源”。

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_CROSSCHECK_WORKTREE\ParquetLiveSync\market_day_universe_crosscheck.py" --module-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --trading-day 2026-11-25 --anchor-symbol SH605336 --reference-root "D:\PrivateEvidence\DeclaredDayUniverse" --reference-relative "2026-11-25.json" --reference-sha256 "<参考JSON实际SHA256>" --summary-only
```

该命令**不会**下载 QMT 历史、修改 TDX 数据、写 Parquet/H5、发送企微或触发定时任务。对外只读地展示差异类别、数量及最终 JSON 快照哈希；默认 `--summary-only` 隐藏可能很长的逐证券列表。所有真实日线文件均保留原有状态、回执和物理 SHA。

## 认证范围、后续路线

输出 `reference_full_stock_day_universe_certified=false`、`independent_reference_provider_authenticated=false`、`tdx_provider_identity_authenticated=false`、`instrument_membership_authenticated=false`、`source_independence_authenticated=false`，且 `native_qmt_1min_certified=false`、`market_quality_cleared=false`、`market_write_authorized=false`、`market_files_written=false`、`qmt_history_download_calls=0`。

**实际测试：** 在独立 Python 临时目录，开发等价接口的 32 项回归，31 项通过、1 项依赖真实 pyarrow 的 Arrow/Parquet E2E 明确跳过；包含 2026/2027 多日期、错误 SHA、非法 JSON、重复股票、交易状态桶、异常 OHLCVA、文件与参考资料变化、禁用非授权写入以及不冒充独立来源。提交后的新 PR 必须在用户 Windows 上用真实 pyarrow 和仓库全部依赖执行，不能把先前的 222 项通过提前扩写成 **254 项 Windows 通过**。如需要真正的独立交易所股票全集或交易状态认证，后续须另用来源有据的清单和数据商身份链，不能通过此插件自动签发认证。

所有跨日期能力必须沉淀到长期工具和设计文档，而不只是 2026-11-25 的特判脚本；原 5,206 接收、9 隔离、PR #243 的 PARTIAL 保持不变。
