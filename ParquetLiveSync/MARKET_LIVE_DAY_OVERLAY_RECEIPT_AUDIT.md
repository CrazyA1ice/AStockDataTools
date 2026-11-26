# 跨日期 TDX DAY 覆盖数据的状态—回执—物理文件内容审计（只读）

本工具属于 AStockDataTools 的长期行情管理、清洗与质量治理，不以 2026-11-25 或九只隔离证券作为内核参数。它复用既有已验收的 DAY Parquet 内容验证，以及 `live_sync.py` 的正式数据状态格式，检查任意 **2026-10-13 基准日之后、已经收入 live_sync 覆盖账本**的指定交易日与指定证券。

## 真实来源链

实际代码 `live_sync.put_day` 会建立以下内容：

1. `ParquetLiveSync/work/state.json`：固定 format、基准数据集 SHA、day 日期和每个已接收日的文件、物理 SHA、行数、回执 SHA、**回执声明**的 TDX 原始 ZIP SHA。
2. `ParquetLiveSync/work/incremental/day/year=YYYY/YYYY-MM-DD.json`：记录 date、file、sha256、rows、raw_zip_sha256、base_dataset_sha256、源 URL 声明与校准。
3. 同名 `.parquet`：真正包含 DAY 八列数据，用 `local_layout` schema 和按北京时间转换的真实日期、规范化证券、OHLCVA 检查，前后重复检查物理 SHA。
4. 可选原始 ZIP：只有操作者主动传入 `--raw-zip-relative` 且这个路径位于上述 work 目录中时，才计算实际 ZIP **文件字节 SHA** 并与原回执的 raw_zip_sha256 对比。**不主动搜索 ZIP、下载源行情或申请外部账户。**

此次新增 `market_live_day_overlay_audit.py`：先读取并 SHA 固定 state，严格检查一条已有的已接受日映射；核对同名回执的物理 SHA 与所有核心身份字段；调用已验收的 `market_official_day_content_readonly.inspect_explicit` 完整读取该单日声明文件并复核 OHLCVA、目标证券，最后再次检查 state/receipt 是否在扫描过程中发生变化。源文件、回执、状态、原 QMT 1 分钟、已接收候选和正式 Parquet/H5 **全部只读**，任何冲突立即报 `LIVE_DAY_OVERLAY_REVIEW_REQUIRED`，绝不补文件/降容差/解除隔离。

本适配器绑定当前 `live_sync` 的 `BASE_SHA=a4987bba...` 与覆盖基准日 2026-10-13，这属于**已存在 TDX DAY 覆盖模块的格式版本保护**，不是将这一天写入通用质量内核。若未来发生真正的生产来源格式升级，必须新增有测试和迁移说明的适配器版本，不在现场悄悄改写已封存回执。

## Windows 一行单笔只读示例

代码路径必须是一个确切固定提交的审计工作树，`--module-root` 则必须指向有真实私有 work/state.json 的生产模块目录：

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_AUDIT_WORKTREE\ParquetLiveSync\market_live_day_overlay_audit.py" --module-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --trading-day 2026-11-25 --symbol SH605336
```

日期和证券只是历史回归示例。支持所有符合此来源覆盖格式的日期与 SH/SZ/BJ 规范证券，但当前实际 TDX 来源不必然拥有所有证券的正成交记录。缺少日期/目标股票或任一 SHA 不符会返回非零，不会自动转往其他供应商或将“没查到”记成“没交易”。

可选已存在的原始 ZIP 字节核验需另外指定 `--raw-zip-relative downloads/...zip`，**只在操作者确切知道存储路径且授权读取时使用**。这个参数不会调用任何下载接口或修复 QMT 自有缓存。

## 验收和认证边界

成功结果状态：`PINNED_TDX_DAY_OVERLAY_RECEIPT_AND_CONTENT_READONLY`，并提供实际 state、回执、DAY Parquet 字节 SHA 与内容校验行数，及目标 OHLCVA。

无论状态如何，都不能把以下值声明为 true：

- `whole_exchange_stock_day_universe_certified=false`；文件中有目标股票≠所有应交易股票齐全；
- `provider_identity_authenticated=false`；即使验证了 ZIP 字节，也≠得到供应商签名/交易所认证；
- `qmt_native_1min_verified=false`、`market_candidate_validated=false`；DAY 不能补造 241 根缺失分钟行情；
- `original_nine_quarantines_cleared=false`、`market_data_write_authorized=false`、`market_files_written=false`、`qmt_history_download_calls=0`。

`receipt_claimed_raw_tdx_zip_sha256` 只是回执声明，若没有可选本地文件核对，`tdx_raw_zip_bytes_verified=false`；如果操作者明确给出本地 ZIP 并证明字节 SHA 相符，则仅升级这一项字节证明，**不升级提供商身份、行情内容或正式入库权限**。

## 本轮测试和下一阶段

在隔离 Python3 临时目录实际运行 **25 项**，其中 **24 PASS、1 项需要 pyarrow 的真实 Arrow E2E 测试 SKIPPED**。其余包括跨 2026/2027 日期和不同证券、state/receipt/Parquet 三方 SHA、错误行数、状态文件/回执变化、重复 JSON 键、符号链接、可选 ZIP 正确/错误/未指定与路径越界。为测试不存在的私有 QMT 文件，隔离测试使用了与 `market_quality_source_proofs` 实际 API 相同的最小本地合约替身及真实 DAY 纯函数，而不是声称已认证用户的原始 TDX ZIP。源码/测试 Git Blob SHA 必须与运行的版本相符。

前一阶段 PR #267 已由用户 Windows 实机 `pyarrow 26.0.0` 完成 **197/197 测试通过**。本次新增 25 项尚未在 Windows 上实机执行，不能合并为“已通过 222”。下一阶段优先用固定工作树在 Windows 运行新测试，再只读复核至少一条真实 TDX DAY 日线覆盖账本，检查 state/receipt/物理 DAY SHA；若实际来源 ZIP 仍未授权或缺失，应保留 ZIP 未认证标志。完成后再推进通用的提供商身份及完整交易日集合验证，绝不提前解除原 5206+9 候选隔离或把 PR #243 的 PARTIAL 变成 PASS。
