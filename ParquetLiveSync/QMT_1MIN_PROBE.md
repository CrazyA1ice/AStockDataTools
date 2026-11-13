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
