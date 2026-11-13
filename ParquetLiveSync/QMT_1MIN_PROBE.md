# QMT 历史 1 分钟 OHLCVA：第一阶段只读探针

目标：验证 2026-10-14 至 2026-11-12 的 **原生** 1 分钟 K 线能否从用户有权限的 QMT 取回。
本脚本独立于东财 5 分钟历史链；不能从 5 分钟数据伪造 1 分钟数据。

## 前提

1. Windows QMT / MiniQMT 行情客户端已启动、已登录，并具备相应分钟历史行情权限；不需要交易账户 API、密码、token。
2. 使用装有 `xtquant` 的 Python 环境（可用 QMT 官方提供的 SDK）；脚本只 import `xtquant.xtdata`。
3. 本机在 `D:\ChatGPT\AStockDataTools`，执行下列单行 PowerShell 命令。

## 运行

在先同步本 PR 对应分支后执行：

```powershell
Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_qmt_1m_probe.py -v
```

```powershell
Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; & .\.venv\Scripts\python.exe -B ParquetLiveSync\qmt_1m_probe.py --start 2026-10-14 --end 2026-11-12 --symbols 600000.SH,000001.SZ,688001.SH
```

若 `.venv` 没装 `xtquant`，用 QMT SDK 所在 Python 解释器替换上述 `.venv\Scripts\python.exe`；先用
`python -c "from xtquant import xtdata; print('XTQUANT_READY')"` 检查。**不要**在公开仓库提交 QMT 安装包、账号、密钥或原始付费行情。

输出：终端 `QMT_PROBE_RESULT` 的 `daily_counts` / `target_dates` / `sha256`，以及
`ParquetLiveSync/work/qmt_1m_probe/` 中源行 JSONL。work 被 Git 忽略；用户可以仅贴终端计数报告，不贴原始行情。

## 限制与下一阶段

- QMT 下载历史数据会填充 **QMT 自身的缓存**，但绝不访问或修改 `D:\stock\AllCycleAStockData` 或 H5。
- `fill_data=False`、`dividend_type='none'`、`count=-1`，禁止凭空填价与预复权。
- 逐行必须有 OHLCVA 六列、有效时间与交易时段；零量但正价格可作为待核查候选。
- **每天根数不强制等于 240/241**：停牌、无成交分钟、09:30 竞价和源端时间标签需结合本地购买数据认证。
- 当前只支持沪深 A 股探针；北交所历史 1 分钟线尚未证明可用。
- 不证明 `volume` 的股/手量纲，亦不证明时间戳与购买 Parquet 对齐，因此探针不具备正式合并权限。
- 只有在实际返回三个时间锚点的有效结果后，才开发批量断点、物理单位校准、整日 OHLCVA 与 DAY 对账以及原子合并。

## 已验证：QMT 历史窗口深度

用户本机 2026-11-12 实测：xtquant 250807.1.2、pandas 2.3.3，QMT 进程连接 127.0.0.1:58610，三个样本 600000.SH、000001.SZ、688001.SH 在 2026-10-14..2026-11-12 各自取得 22 个交易日 × 241 = 5302 根 OHLCVA。所有结果仍属于来源候选，**未取得已购数据口径校准认证**。

## 下一验收门槛：9 月 30 日原购买 1min 重叠样本

仅下载 QMT 2026-09-30 当日 3 股，核对旧购买物理数据的时间戳、volume 与 amount 单位。此阶段仍**不写 AllCycleAStockData**。

```powershell
Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; .\.venv\Scripts\python.exe -B ParquetLiveSync\qmt_1m_probe.py --paid-overlap-probe --start 2026-09-30 --end 2026-09-30 --symbols 600000.SH,000001.SZ,688001.SH
```

该命令只做 QMT 来源私有缓存与行检查，尚未执行与购买 Parquet 的逐根自动对比。只有完成独立逐根对账之后才能建立正确的跨源量纲与时间偏移映射，不能因为同日记录数为 241 就认定二者数据一致。

## 一键大批量推进（新增）

第一阶段三只股票已在用户 Windows QMT (xtquant 250807.1.2, pandas 2.3.3) 返回 2026-10-14..2026-11-12 全部 22 个交易日各 241 根。为避免小批量反复操作，新增 `qmt_1m_pipeline.py` 和 PowerShell 一键入口：

```powershell
Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; git pull --ff-only origin feat/qmt-one-minute-history-probe-20261112; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-qmt-1m-full.ps1 -StartDate 2026-10-14 -EndDate 2026-11-12 -MaxStocks 0; if($LASTEXITCODE -ne 0){throw "QMT one-shot workflow failed"}
```

它依次：检查 `pandas/xtquant/pyarrow`、运行 QMT 离线测试、使用现有 TDX 日线增量脚本补齐**私有且 SHA 验证的 DAY 来源层（不修改正式日线月文件）**、比对 2026-09-30 已购买 1min 时间/价格/量额倍率；全市场股票交易日来源可从现有 DAY 物理月文件或接受的私有 TDX DAY 增量中自动识别，随后逐股票获取 2026-10-14 以来的原生 1m OHLCVA。

逐股票需要完整的 241 根时标（09:30..11:30，13:01..15:00）并与当天 DAY OHLC 交叉核验。额外记录每只股票每个交易日的 DAY/QMT 成交量额合计比值，但**不假设倍率已经完成独立认证**。成功股票在私有 `work/qmt_1min_market/YYYYMMDD_YYYYMMDD/` 存来源 Arrow Parquet 和 SHA 收据，重复执行不重新下载已通过的股票；12 次连续失败自动停止新下载并保留断点。QMT 客户端自己的行情缓存会正常增加，正式 `AllCycleAStockData` 与 H5 始终不修改。

若正式 DAY 月度文件及已验收私有 DAY 增量仍比指定 --EndDate 落后，自动**只缩短本次全市场已校验覆盖上界**，绝不伪称原日期已更新；末尾会明确报告实际 `range` 和 `requested_end`。若 9 月 30 日跨源倍率未通过，仍可进行 **仅原始 OHLCVA 私有采集**，但相关股票的 `calibrated_*_factor` 为 null，绝不把未认证数据当作可入正式 Parquet 的八字段来源。

一键脚本终端只显示校准、每 50 只的进度、失败示例、最终 `QMT_ONE_MINUTE_MARKET_RESULT`。完整运行日志保存在 `work/qmt_1min_market/logs/`。如本机强制终止，本次已完成 SHA 收据仍保留；重新运行同一命令继续。完整市场可能涉及数千只股票，注意可用磁盘空间和 QMT 行情服务限速。如需先少量试运行，将参数 `-MaxStocks 0` 改为 `-MaxStocks 100`。

该阶段未合并到正式 1min 月文件，原因是 October 2026 已购/H5 月文件前半月的分钟口径还未最终统一，且大范围写入需按内存/事务边界拆分。下一阶段必须用本次源证据继续进行跨源/全日成交量额单位验收、月分片流式并入/备份及覆盖范围证明。


## 全市场采集真实结果与 184 只隔离股票逐日救援（2026-11-13）

用户本机真实采集：2026-10-14..11-12，全市场沪深候选 5223 只，完整 SHA 私有来源验收 5039 只，隔离 184 只。2026-09-30 购买 1min 跨源比对：沪主/深主/科创均通过，分钟时间偏移 0 ms、OHLC fit 1.0、QMT volume 转已购原始 1min 倍数 100、amount 倍数 1。失败分类：181 OHLC mismatch、2 Windows WinError32 文件锁、1 无效 OHLC 价格。正式 AllCycleAStockData 和 H5 均没有写入。

为了避免重新采集 5039 只，新增 qmt_1m_recover.py 和 run-qmt-1m-recovery.ps1。自动执行：逐个校验 5039 份已接受 Parquet 的 SHA/Arrow schema/footer/交易日数；核实官方 DAY 来源与购买原始 1min 跨源校准的版本绑定；只从本机 QMT 获取缺失的约 184 只源数据。每个交易日独立执行 241 分钟网格、OHLCVA 和 DAY OHLC 检验。合格的单日保存在完全独立的私有 day_recovery/source_parquet/*.parquet；异常单日保留差异数值、双方日 OHLC 和量额合计比值用于后续研究。Windows 私有原子替换遇到临时占用最多重试 6 次。重新运行同一命令会验收 SHA 和复用已经写入的恢复收据，绝不重下完整 5039 只，不碰正式 Parquet/H5。

单行运行（QMT 客户端保持已启动及登录）：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-qmt-1m-recovery.ps1 -MaxStocks 0; if($LASTEXITCODE -ne 0){throw "QMT day recovery failed"}

仅发送终端 QMT_RECOVERY_SUMMARY 和 QMT_RECOVERY_PER_DAY（或最终错误），不要上传原始 QMT 私有行情文件。私有日志保存在 ParquetLiveSync/work/qmt_1min_market/logs/qmt-day-recovery-*.log。

说明：仍是私有来源分段候选，没有正式合并权限；异常日期保留隔离，绝不会凭空补 K 线。北交所未纳入这次沪深源计划。原有分区/数据 SHA 发生变化将直接失败，避免跨版本混用。


## 2026-11-13 盘中：昨日 T+1 历史数据稳定性与独立双源交叉验收

已完成 2026-11-12 15:00 以前的昨日数据可以在 11-13 盘中重新取回，但不得把 11-13 盘中尚未收盘的分钟数据称为完整全天。新增 qmt_1m_crosscheck.py 只指定 2026-11-12 这个闭市交易日。

新增流程 run-qmt-t1-crosscheck-and-recovery.ps1 一次完成：
1. QMT 重读昨日单日 OHLCVA，与已验收的私有完整历史 Parquet 逐分钟对比（T+1 快照是否改变），任何变动都保留新来源证据，不覆盖原始快照。
2. 腾讯真 1 分钟 K 线独立检查：逐分钟 OHLCV、时间和独立量纲倍率。腾讯只提供最近最多320根且没有 amount；今天越晚昨天越容易被挤出，源日期缺失时标记覆盖不足，不判定为错误。
3. 东方财富独立 5 分钟 K 线检查：QMT 昨日 241 根 1m → 48 根 5m，对比分时段 OHLCVA 和成交量额因子；同时测试首根是否纳入 09:30 集合竞价的两种规则，所有差异只作诊断。
4. 继续核验原来成功的5039只来源 SHA，并逐日救援原先隔离的184只。不合格日永不填补假数据，全部数据仅保存私有暂存。

单行 PowerShell：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-qmt-t1-crosscheck-and-recovery.ps1 -Day 2026-11-12 -MaxQuarantinedStocks 0; if($LASTEXITCODE -ne 0){throw "QMT T+1 audit or recovery failed"}

保留 QMT_T1_CROSSCHECK_SUMMARY 与 QMT_RECOVERY_SUMMARY；详尽报告和 SHA 在 Git 忽略的 work/qmt_1min_market/independent_crosscheck 与 logs。QMT/Tencent 时间标签或停牌缺失、日内回填造成的正常口径差异必须保留证据。两家公开源并不能替代 QMT 的原生完整 1m 成交额，也不授权正式 Parquet/H5 合并。


## 深度分钟对账升级：借鉴 astock-data-toolkit / eltdx（2026-11-13）

源仓库：
- https://github.com/tiantianlaolao/astock-data-toolkit
- https://github.com/electkismet/eltdx

代码审查结论：astock-data-toolkit/minute/tdx_download.py 使用 pytdx.hq.TdxHq_API.get_security_bars(category=8, market, symbol, start, count=800) 分页取真正 1 分钟 OHLCVA，原作者报告常见服务器历史窗口近 90 交易日、最多约 24800 根。其 1min 质检依据 240 根/日，并直接提供 open/high/low/close/vol/amount；源服务器限频、旧版 TDX denormal float32 零成交和 100 股/手量纲要特殊处理。深度是源端滚动窗口，不能凭页数推断覆盖到 2011。

eltdx/docs/methods/7709-K线周期线.md 记录：1m period 原生 7/1，all_pages=True、page_size<=800 自动分页；一台服务器实测 23520 根 1m。bar_time='start'/'end' 可暴露分钟标签起止点差异，解析字段 volume_lots、amount 及原始 compact-float。它的 minutes.history(trading_date) 只返回 240 个分时价格/成交量点，非历史 OHLCVA Kline。eltdx 与 pytdx 主要同属通达信 7709 后端，因此不是两个独立供应商；不应把两套客户端一致看成两家源商独立认可。

新增 ParquetLiveSync/qmt_tdx_1m_depth.py，采用上述 pytdx category 8 历史K线，最多 40 页×800 根的有界向前回溯，遇到首条早于窗口开始日才停止；支持多个通达信公开 7709 服务器故障切换、限速和恢复缓存。程序仅对 2026-10-14..2026-11-12 已购买日线/QMT 私有缓存绑定的数据集执行：源日历和购买 1min 校准 SHA 复核；5039 只完整股票源 SHA 复核；可选读取 184 只已获逐日恢复收据；将 TDX 的 240 根与 QMT 241 根按股票/日期/分钟比对；对 offset=-2,-1,0,+1,+2 分钟进行诊断评分，记录 OHLC、逐分钟 amount 匹配、volume/amount 源量纲因子和每日期匹配情况。不得凭 1m 条数相同宣布来源一致，也不能把 09:30 集合竞价当成交量凭空推给 09:31。

只写 Git 忽略的 work/qmt_1min_market/tdx_1m_crosscheck/20261014_20261112 下独立私有 TDX Parquet、SHA 收据和逐日对账结果。不覆盖原有已购 Parquet、H5 或 QMT 私有暂存。稳定因子不可识别则标记 NO_UNIQUE_STABLE_VENDOR_FACTOR，数据有冲突则标记 MINUTE_SOURCE_DIFFERENCE_REVIEW。深度分页较 320 根源显著增加请求量，先三只锚点校验，自动门槛通过才继续全市场，串行按有限页面限速；失败保留断点而不是重复重抓 5039 只 QMT。

新增一条统一 Windows PowerShell 命令（先自检/安装 pytdx、跑离线回归、三股真实 TDX 22 日分钟线门槛，接着恢复 184 股的有效单日，最后约 5000 股深度对账）：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-qmt-tdx-deep-minute-crosscheck.ps1 -MaxStocks 0 -MaxRecoveryStocks 0; if($LASTEXITCODE -ne 0){throw "Deep 1min crosscheck failed"}

反馈 QMT_TDX_DEEP_CROSSCHECK_SUMMARY 与 QMT_RECOVERY_SUMMARY，若试点门槛失败请只分享最后报错和 QMT_TDX_DEEP_CROSSCHECK_SUMMARY，均不需上传私有行情原始价格和成交金额。生产月合并权限继续 false。北交所不在此次 7709 沪深源计划中。

## 2026-11-13 本机 pytdx 试点故障与自动诊断修复

本机真实日志（2026-11-13 10:14）：pytdx 1.72 安装成功、33 个离线测试通过、5039 只 QMT 私有来源收据通过读取，但通达信 600000.SH / 000001.SZ / 688001.SH 三股尝试 `get_security_bars` 均返回 None；三股深度对账 0 交易日，源端全市场下载未开始，正式 Parquet/H5 未更改。

代码复核：pytdx BaseSocketClient 的 `update_last_ack_time` 在默认 `raise_exception=False` 时会把 socket/parse 异常吞掉并返回 None，上一版记录缺乏实际网络、协议原因。pytdx TDXParams 将沪深1分钟标号定义为 `KLINE_TYPE_1MIN=8`，另有 `KLINE_TYPE_EXHQ_1MIN=7`；eltdx 文档原生 1m 为 7/1。服务器兼容性须从真实返回的一分钟时间网格实测，不可盲目改编号。

新增 `qmt_tdx_network_preflight.py`：使用 `raise_exception=True`，在有限官方/公开通达信 7709 主机池内依次探测 TCP、category 8 与 7 两种编码。每个类别独立建链，验证至少 16 根有效、最新数据非旧快照、连续真实一分钟时标、交易时段和 OHLCVA 合法才接受。保存选中 IP、端口、类别到 `work/qmt_1min_market/tdx_1m_crosscheck/network_profile.json`；一键脚本读取为**进程级临时环境变量**，不会改系统代理/Clash。真实失败回显底层异常和所在节点，避免抽象 `TDX returned None`。

新的大阶段一键脚本即使 TDX 所有主机不可用，仍继续执行 **184 只 QMT 异常股票逐日恢复**，随后给出 `QMT_TDX_SOURCE_NOT_AVAILABLE`（未启动 TDX 全市场轮询）。如果 TDX 预检通过，则串行执行三股/22 日深度分钟试点，通过门槛才允许启动全市场分钟交叉验收，继续复用 QMT 5039 只私有收据、TDX 已采集分区的 SHA 断点，数据全部私有暂存，无生产行情写入。

运行方式（一条 PowerShell）：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-qmt-tdx-deep-minute-crosscheck.ps1 -MaxStocks 0 -MaxRecoveryStocks 0; if($LASTEXITCODE -ne 0){throw "QMT-TDX source audit failed"}

反馈简要：`TDX_NETWORK_PREFLIGHT_PASS` / `TDX_NETWORK_PREFLIGHT_FAILED`、`QMT_RECOVERY_SUMMARY` 和 `QMT_TDX_DEEP_CROSSCHECK_SUMMARY`。本机 Clash/TUN 对 TCP 7709 的透明代理可能影响连接，尚未通过返回日志证实是其根因；必须根据实际报错和通过的 IP 制定具体 Clash `IP-CIDR/DIRECT`，不能盲目将所有 Python 流量设置为 DIRECT。

## 2026-11-13 verified eltdx 1min OHLCVA (real online test)

An actual GitHub Actions Ubuntu runner installed the prebuilt eltdx 3.3.5 wheel. Its native Rust 7709 bars.get(period="1m", count=800, bar_time="start") interface successfully fetched 5,280 unadjusted OHLCVA 1m records for SH600000 from host 116.205.183.150:7709, spanning all 22 trading days of 2026-10-14..2026-11-12 (240 per day). The source SHA was 85ae44e1acd96cc9adf8d50f46b184072d258307bd067d532bdede6c2b34ede6. Evidence: https://github.com/CrazyA1ice/AStockDataTools/actions/runs/43355867675. CI did not have access to the user's QMT private files, and therefore did not certify per-minute QMT identity.

The new qmt_eltdx_1m_probe.py and run-qmt-eltdx-real-1m.ps1 perform the local equivalent: install eltdx binary wheel if missing, execute synthetic offline tests, download exact-window real 1m OHLCVA for SH600000 / SZ000001 / SH688001, compare each source minute against the SHA-verified QMT private snapshot, and save only new private files under the gitignored work/qmt_1min_market/eltdx_1m_probe directory. The script explicitly distinguishes 22 complete minute days from merely partial online responses and does not authorize production merge. Its Windows PowerShell Start-Process execution also avoids the earlier stderr NativeCommandError pipeline abort.

One-line command:

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-qmt-eltdx-real-1m.ps1 -MaxHosts 6 -MaxPages 16; if($LASTEXITCODE -ne 0){throw "ELTDX pilot setup failed"}

If the user workstation still cannot contact 7709, preserve their original Tongdaxin after-hours 1-minute .lc1 files (often under vipdoc/sh/minline and vipdoc/sz/minline) for a fully offline source-by-source minute validation. Do not confuse .lc5 five-minute or .day daily files with .lc1. eltdx license is noncommercial research only; do not use as a commercial source or trading automation service.


### Full three-market live retest, completed

The branch CI run at https://github.com/CrazyA1ice/AStockDataTools/actions/runs/43356407582 performed actual network queries for all three QMT anchors (eltdx 3.3.5, host 116.205.183.150:7709, period=1m, 2026-10-14..2026-11-12):

- 600000.SH: 5,280 minute OHLCVA bars / 22 complete days; SHA 85ae44e1acd96cc9adf8d50f46b184072d258307bd067d532bdede6c2b34ede6
- 000001.SZ: 5,280 minute OHLCVA bars / 22 complete days; SHA 2f3bdfe3430fab33c184a7eb4dc25e84804df7119deec557dbb7c7d281096696
- 688001.SH: 5,280 minute OHLCVA bars / 22 complete days; SHA f6390ea50d110012743828587c519c551ac90031491ec1939e8b8f757550c8ca

Real source fetch pass 3/3, failures 0. The remote CI workspace did not contain private QMT so minute-wise cross-provider fit is still pending the same one-line local script. No private market source uploaded from workstation.


## 2026-11-13 next phase: full-market QMT x eltdx true one-minute cross-audit

Three real Windows QMT x independent eltdx 1min pilots returned 22/22 matched stock-days for each SH600000, SZ000001 and SH688001, 15840 eltdx candles in total. MATCHED_1MIN_OHLCVA means the documented price, amount, scaled volume and timestamp tolerance gates were satisfied, not that every field of every minute matched bit-for-bit.

New qmt_eltdx_market_audit.py and run-qmt-eltdx-allmarket.ps1 implement the following in a single session: validate original purchased DAY/paid 1m source fingerprints; SHA-audit all 5039 original QMT stocks; run day-level rescue for only the quarantined 184 stocks; then compare the complete official 5223-stock universe to genuine eltdx Rust 7709 one-minute OHLCVA across the exact 2026-10-14..11-12 window. Reuse the three already staged eltdx sample stocks by SHA, and preserve new sources as immutable private Parquet receipts, with original QMT SHA, DAY-plan SHA, per-minute timestamps, price-volume-amount comparison, daywise 240/241 status and capped specific mismatch examples.

Full-market source download is single-stock serial, bounded to 16 pages of 800 records on at most 6 eltdx nodes, with short throttling, SHA restart and a 12-consecutive-error circuit breaker. The Windows PS one-shot uses Start-Process to separate Python stderr/stdout so errors cannot trigger the previous NativeCommandError premature exit; poll reports for progress. All source buffers are under gitignored ParquetLiveSync/work/qmt_1min_market, production Parquet/H5 is NEVER written and production_merge_authorized stays false. Users must observe eltdx's license restricting use to noncommercial learning/research.

One-line command:

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-qmt-eltdx-allmarket.ps1 -MaxStocks 0 -MaxRecoveryStocks 0; if($LASTEXITCODE -ne 0){throw "ELTDX market crosscheck or recovery failed"}

To limit eltdx online source queries to the already cached 3 anchors, change -MaxStocks 0 to -MaxStocks 3. Do not change MaxRecoveryStocks from 0 if you want to recover all original 184 QMT stock-day gaps. The full-market run may involve tens of thousands of real server requests; run only with QMT logged in and stable network. Return just QMT_RECOVERY_SUMMARY and ELTDX_MARKET_SUMMARY plus specific errors, not licensed raw price data.


## 2026-11-13 all-market actual QMT vs eltdx 1m result and bounded anomaly round

Verified user's Windows run: original 5039 full QMT + 184 partial-recovery SHA receipts, 114463 of 114749 accepted QMT stock trading days (286 gaps). Full eltdx market scan visited all 5223 stocks; 5217 SHA-pinned native 1m OHLCVA sources were staged (5214 new + 3 reused). Source-present 114676 stock-days: 113846 matched by the existing minute-level OHLCVA tolerance, 554 cross-provider difference-review, 276 no QMT minute overlap. 27456000 actual minute record pairs were compared. Six eltdx stocks without a full source receipt were 001381.SZ, 002731.SZ, 301139.SZ, 301569.SZ, 301718.SZ, 688827.SH, accounting for 73 stock-days. The other 10 QMT missing keys are among these six; 276+10=286. Four of these six had eltdx source errors reporting data first available after the universal Oct14 boundary. The 4554 fully matched stocks and ~99.28% matched stock-day ratio do NOT establish bit-for-bit equality of individual minute fields.

Corrected per-stock historical lower bound: use immutable official DAY map's first certified trading date, instead of wrongly requiring every recently listed stock to have bars since 2026-10-14; allow 1/2/3 completed historical day lookback when the same certified map has only that many trading dates. Do not fabricate pre-listing bars or relax source price/amount acceptance. Already stored 5217 sources remain SHA reusable, so next run fetches only originally missing or invalid source stocks.

Added read-only qmt_eltdx_forensics.py, called automatically by run-qmt-eltdx-resume-verified.ps1 after new source retry: validate each eltdx source SHA and official plan hash; break source-difference-review days into overlapping nonexclusive price-fit, minute amount-fit, volume factor, price/amount factor ambiguity, and time-offset ambiguity categories; aggregate per-field minute mismatch totals and dates. For QMT's truly absent days, compare independent eltdx's original 240 1m OHLC to independently pinned official DAY OHLC. Report this only as diagnostic: a 240-candle source is not a reconstructed/authorized 241-candle QMT dataset. Six remaining source failures are reported with first official traded date.

One-line PowerShell continuation (source-only):

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-qmt-eltdx-resume-verified.ps1 -MaxStocks 0 -MaxHosts 6 -MaxPages 16; if($LASTEXITCODE -ne 0){throw "Private anomaly recheck failed"}

Share only ELTDX_MARKET_SUMMARY, ELTDX_FORENSICS_SUMMARY and ELTDX_FORENSICS_MISSING_SOURCES, not the raw market Parquet. This step does not change purchased source files, canonical Parquet/H5 or production merge authorization; the eltdx Rust package license remains restricted to noncommercial learning/research.

## 2026-11-13 latest completed 5221/5223 deep minute SHA forensic (source provenance correction)

User's current real Windows log: eltdx 1-minute SHA sources 5221/5223, 4 new + 5217 reused, 114724 source-present stock trading days, 113894 days matched under the existing minute tolerance, 554 source-discrepancy days, 276 QMT no-minute-overlap days, 27467520 actual aligned 1min pairs. The 2 remaining independent 1min source stocks are 002731.SZ (15 official days) and 301139.SZ (10 days). Existing 184 QMT recovery receipts remain valid and 286 QMT stock trading-day gaps remain. The 276 eltdx-vs-DAY gap tests have 261 four-OHLC matches and 15 failures.

IMPORTANT PROVENANCE CORRECTION: official_day_universe() uses local physical DAY Parquet when sufficiently complete, otherwise the project's SHA-pinned **TDX DAY private overlay** for this window. Therefore eltdx 1m vs TDX DAY OHLC agreement is SAME TDX PROVIDER FAMILY SELF-CONSISTENCY, not independent third-provider market evidence. Such agreement cannot by itself authorize filling QMT's missing 09:30 minute or promoting native 240 TDX candles to a 241 QMT day.

qmt_eltdx_forensics.py now creates complete local PRIVATE case queues, not merely 12/16 examples: latest_review_queue.private.json (all 554 minute source-disagreement days with price/volume/amount/offset diagnostic) and latest_gap_queue.private.json (all 276 QMT no-overlap days with DAY provenance and nonpromotion disposition). It also reports mutually exclusive REVIEW classes to distinguish true price differences from amount/volume measurement and timestamp ambiguity. Per-day missing 240/241 evidence is never invented; false source independence never claimed. Both queues are stamped production_merge_authorized=false and are written only under ignored ParquetLiveSync/work/qmt_1min_market/eltdx_1m_probe/20261014_20261112.

One line to run ONLY this completely offline SHA-verifying forensic stage (zero eltdx/QMT network requests, no market-file modification):

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_qmt_eltdx_forensics.py -q; if($LASTEXITCODE -ne 0){throw "Forensic tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\qmt_eltdx_forensics.py --root D:\stock; if($LASTEXITCODE -ne 0){throw "Private source-only forensic stage failed"}

Return ELTDX_FORENSICS_SUMMARY including gap_reference_provenance, gap_review_dispositions and review_exclusive_day_classes. Keep original QMT source and 5221 eltdx source receipts unchanged; do not upload licensed market bars or automatically merge any 261 candidate gaps.


## 2026-11-13 targeted offline amount/price divergence diagnosis (source-only)

New user-run forensic summary: QMT vs eltdx 1m SHA coverage 5221/5223 and source days 114724. Original QMT receipts 114463 of 114749 (286 missing). Difference-review exactly 554 days: PRICES_ALIGN_AMOUNT_NEEDS_REVIEW=393, PRICE_DISAGREEMENT_NEEDS_REVIEW=151, PRICES_ALIGN_VOLUME_NEEDS_REVIEW=1, FACTOR_OR_OTHER_NEEDS_REVIEW=9. There are 276 QMT no-overlap days, of which 261 native eltdx 240m OHLC summaries fit a PHYSICAL_PARQUET_DAY_PROVIDER_UNVERIFIED reference and 15 conflict. Two source-absent stocks remain 002731.SZ/301139.SZ, covering 25 stock-days. Physical Parquet DAY provenance must NOT be represented as an independent third source unless separately verified.

qmt_eltdx_targeted_triage.py consumes ONLY the existing 554-case latest_review_queue.private.json produced by the SHA-stamped forensic stage. It re-verifies original QMT SHA, source plan, recovery receipt SHA for any partial stock, eltdx source SHA and case-specific stored minute status; then reads only affected stock source Parquets from the private workspace. It classifies all discrepancy days into boundary-only amount misattribution, intraday amount divergence, research-only candidate stable magnitude factor, real OHLC differences, or untrusted time overlap. The new output latest_targeted_triage.private.json retains every case and summary counters with merge_calibration_authorized=false, market_files_modified=false, production_merge_authorized=false. It NEVER automatically multiplies amounts or invents a missing QMT 09:30 auction minute. Any future physical dataset promotion requires independent provenance and versioned choice of 240/241 target grids.

One PowerShell line, offline (no QMT or eltdx network calls):

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_qmt_eltdx_targeted_triage.py -q; if($LASTEXITCODE -ne 0){throw "Targeted triage tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\qmt_eltdx_targeted_triage.py --root D:\stock; if($LASTEXITCODE -ne 0){throw "Targeted minute amount forensic analysis failed"}

Send only ELTDX_TARGETED_TRIAGE_SUMMARY, never vendor raw 1-minute bars. The full 554-case evidence stays in the private workspace; the 261/15 gap triage stays in the separate latest_gap_queue.private.json. The sole QMT source has already been verified for each case; no need to rerun all-market source acquisition.


## 2026-11-13 eltdx 历史 09:25 正式撮合拆分 240→241 的可行性试验

eltdx 的 client.auctions.series(code,date) / 0x056a 返回竞价过程的虚拟匹配量和未匹配量，并非成交，绝对不能直接累加为 09:30 成交。历史 09:25 **正式成交**应使用 client.trades.opening_match_history(code,date) / 0x0fc6（或 client.helpers.auction_data(...).snapshot_0925）。它返回撮合价格、成交量（手）和由 price * volume * 100 派生的成交额。历史日期能否返回取决于远端服务器保存范围。

历史购买 Parquet 的 1min 正常日采用 241 根网格（09:30 独立开盘 + 09:31..11:30 + 13:01..15:00），通达信 eltdx 原生 240 根；原已购 600000.SH/2026-09-30 的只读 .lc1 对账发现 **Parquet 的 09:30 + 09:31 合并后**与通达信 09:31 首根 OHLCVA 全六字段吻合，剩余 239 根也吻合。这给 09:25 开盘竞价撮合=Parquet 09:30 提供了可检验的假说，但未证明所有股票/日期同理。

新增 qmt_eltdx_auction_241_probe.py：直接复用之前 3 股（600000.SH、000001.SZ、688001.SH）的 SHA 验证 QMT 241 根和 eltdx 240 根私有快照，只联网逐股取所选交易日历史正式 09:25 成交。检查正式竞价价是否等于 QMT 09:30 四价、量与成交额在股/手量纲下相符，及 QMT 首两根聚合后是否等于 TDX 首根全六字段。绝不把虚拟委托盘的 matched_volume 作为实际成交；金额是 price×lots×100 的派生值而非第二份独立交易金额证据。

这项试验并不直接**生成** 241 根新行情：当 QMT 09:30 原始数据本身缺失时，即便已知正式竞价 OHLCVA 与合并 09:31 量额之差，也无法凭一根合并 K 线唯一求出连续交易的 09:31 **open/high/low**（其 high/low 可能由竞价价格取得极值）。要无损恢复须进一步审计 eltdx.trades.all_history(code,date) 历史成交明细的完整性、价格极值和分钟分桶，并与已有 241 根原始 Parquet 逐字段对比。该接口时间精度只有分钟、并非 L2 逐笔撮合；如果欠缺可唯一确定的开盘或极值，就保持隔离而非造 K 线。买来的 241 根 Parquet 仍为目标格式，不允许自动合并。

本机有限范围联网试点（只查 3 股 2026-10-14 历史正式竞价，不重下已缓存的 240/241 完整分钟源，也不写正式 Parquet/H5）：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_qmt_eltdx_auction_241_probe.py -q; if($LASTEXITCODE -ne 0){throw "Auction split offline tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\qmt_eltdx_auction_241_probe.py --day 2026-10-14; if($LASTEXITCODE -ne 0){throw "Historical 09:25 split feasibility probe failed"}

回传 ELTDX_AUCTION_241_FEASIBILITY_SUMMARY 和三条 ELTDX_AUCTION_SPLIT_STOCK 的状态，不要分享非公开原始分钟行情。完整源 SHA 绑定试验报告位于 private work/qmt_1min_market/eltdx_1m_probe/20261014_20261112/auction_0925_split_pilot/。所有结果维持 production_merge_authorized=false。


## 2026-11-13 竞价试点实测：09:25 能匹配 QMT 09:30，但 09:31 首根仍有差异

用户 Windows 2026-11-13 试点运行：4 项离线测试通过，3 只锚点 (600000.SH/000001.SZ/688001.SH) 的 2026-10-14 正式 09:25 撮合数据在既定价格/量/额容差内都吻合 QMT 的独立 09:30 bar（auction_0930_candidate_matches_qmt=true）；但 QMT 09:30+09:31 两根按 OHLCVA 聚合后，均未与 eltdx 09:31 首根完成所有 6 字段一致性校验 (first_minute_all_fields_fit=false)。不能把此现象解读为竞价数据无用或认定已经成功恢复了 241 根。由于这是全字段 AND 门槛，必须拆出不匹配字段；仅此结果无法判断是价格还是量额问题，也无法判定源间 09:31 时间语义和盘后 .lc1 是否完全相同。

新增 qmt_eltdx_auction_241_postmortem.py 完全离线对账：读取既有 20261014_summary.private.json，并重新独立验证 QMT 241 和 eltdx 240 的 SHA/Arrow/时间网格；比较 QMT(09:30+09:31)→TDX(09:31) 以及 QMT(09:31)→TDX(09:31) 两种假设的六字段通过项、相对误差及随后 239 根每字段匹配数。若旧报告源签名或字段判定有任何变化，禁止继续推断。全部只写 Git 忽略私有报告，正式 Parquet/H5 不修改。只打印计数和比例，不输出受许可约束的原始行情价格。

单行命令（无任何行情联网请求，仅用用户刚才的原始缓存）：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_qmt_eltdx_auction_241_postmortem.py -q; if($LASTEXITCODE -ne 0){throw "Auction field tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\qmt_eltdx_auction_241_postmortem.py --day 2026-10-14; if($LASTEXITCODE -ne 0){throw "Auction field postmortem failed"}

请返回 ELTDX_AUCTION_241_FIELD_DIAGNOSTIC (3 行) 与 ELTDX_AUCTION_241_FIELD_SUMMARY (1 行)。之后才考虑针对失败的具体字段调取历史真实成交明细（不是 0x056a 虚拟委托快照），并拿旧购买的 .lc1+241 Parquet 样本做同日交叉印证。正式目标始终保留 241 网格、不得伪造 09:31 high/low/open，也不得因 3 个样本匹配某规则就在全市场自动合成。


## 2026-11-13 三股分钟字段审计揭示疑似股/手 ×100 而非真实 09:31 价格错误

用户本机 2026-10-14 三只 SHA 认证源回显：QMT 09:30+09:31 合并后与 eltdx 09:31 **OHLC 四项及成交额 amount 均匹配，仅 volume 不匹配**，三股的 volume 归一化相对差都为 0.99。之后 239 根各股 OHLC+amount 都是 239/239，通过原值比较的 volume 只有 1/239 或 2/239（很可能是双方均为零的无成交 K 线）。此时模型的原标签 MERGE_PRICES_ONLY_VOLUME_AMOUNT_DISAGREE 只是过宽的分类名，不应误以为 amount 也不匹配。这组证据非常符合 raw eltdx volume_wire_value（常为股）相对 QMT volume（可能为手）的 100 倍量纲差异，但不能只凭 0.99 决定倍率方向或单位。

增强 qmt_eltdx_auction_241_postmortem.py 的 v2 输出：使用既有 SHA 认证的 QMT 241 与 eltdx 240、09:25 正式竞价收据，严格按现有时间戳，在 TDX 240 根的首根与 QMT 首两根合并后、其余 239 根直接对应的条件下，检验 QMT_volume = raw_eltdx_volume × {0.01,1,100} 的全日 240 根配对。**只用正成交量分钟判别量纲**，单独报告双方都为零的分钟和只有一方为零的异常；候选需要至少 40 对有效分钟、>=98% 正量分钟拟合、其他倍率低于 80% 且无单侧零成交，才能称为唯一候选。即便 240/240 在单位归一化后全通过，也只是源端口径诊断，绝不授权修改原始 Parquet、H5 或交易值，仍未证明由 240 根 + 09:25 快照能独立无损恢复 09:31 连续竞价 open/high/low。

一条离线 PowerShell 命令（不会重新下载行情，使用原先 2026-10-14 的原 SHA 证据，需回传三条诊断和汇总中的 volume_candidate_factors_raw_tdx_to_qmt）：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_qmt_eltdx_auction_241_postmortem.py -q; if($LASTEXITCODE -ne 0){throw "Volume scale tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\qmt_eltdx_auction_241_postmortem.py --day 2026-10-14; if($LASTEXITCODE -ne 0){throw "Volume scale diagnosis failed"}


## 2026-11-13 三股 240↔241 首分钟六项数据恢复成功后的下一阶段：历史实际成交验证

用户实际实测 2026-10-14 的 000001.SZ、600000.SH、688001.SH 3/3：QMT 09:30 竞价对应 eltdx 09:25 正式撮合；QMT 09:30+09:31 两根聚合后的 OHLC、amount 与 eltdx 09:31 首根吻合；TDX 原始 volume_wire_value 对应 QMT volume 的固定倍率为 0.01，所有三股的 240/240 每日分钟线 volume 归一化后吻合，后续 239 根的 OHLC 和 amount 也全数吻合。正成交量证据每股 238~239 根、双方同时零成交 1~2 根、单侧零成交 0。**此处 720/720 指三只股票的 240 根聚合对账，并非已经反向独立恢复 723 根 QMT 原始分钟线。**

必要的下一阶段：eltdx 的 0x0fc6 历史成交明细只具备分钟级时间戳，部分成交为合并记录，不是有秒级排序保证的 L2 逐笔成交。因此即使能够从 09:25 正式成交构造真实 09:30 竞价 bar，也不能仅由通达信 09:31 的合并 OHLC 唯一确定 QMT 09:31 的 open/high/low。新增 qmt_eltdx_opening_ticks_241_probe.py，在仅限上述三股和 2026-10-14 日期范围内，复用原 09:25 认证报告、QMT/TDX 的既有 SHA 绑定私有 241/240 快照及 100x 量纲核对。随后只查询三股该日的历史成交明细 (client.trades.all_history / 0x0fc6)；严格排除 event_kind=auction_snapshot 的虚拟竞价行情和 09:25 正式撮合（后者另做单独竞价认证），检查 09:30、09:31、两分钟合并三种交易分组的价格开高低收（同时研究原始记录顺序或反向记录顺序）、手数及派生金额是否拟合 QMT 的独立 09:31 记录。

这是一项**能否在缺少 QMT 09:31 时从通达信真实成交恢复的可行性检验**。一个股票样本即便六字段拟合，也只报告诊断拟合，不自动认证真实时序、完整逐笔撮合、无损恢复，更不会写正式 AllCycleAStockData/H5。源行情及逐笔仅在私有 work 目录保存 SHA 证据，不对公开仓库上传。

Windows 用户按以下**单行**命令试点（本次仅新查询三只股票的 2026-10-14 历史成交明细，已经缓存的 240/241 1min 不重下；试点失败按股票报告并保持原市场文件不变）：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_qmt_eltdx_opening_ticks_241_probe.py -q; if($LASTEXITCODE -ne 0){throw "Tick-reconstruction offline tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\qmt_eltdx_opening_ticks_241_probe.py --day 2026-10-14; if($LASTEXITCODE -ne 0){throw "Historical trade tick pilot failed"}

下一次只需反馈 ELTDX_0931_TRADE_PILOT_STOCK 3 行和 ELTDX_0931_TRADE_PILOT_SUMMARY 1 行。核心问题是 09:31 OHLC 是否能从历史实际成交而不是 QMT 参考来源独立推导。此试点无批量生产合并权限。


## 2026-11-13 历史成交实测：不能拿分钟标签 09:30 的成交强行当成 QMT 09:30

2026-10-14 真实三股 eltdx 0x0fc6 采样：三股正式 09:25 撮合仍 3/3 符合 QMT 的单独 09:30 竞价 bar。但历史实际成交明细的 09:30 和 09:31 标签各有 **20 条**，而 000001.SZ 的 09:30 分组却与 **QMT 09:31 bar** 在原试验容差下 OHLCVA 六项 6/6 匹配；600000.SH 是 5/6，688001.SH 是 4/6，均由价格 high（后者还包括 low）失配。被标为 09:31 的成交组直接对 QMT 09:31 仅 1~2/6 通过。这强烈提示需要检验 0x0fc6 成交记录标签是否是 1min 分桶的 **左端点**，即 09:30 对应 QMT 09:31、09:31 对应 QMT 09:32；对于价格极值的失配需检验成交记录聚合/不完整性。20 条每分钟且返回的时间精度只有分钟，不得未经证实将其视为秒级完整 Level 2 撮合。

新增 qmt_eltdx_opening_tick_alignment.py：**零联网、严格源 SHA** 校验上一次 09:25 报告、上一次历史成交试验摘要、每只股票保存的 40 条真实成交 subset（通过内容 SHA256 绑定）、现有 QMT 241/TDX 240 私有源，然后对 09:30/09:31 两个 trade 组分别交叉比对 QMT 的 09:30/09:31/09:32 K、TDX 09:31/09:32。价格/量额同时输出原先诊断容差和更严格容差，不在日志中打印原始收费行情值；给出若干价极值是否落在对应 QMT 极值范围内。源时间顺序/分钟内成交完整性均不认证，不合成或修改任何 K 线。仅保存 Git 忽略目录下新的私有归因结果。只有分钟标签、极值完整性进一步验证后，才可判断 TDX 240+09:25 是否能独立无损恢复 241；当前 production_merge_authorized=false。

单行 PowerShell（零行情联网，仅 git pull 会联网更新代码）：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_qmt_eltdx_opening_tick_alignment.py -q; if($LASTEXITCODE -ne 0){throw "Trade label offline tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\qmt_eltdx_opening_tick_alignment.py --day 2026-10-14; if($LASTEXITCODE -ne 0){throw "Trade label offline SHA crosscheck failed"}

请回传 ELTDX_OPENING_LABEL_STOCK 三行与 ELTDX_OPENING_LABEL_SUMMARY 一行，不要上传私有逐笔/原始行情数据。


## 2026-11-13 第二轮 0x0fc6 双分钟对齐与成交额精度/首分钟可逆性

用户 SHA 原证据 (2026-10-14) 的 3 股输出证明：每股历史真实成交的 09:30 和 09:31 组**各 20 条记录**，时间字段只有分钟；成交记录的 09:30 分组与 QMT 09:31 的成交量严格一致，09:31 分组与 QMT 09:32 的成交量严格一致；上述两组的派生成交额在旧 3.5% 容差内均一致，然而三股的 amount 在更严格的 1 元/1ppm 级阈值下都不一致。旧报告字段 status=NEITHER_MINUTE_LABEL_MODEL_STRICTLY_FITS 是因同时要求严格成交量 + 严格成交额的 AND 门槛造成，**不能据此否定历史成交明细时间比 QMT 分钟 K 线早一标签的强证据**。此时在相同分钟标签下成交量不吻合；09:30→09:31、09:31→09:32 很有必要独立审计。真实成交额是由协议每条成交价格×手数×100 估算的，非另一份严格官方总成交额记录。

下一阶段在原 qmt_eltdx_opening_tick_alignment.py 就地增加：
- 三类强度：既有宽松成交量+额匹配、已有严格成交量+额匹配，以及新增**严格成交量+容差成交额**匹配，独立判断起始标签 +1 与同名标签，避免严格金额失败造成假阴性；
- 每个分桶输出估算成交额偏差的**基点**（basis points）与绝对误差区间（<=1、<=10、<=100、<=1000、>1000 元），私有价格成交值不出终端；
- 首分钟反问题的可确定边界：仅使用已有 QMT 09:30 **作为暂时竞价价、量、额对照基准**（旧 09:25 正式撮合试验原始价量额没有持久保存），研究通达信 09:31 首根 **close**、减去独立 09:30 竞价成交的 **volume/amount** 在原 QMT 09:31 中的严格通过情况；只有通达信合并 K 的 high **严格高于**竞价价格，才能断言该 high 是真实连续交易产生；只有 low **严格低于**竞价价格，才能断言该 low 是真实连续交易产生。若 high==竞价价或 low==竞价价，不能由合并 K 唯一反推该极值；真实 09:31 open 需要完整且可靠时间排序的实际交易。
- 另外标记 09:30 成交记录按源返回正序和反序的首价是否各自匹配 QMT 09:31 open，但不认证源成交记录属于时间顺序，也不认证每分钟 20 条代表完整逐笔。
- **本报告使用 QMT 09:30 作临时 oracle，因此只验证数学可逆性，不是脱离 QMT 的独立 241 根数据恢复成果**；真正来源独立的程序以后须重新从 eltdx 0x0fc6 获取正式 09:25 价量额并保存其来源，且对分钟开高低收建立时间顺序/极值完整性证明。在这之前不转换/写入正式 Parquet/H5，仍 production_merge_authorized=false。

零行情联网、零正式数据库修改的单行命令：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_qmt_eltdx_opening_tick_alignment.py -q; if($LASTEXITCODE -ne 0){throw "Opening inference offline tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\qmt_eltdx_opening_tick_alignment.py --day 2026-10-14; if($LASTEXITCODE -ne 0){throw "Opening inference local SHA audit failed"}

请回传三条 ELTDX_OPENING_LABEL_STOCK 与一条 ELTDX_OPENING_LABEL_SUMMARY。特别检查 status 是否为 NEXT_MINUTE_LABEL_SUPPORTED_BY_EXACT_VOLUME_AND_TOLERANT_AMOUNT，及 inferred_0931_bounds.known_field_match_to_qmt / high_uniquely_determined_by_merged_extreme / low_uniquely_determined_by_merged_extreme / trade_0930_first_as_returned_open_match。以上仍仅能为三只 SHA 源历史样本提供研究结果。


## 2026-11-13 独立 09:25 竞价与 240→241 候选构造（隔离试点）

用户最新实测 2026-10-14 三股：历史 0x0fc6 成交标记 09:30 的成交量严格对应 QMT 的 09:31，标记 09:31 严格对应 QMT 的 09:32；两分钟的估算成交额在旧容差下均吻合。模型分类 3/3 均 NEXT_MINUTE_LABEL_SUPPORTED_BY_EXACT_VOLUME_AND_TOLERANT_AMOUNT。三股 QMT 09:31 的 open 都与 09:30 成交源返回的第一笔价格吻合，而反向顺序不吻合；然而成交源有且仅有分钟时间标签，20 条/分钟，不能据此认证精确逐笔成交先后顺序。原诊断 inferred_0931_bounds 的 high/low/close/volume/amount 在三股全部与 QMT 09:31 匹配，且原合并首根高/低均分别超出竞价单价格；**但该结果依赖 QMT 09:30 竞价价量额作为临时 oracle，并非独立重建成功。**

新增 qmt_eltdx_source_independent_241_pilot.py，将竞价价量额补上真实原始来源：
- 读取 SHA 验证的原三股 240 通达信原生 K、241 QMT 验收参考源及前面只读的 09:30/09:31 成交明细 SHA 收据；不重新下载 1min 或逐笔。
- 只联网重新查询每股指定日期 eltdx.trades.opening_match_history(code,date)，强制 event_kind=opening_match、09:25、正常成交且非 status=8 竞价过程快照；将**正式拍卖价、手数与 price×lots×100 派生成交额**完整记录在 Git 忽略私有文件并做 SHA 溯源，修复此前只有布尔匹配、不保存真实竞价值的问题。
- 研究候选 QMT 格式 09:30: OHLC=真实正式撮合价，volume=正式拍卖手数，amount=正式价×手数×100；研究候选 QMT 09:31: close=TDX 09:31.close, volume=TDX 09:31 原始 volume_wire_value ×0.01 减去竞价成交手数, amount=TDX 09:31.amount 减去正式撮合派生额；high 当合并首根高于拍卖价时确定为合并高，low 当合并首根低于拍卖价时确定为合并低；如果极值恰等于拍卖价但存在历史真实 09:30 分组成交记录在该价，则暂定该极值可确定；如果无法唯一确定则保存 null，**绝不猜测高低价**。
- 09:31 候选 open 使用历史成交 09:30 组源返回第一条实际成交价，但显式标注 sequence_chronology_certified=false、independent_0931_open_certified=false。即使该价与 QMT 原 09:31 开价完全吻合，也不允许以当前分钟精度和 20 条/分钟成交明细声称已独立证明真实开盘价。
- 只有完成来源独立构造后，才使用**独立只读** QMT 241 参考列逐项验收 source-only 候选，输出已知字段匹配情况与缺失字段，不以 QMT 数值补任何候选 K。保存私有候选、真实 09:25 撮合数值和SHA；不写/回填正式 Parquet/H5，production_merge_authorized=false。候选在开盘时序未被额外认证前不可自动正式发布。

Windows 单行 PowerShell（最多新增查询三只股票该日 09:25 正式成交，一次证券一个；不重新下载 1min 或成交明细）：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_qmt_eltdx_source_independent_241_pilot.py -q; if($LASTEXITCODE -ne 0){throw "Source-independent 241 pilot tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\qmt_eltdx_source_independent_241_pilot.py --day 2026-10-14; if($LASTEXITCODE -ne 0){throw "Source-independent 241 candidate pilot failed"}

回传 ELTDX_241_SOURCE_ONLY_STOCK 3 行与 ELTDX_241_SOURCE_ONLY_SUMMARY 1 行。重点检查各股是否 09:30 和 09:31 已知六字段逐一符合原 QMT 241 参考、是否存在未知高低价以及开盘价排序能否在新独立来源中进一步认证。任何候选全部匹配仍不能授权正式入库。


## 2026-11-13 09:25 独立来源 + 09:31 候选已在三股成功，下一阶段留出日期严谨验证

用户 2026-10-14 真机输出：600000.SH、000001.SZ、688001.SH 均得到 ALL_SIX_SOURCE_CANDIDATE_FIELDS_VALIDATE_TO_QMT。先由 eltdx 09:25 正式撮合**独立提供竞价价、手数、派生成交额**，独立 TDX 240 合并首根反推连续交易 09:31 的 high/low/close、量额，历史真实成交 09:30 首条价给出 provisional open；所有 3 股的 09:30 和 09:31 各六字段均在设定容差内符合独立 QMT 241 对照。SH 600000、SZ 000001 的两根各六字段还全部通过严格金额阈值；SH 688001 的 09:30/09:31 amount **仅容差通过而严格失败**（由于 09:25 成交额=单价格×手数×100，并非独立成交额权威字段，不能当作零误差认证）。两根都已确定，三股均未出现首根等于竞价价导致的 high/low 不可辨识，但这不是全市场普遍性证明。历史交易明细 20 条/分钟，秒级顺序未认证；因此 **09:31 open 属候选，而非真实来源独立认证**。production_merge_authorized 仍始终 false。谨防把 3 股×2 根×6 字段的验收误称为 241 根×3 股全部独立重建：后续 239 根直接沿用原 240 通达信数据，而开盘拆分仅验证开头两根。

新增 ParquetLiveSync/qmt_eltdx_241_cross_day_holdout.py：严格留出 2026-10-15 和 2026-10-16 两个日期、3 只原股票，至多 6 股票日。先离线 SHA+Arrow+完整 241 QMT/240 TDX 网格预检，**本地数据不齐则在任何 7709 请求前停止**。每个股票日只联网调用一次 eltdx.trades.all_history(code,date)，要求历史正式 09:25 opening_match 唯一且 09:30、09:31 真实成交均存在，status=8 虚拟竞价从成交排除。独立生成 09:30/09:31 候选，只在构造完成后对 QMT 封存参考源做验收，同时将历史成交 09:30→QMT 09:31、09:31→QMT 09:32 的精确量与容差成交额列出，剩余 239 根以 0.01 股/手比例核对。精确金额不足、极值不唯一、价格不同，均单独返回状态并永久保留源，不采取自动更改或容差自动提升。历史成交页/候选/独立正式竞价保存在 Git 忽略的私有 holdout 目录；仅控制台打印统计、SHA 证据，不输出原始行情。每只股票/每日期可以继续独立复核。不得以测试通过推断生产入库权限。

Windows 单行 PowerShell：先拉取分支，运行 6 项该试点离线测试，通过后本地预检六个股票日；预检成功才开始新的历史成交请求（不会重新下载已有 240/241 分钟原始数据，不写购买的正式 Parquet/H5）：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_qmt_eltdx_241_cross_day_holdout.py -q; if($LASTEXITCODE -ne 0){throw "241 holdout offline tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\qmt_eltdx_241_cross_day_holdout.py --preflight-only; if($LASTEXITCODE -ne 0){throw "241 local SHA/full-grid preflight failed, no 7709 request made"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\qmt_eltdx_241_cross_day_holdout.py; if($LASTEXITCODE -ne 0){throw "241 two-day holdout failed"}

发送每个股票日一行 ELTDX_241_HOLDOUT_CASE 和最后一行 ELTDX_241_HOLDOUT_SUMMARY。若本地 SHA/241/240 完整日不齐则发预检报错即可，不尝试绕过 SHA 或伪造其他日期。该阶段没有设置自动合并或数据迁移行为。


## 2026-11-13 240→241 跨日期真机留出检验：5/6 六字段候选完整，单例极值仍不可确定

用户 Windows 真机结果：6 项离线测试 OK，本地原三股 2026-10-15/16 的 241(QMT)/240(eltdx) 6 个股票日 SHA、Arrow、完整日期网格预检通过。6/6 均验证历史实际成交 09:30→QMT 09:31 与 09:31→QMT 09:32 的严格成交量/容差成交额匹配，且首条 09:30 成交记录价格严格等于 QMT 09:31 open。然而 0x0fc6 返回仅分钟时间标签，不能证明那条记录就是严格按秒排序的连续交易开盘价。
- 2026-10-15 600000.SH 与 2026-10-16 000001.SZ 为 HOLDOUT_ALL_SIX_STRICTLY_MATCH_SOURCE_CANDIDATE (2/6)；
- 2026-10-15 000001.SZ、688001.SH 与 2026-10-16 600000.SH 为 HOLDOUT_ALL_SIX_TOLERANTLY_MATCH_NOT_STRICT (3/6)；
- 2026-10-16 688001.SH 为 HOLDOUT_PRICE_EXTREME_OR_FIELD_NOT_IDENTIFIABLE，尽管它的已知字段均满足原容差，但 source_only_09:31 候选缺少 1 个无法从合并 K 唯一推断的字段。这个案例绝对不能将 QMT 原值作为“补缺”直接转生产 K。
- 上述 5/6 是 **3 股票×2 日期的六字段已知候选**，不是已经无损恢复 5 个完整 241-bar 股票日；后续 239 根是原始 eltdx 240 bar 的时间和 volume 单位对齐，源仍依赖通达信分钟 K 且历史交易开盘先后未独立认证。任何结果都保留 production_merge_authorized=false。

新增 qmt_eltdx_241_holdout_postmortem.py 和 test_qmt_eltdx_241_holdout_postmortem.py：
- 零行情网络请求，读取已生成的 20261015_20261016_holdout_summary.private.json；逐股票日用私有报告保存的 SHA256 检查各历史 trade 子集/候选报告字节未变更，重校验原始 eltdx 240/QMT 241 来源 SHA、Arrow schema，再利用保存的 **正式 09:25 撮合**和真实 09:30/09:31 成交 + eltdx 240 开盘首根重新**独立**构造两个候选，只将 QMT 用于最终验收。
- 分别列出 09:30 和 09:31 的严格不匹配字段、容差不匹配字段、未知字段。对于未确定高低价，报告**是否恰好等于竞价价、历史真实成交记录是否到达竞价极值、QMT 验收时的极值是否等于竞价价**；尽量辨析是高、低哪个字段缺证据，绝不填入缺失极值。
- 每股只打印成交额误差基点及绝对额区间（<=1、<=10、<=100、<=1000、>1000 CNY），分开显示竞价 09:30、连续交易 09:31、聚合首分钟合计、历史真实成交估算金额；保存细节在 Git 忽略私有目录。**不能把原容差金额匹配等同于精确金额恢复**，也不能把历史成交分组记录顺序当成 L2 秒级时序。
- 原始 SHA、日历和私有报告一旦不匹配则立即停止，不会重新抓行情、修改已购 Parquet/H5，不能生成生产 241 数据集。

PowerShell 单行命令：先更新代码+五项离线测试，然后仅使用已缓存的六个案例生成私有归因报告：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_qmt_eltdx_241_holdout_postmortem.py -q; if($LASTEXITCODE -ne 0){throw "241 held-out SHA postmortem unit tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\qmt_eltdx_241_holdout_postmortem.py; if($LASTEXITCODE -ne 0){throw "241 held-out SHA replay failed"}

回传 ELTDX_241_HOLDOUT_POSTMORTEM_CASE 的 6 行和 ELTDX_241_HOLDOUT_POSTMORTEM_SUMMARY 的 1 行。下一阶段只根据真实缺口决定能否获得更权威的秒级成交排序/权威金额来源；绝不能把 241 已恢复给所有股票当作结论。


## 2026-11-13 六股票日 SHA 复核：缺口是 688001.SH 的 2026-10-16 09:31 high，观测极值不得直接补库

用户本机 2026-10-15/16 六股票日的 qmt_eltdx_241_holdout_postmortem.py SHA 重算通过，5 项离线测试 OK：
- 6/6 原通达信 09:31 合并首根成交额均能与 QMT 开盘两根成交额之和在严格阈值内对齐，差额均在 10 元以内。但拆成两根后，09:31 独立成交额严格不匹配 4/6。eltdx.models.trade.TradeTick.trade_amount_yuan 只是 self.price * self.volume * 100.0，非交易所独立提供的权威开盘成交额。此为源端金额量化问题，不能用宽容差冒充精确恢复。
- 688001.SH 2026-10-16 缺失的是 09:31 的 high；合并首根最高价等于正式竞价价，QMT 09:31 最高价与竞价价不同，且记录中 20 条 09:30 实际成交的观测最高价恰好严格吻合 QMT 09:31 最高价。这是来源独立的观测候选，但不是可以严格认证的真实完整极值。
- **有真实反例：2026-10-14 的 600000.SH 和 688001.SH**，历史成交 09:30 组与 QMT 09:31 的成交量严格匹配、成交额容差匹配，但观测组 high 未与 QMT 对应 high 匹配。即使所有成交量完全覆盖，20 条历史成交记录也不能保证完整价格极值。因此绝不允许因 2026-10-16 688001.SH 的观测 high 恰好匹配 QMT 就自动填补正式 Parquet。
- eltdx.api.trades.TradeApi._all() 逆序拼接页面但保留页内 wire 顺序；TradeTick.absolute_index 由页偏移+行偏移生成；只有分钟精度的 0x0fc6 记录仍不能独立证明严格秒级成交先后。因此首条价 9/9 样本与 QMT 09:31 开盘价一致，仍属高价值候选，非真实逐笔时序认证。
- 代码新增来源独立观测极值私有候选、成交量覆盖旗标、相对竞价价基点间隔、观测最高/最低价与 QMT 是否吻合的仅验证布尔值。无论是否吻合都保持真实候选中不确定极值为 null（source_only_production_field_stays_null=true，production_merge_authorized=false）。原始价格值只进 Git 忽略私有报告，不进入打印日志。还加入测试：成交量完全匹配但交易聚合价丢失原始极值的合成反例。
- 安全结论：不批量写入正式 Parquet/H5；需要在这个真实异常日验证能够认证 09:31 高低价的第二来源，或权威完整逐笔撮合极值；精确金额需比 price×lots×100 更可靠的正式竞价金额来源。不要用 QMT 验收值填充候选。

单行 PowerShell（更新 Git 代码后其余部分全离线）：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_qmt_eltdx_241_holdout_postmortem.py -q; if($LASTEXITCODE -ne 0){throw "Historical extremes offline tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\qmt_eltdx_241_holdout_postmortem.py; if($LASTEXITCODE -ne 0){throw "Extrema forensic SHA replay failed"}


## 2026-11-13 通达信本地盘后文件只读探针（完全不需要 BigQuant）

用户截图本地安装根目录 D:\software\TDX\vipdoc\sh\fzline，存在大量 sh000001.lc5 等文件、显示 192 KB、更新时间 2026-11-13。经 pytdx 官方 reader 文档和 TDX 本地读取器交叉确认：
- vipdoc/sh|sz|bj/minline/*.lc1 是本地 **1 分钟 K 线**，用户目标是寻找它以独立验证 2026-10-16 688001.SH 的 09:31 high；
- vipdoc/sh|sz|bj/fzline/*.lc5 是本地 **5 分钟 K 线**，只读 .lc5 对照可验证分钟覆盖/更高周期，但不能直接恢复 1min 最初高低价；
- sh000001.lc5 是上证综指，不是 600000.SH/688001.SH 个股。还需核验三股对应文件 sh600000.lc5、sz000001.lc5、sh688001.lc5 以及 .lc1；
- .lc1/.lc5 均为每条 32 字节的小端记录，HHfffffII：16 位压缩日期 (year-2004)*2048+month*100+day、16 位分钟数、四个 float32 OHLC、float32 成交额、uint32 原始成交量、uint32 保留。正常已完成交易日分钟线常见 1min=240、5min=48，但只统计实际记录，不预先改成 QMT 241、不补造竞价 K，股票/指数成交量单位可能不同；
- 截图 192 KB 是 Windows 大小显示值，不代表已核准真实字节数或历史日期；以本机文件长度、SHA 和解码结果为准。

开发分支新增 ParquetLiveSync/tdx_local_lc_probe.py / tests/test_tdx_local_lc_probe.py，纯标准库，无网络行情依赖、零 Parquet/H5 写入。传入本机 vipdoc 根目录，定向读取三只原股票 600000.SH、000001.SZ、688001.SH，并单独扫描 sh000001 指数；同时仅枚举 sh/sz/bj 的 minline/fzline 内文件数，区分是否实际拥有任何 .lc1 1min 文件。逐文件 SHA256、完整的 32 字节记录、字段合理性、异常/重复时间戳、首末日期、交易日根数分布、2026-10-14/15/16 样本分时、09:30/09:31/09:32/09:35/15:00 标签存在与否。日志不输出原始 OHLCVA 值；所有读数只留在内存，禁止批量改写、移动、转换源数据。

用户 Windows **单行** PowerShell：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_tdx_local_lc_probe.py -q; if($LASTEXITCODE -ne 0){throw "Local TDX LC tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\tdx_local_lc_probe.py --vipdoc "D:\software\TDX\vipdoc" --codes "600000.SH,000001.SZ,688001.SH" --dates "2026-10-14,2026-10-15,2026-10-16"; if($LASTEXITCODE -ne 0){throw "Local vipdoc LC read-only scan failed"}

回传 8 条 TDX_LOCAL_BAR_FILE 和 TDX_LOCAL_BAR_SUMMARY。若 .lc1 不存在，则第一步应在通达信软件中检查盘后数据下载是否提供“1分钟”历史下载，**而不是把 5min K 线拆成 1min 或强制填补 09:31 high**。如果 .lc1 存在且目标日期完整，下一阶段才安排 SHA 单分钟标记对照 QMT 原始 241，用作第二来源的只读严格校验。


## 2026-11-13 Windows 通达信本地 9,607 个 .lc1 文件发现后：三源只读分钟精度验收

用户本机命令扫描输出：vipdoc/SH minline 4850、SZ minline 4397、BJ minline 360，共 9607 个 .lc1（同目录数量的 .lc5 文件）；截图本来仅显示 sh/fzline 下的 LC5，但 minline 实际存在。原三股 600000.SH、000001.SZ、688001.SH 和 sh000001 指数的 .lc1 全部有效，每个 983040 字节（30720×32）、128 个交易日，每日严格 240 根，样本日期完整，自 2026-05-11 09:31 至 2026-11-13 15:00；其 .lc5 每个 196608 字节，48 根/日。8/8 源文件 32 字节网格、时间顺序、数据格式检查通过，零无效/重复/逆序。已查明 TDX 原始盘后 1min 数据是具有本地持续落盘价值的资料，但是 **仍为 240 根/日，不是直接可用的 QMT 241 根**，且 .lc1 很可能与先前 eltdx 7709 分钟线同源；不能未经测试就认定它能恢复 2026-10-16 688001.SH 09:31 的真实 high。

为此新增 ParquetLiveSync/tdx_local_lc_vs_eltdx_qmt.py 和 tests/test_tdx_local_lc_vs_eltdx_qmt.py。程序仅在 2026-10-14/15/16、三只原样本股票、共 9 个股票日进行：
- 纯本地不联网读 D:\software\TDX\vipdoc 下的 .lc1/.lc5，逐文件复核完整源 SHA256、目标日精确 240/48 根和分钟时间格，检查期间源文件是否发生改动；
- 从已有私有 SHA 收据读取 eltdx 7709 的 240 根 1m，以及独立 QMT 241 根参考（QMT 仅验收，不用于候选数据生成）；严格要求三个来源 09:31~15:00 标签完全一致，**不得平移时间或用 QMT 填补未知**；
- 对本地 .lc1 与在线 eltdx 240、与 QMT 前两根合并成 09:31 的 240、与本地 .lc5（由每 5 根本地 1m 聚合）逐分钟六字段比较，输出严格/宽松匹配根数以及成交量候选倍率 0.01/1/100；倍率只用于研究对账，不调整实际源值；
- 对最重要的 2026-10-16 / 688001.SH，单独报告 local_merged_high_equals_online_merged_high_strict、local_merged_high_equals_qmt_auction_high_strict、local_merged_high_equals_qmt_regular_high_strict、qmt_regular_high_below_auction_high。**如果本地首根 high 与在线同样等于竞价高，则它还是合并 K 的 high，不能直接认作 QMT 09:31 单独连续交易 high。** 即使本地与在线不同，也仅给出样本对账和来源差异，不自动授予真实 high 的生产可信度。
- 报告仅在控制台输出逐日匹配计数/布尔判断及总览，不输出任何原始行情 OHLCVA/不创建文件，不修改用户原已购 Parquet/H5/TDX 文件。全部 source_market_files_modified=false、production_merge_authorized=false。

Windows 单行 PowerShell（需先 git pull，本地三方对账本身无行情联网）：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_tdx_local_lc_vs_eltdx_qmt.py -q; if($LASTEXITCODE -ne 0){throw "LC three-way tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\tdx_local_lc_vs_eltdx_qmt.py --vipdoc "D:\software\TDX\vipdoc"; if($LASTEXITCODE -ne 0){throw "LC local/online/QMT three-way source SHA audit failed"}

反馈 TDX_LOCAL_THREE_WAY_CASE 九行和 TDX_LOCAL_THREE_WAY_SUMMARY 一行，重点 688001.SH 2026-10-16 的 high 数组及每日日积 240/48 差异。原价/原成交额/原始行情不上传。此阶段严禁直接入库，候选 high 仍需独立、完整的 1m 真值证据。


## 2026-11-14 免费第三来源突破路线：先检验新浪/腾讯，再核验 2026-10 的 Level2 逐笔 CSV

先前本地 TDX .lc1 240根与在线 eltdx 7709 240 根，在 2026-10-14/15/16 三股 9 股票日严格六字段一致：这不是独立 241 来源。2026-10-16 688001.SH 的合并 09:31 high==09:25 auction high、QMT 独立 09:31 high 低于竞价 high，该值不能从 TDX 240 唯一恢复。公开来源调查：
- 新浪股票历史分钟数据 CN_MarketDataService.getKLineData 支持 1min OHLCV；AKShare 代码默认 datalen=1970（约 8 个完整交易日），故必须实际测试服务器是否接纳更大 datalen=20000、是否包含 2026-10-16。新浪不保证成交额字段。无需注册的 HTTP 数据不能保证是真实独立源。
- 腾讯 appstock/app/kline/mkline 的 m1 历史分钟接口存在，但是否实际支持超过几日、能否回溯 2026-10-16 或提供独立拆分竞价根，都需要运行验证，不能依据端点命名直接断言成功。
- 东财/AKShare stock_zh_a_hist_min_em 的免费 1min 接口文档明确仅近 5 交易日，因此不是当前 2026-10-16 的可直接回溯来源。
- 第三方 GitHub 仓库 submato/ashare-l2 公开 **2026-10 Level2 逐笔成交 CSV 免费月份链接**，直达页面 https://github.com/submato/ashare-l2 的 2026-10 夸克网盘：https://pan.quark.cn/s/b9ed1e0ba845。GitHub 仓库存的是演示/字段说明而非真实 2026-10 的已核验原数据，网盘文件体积、真实性、源端交易时间和实际使用/再分发权限都未验证；不要安装/运行下载包中的任何 EXE/脚本，只提取可核验单股日 CSV。
- zhituapi 历史逐笔成交宣称可覆盖 2026-08-13 后的日内交易，有 token 使用门槛，作为低优先级候选；其他含历史 1min 的服务可能付费，当前不以商业购买作为方案。

新增 qmt_241_public_minute_crossprobe.py：先 SHA 验证原 QMT241 + eltdx240 源且日网格完整，再每只股票最多两个公开只读 HTTPS 请求（Sina + Tencent），内存解析不保存、不上传原始行情，按实际分钟标记核查是否包含 2026-10-16 09:30、09:31。用只读 QMT 做比较：若第三方 09:31 high 正好匹配原 QMT **且不同于已知 TDX 合并高**，才记为新的 high 候选；若第三方 high==TDX 240 合并高，不能用来填补真实 09:31 high。即便符合也不能立即宣称来源独立、入正式 Parquet。预设只对最关键 688001.SH 做样本，不批量全市场。纯只读。
Windows 单行命令（联网只向新浪/腾讯公开数据域名发起最多 2 请求，不触碰正式库）：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; $b="feat/qmt-one-minute-history-probe-20261112"; if((git branch --show-current).Trim() -ne $b){throw "Branch mismatch"}; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 pull --ff-only origin $b; if($LASTEXITCODE -ne 0){throw "Git pull failed"}; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_qmt_241_public_minute_crossprobe.py -q; if($LASTEXITCODE -ne 0){throw "Public minute source offline tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\qmt_241_public_minute_crossprobe.py --codes "688001.SH" --days "2026-10-14,2026-10-15,2026-10-16"; if($LASTEXITCODE -ne 0){throw "Public crossprobe unavailable"}

新增 qmt_241_l2_csv_crossprobe.py：若用户愿意从 2026-10 免费 L2 索引提取单个 688001.SH/20261016/逐笔成交.csv，则支持本地严格只读 CSV UTF8/GB18030、SHA256、事件代码和 9 位毫秒时间戳，并由调用者明确指定非自动推测的 price_divisor=10000（仅适合 Wind-like 价格×10000 的真实文件；不同来源先看其字段单位）。只认可事件代码 0 作为临时成交筛选；取消类事件 C 与未知标记保留计数但不参与 OHLC 汇总。将 09:25 正式成交和 09:30~09:31 连续交易的价格极值、量（QMT手×100）、派生成交额逐项与 QMT **只读验收**比对。若 09:31 观测高匹配 QMT 且不同 TDX 合并高，则为新的证据；但 CSV 来源真实性、完整逐笔和事件编码均未认证，不能标记生产可用。只使用一个真实的股票/日期，不能处理压缩包、不得运行来源附带安装程序。严禁正式写库。

单行命令（需将文件路径替换为你实际提取的 2026-10-16 688001.SH 逐笔成交.csv）：

    Set-Location -LiteralPath "D:\ChatGPT\AStockDataTools"; $ErrorActionPreference="Stop"; & .\.venv\Scripts\python.exe -B -m unittest discover -s ParquetLiveSync\tests -p test_qmt_241_l2_csv_crossprobe.py -q; if($LASTEXITCODE -ne 0){throw "L2 source schema offline tests failed"}; & .\.venv\Scripts\python.exe -u -B ParquetLiveSync\qmt_241_l2_csv_crossprobe.py --csv "D:\path\to\688001.SH\l2\20261016\逐笔成交.csv" --price-divisor 10000

只有上述免费候选确实包含 2026-10-16 09:31 独立价格且价格/交易时标/事件类型经过核验时，才进入扩容研究；否则仍诚实标记 240→241 严格无损不能在所有股票日由现有来源完成。
