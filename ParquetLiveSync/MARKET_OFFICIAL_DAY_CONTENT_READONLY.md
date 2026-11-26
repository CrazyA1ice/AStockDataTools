# 官方 DAY 声明来源的 Parquet 内容校验（只读，尚不认证提供商）

## 产品定位

AStockDataTools 是跨日期、证券、来源及八周期的持续行情管理、清洗与修复工具。前置 PR #266 已提供本地来源文件字节 SHA 证明，本阶段验证**明确指定的 DAY Parquet 导出件**中是否存在一条合法、唯一、与目标日期和证券一致的日线记录。不会为 2026-11-25 或特定九只股票写专门判断。本阶段仍是通用证据链中的内容检查，不等于交易所真实来源认证。

## 复用的代码和校验规则

复用 market_quality_source_proofs 的安全相对路径检查和实际文件字节 SHA 核验；复用 local_layout.validate_schema 的 Arrow 八列约定，由 pyarrow.parquet.ParquetFile.iter_batches 分批读取。日线字段 ts:int64、symbol:string、open/high/low/close/volume/amount:float64。分钟、周、月等周期以后由各自的物理格点规则验证，不能直接套用 DAY。

- 所有行须属于声明日期、北京时间的实际日线日期，且字段类型合法、数值有限。
- 规范 SH/SZ/BJ 前缀或交易所后缀代码；拒绝同一规范代码的重复日线。
- 验证 low <= open/close <= high、量额同时为正或同时为零；目标股票必须存在且正量正额。
- **仅凭证券代码不能判定股票还是指数**。报告只统计规范化交易所代码，并明确 instrument_type_or_equity_membership_authenticated=false；完整交易所证券名单仍需独立官方交易日历。
- 对每份导出最多读取 100,000 行，不跳过明显损坏的 A 股代码或 OHLCVA 后再宣布成功。
- 在内容检查前后再次绑定实际文件 SHA；变化立即拒绝。不调用 QMT 下载，不改 Parquet/H5、隔离收据、任务计划或企微。

## 两种只读输入

A. **单独 DAY Parquet 文件**（适合恰好缺失 QMT 1m 的股票日）。提供明确的私有根目录、该目录下 DAY Parquet 相对路径、从独立来源收据获得的 DAY 文件 SHA256、交易日期及证券。此方式不要求导出或伪造不存在的 1m。

PowerShell 示例（路径与 SHA 必须换成真实、已授权来源）：

    & "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_AUDIT_WORKTREE\ParquetLiveSync\market_official_day_content_readonly.py" --evidence-root "D:\PrivateMarketEvidence" --day-file-relative "DAY/2026-11-25.parquet" --expected-day-sha256 "<官方DAY文件的真实SHA256>" --trading-day 2026-11-25 --symbol SH605336

不能误用当前已接收分钟候选 Parquet SHA 或回执本体 SHA 当作官方 DAY 文件字节 SHA。

B. **绑定 PR #266 的原生1m+DAY双来源 manifest**。仅当用户已合法导出两种文件时，使用 --evidence-root ROOT --manifest-relative manifest.json；manifest 的 scope.period 必须为 day，官方 DAY 角色文件必须为 Parquet。这也不表示两个自填来源标签一定相互独立。

## 严格区分结果与认证范围

状态 DECLARED_DAY_PARQUET_CONTENT_CHECKED_NOT_PROVIDER_AUTHENTICATED 只证明本地声明 DAY 文件字节、结构、日期、代码与目标 OHLCVA 通过检查。以下全部保留 false：

- complete_official_exchange_universe_certified
- instrument_type_or_equity_membership_authenticated
- official_provider_identity_authenticated / source_independence_authenticated
- qmt_native_minute_data_certified / market_candidate_validated
- market_admission_authorized / market_files_written
- qmt_history_download_calls = 0

仅通过 DAY 内容验证，不能把七只缺分钟数据的股票变成完整 1m，也不能解除九只隔离。后续仍需独立来源证明、交易所全市场证券覆盖、原购买校准、分钟240/241时间网格、六字段校验、版本化私有候选及单独授权的正式提交。

## 实际验证与下一步

本轮在隔离 Python3 环境已执行 22/22 项合成与契约测试 PASS；覆盖 2011/2019/2026 多日期/证券、代码规范、OHLC/量额、非法时间戳、重复/缺失、上限、两种输入模式及字节漂移。源码和测试 Git Blob 与实际执行文件完全一致。

**限制：** 本轮 Python 环境没有 pyarrow，因此尚未执行真实 ParquetFile/Arrow schema 的端到端读取，也未执行用户 Windows 的新分支。此前 PR #266 的 Windows 171 项已通过，但不可把新 22 项写成 Windows 已完成。下一步在本机已有 .venv 中完成实际 pyarrow/Parquet 只读测试；随后再设计官方 DAY 来源身份与全市场集合的独立证明。
