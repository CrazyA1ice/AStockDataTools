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
