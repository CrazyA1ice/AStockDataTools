# 财务主线：Capital.m_quarter 来源附加列差异，不再阻断实际股本

2026-11-18。正式基线 P69 `4bd97daf`，P70 只读消费者虽已通过 223 个 Python 回归，但本简化方案不依赖 P70，也不修改 P69 历史事务。

## 外源字段结构对照

- 迅投官方 QMT Capital 股本表列出 `total_capital`、`circulating_capital`、`restrict_circulating_capital`、`m_timetag`、`m_anntime`，**未列出 `m_quarter`**。来源：`https://knowledge.thinktrader.net/docs/dictionary/stock.html` 的“股本表”一节。
- 社区 QMT 兼容列举 `CAPITALSTRUCTURE` 不含 `m_quarter`，但 `PERSHAREINDEX` 含该列。来源：`https://github.com/litaolemo/xtquant_big_convert/issues/52`。
- Tushare `daily_basic` 提供 `total_share`/`float_share`/`free_share`（单位万股），不提供 `m_quarter`；BaoStock `query_profit_data` 提供 `totalShare`/`liqaShare`，不提供该列。此处仅验证**外源字段模式**，不是实际逐股股本数值已交叉验证；不同表的日期和计量单位不得直接混比。

## 业务规则

只对**显式启用** `--capital-mquarter-nonbusiness` 的财务导入任务生效。直接复用 `qmt_capital_semantic_proof.prove_historical_union` 的全历史比较：
- 仅当旧版所有选中记录与当前 QMT 缓存的 `m_timetag` 报告日期集合相同、其他所有原始字段（包括三类实际股本和公告日期）完全相同、只有 `m_quarter` 取值差异时，新增保留当前原始值的内容寻址 Capital Parquet 快照并释放该股票 pending。
- 严格拒绝额外的真实股本/业务字段变化、报告日期新增/删除、旧历史业务字段冲突或坏记录。其他八张财务表仍全部严格比较；一只股票一旦任何表不合格不允许写入该股票的九表事务结果。
- 原始历史 Parquet 不覆盖、不删除；包含旧 `m_quarter` 版本仍可作为审计证据。全局 mass guard 不关闭；它会在待审真正逐步减少到阈值以下后自然停止阻断无人值守日更。暂时被拒绝的股票保留 pending。
- 默认 Python API/CLI 仍是严格模式，只有 `--capital-mquarter-nonbusiness` 明确传入才启用。正式 `run-qmt-financial-daily.ps1` 包含该参数，避免后续恢复成功后又被重复隔离，但明天仍可能被 global guard 阻断，需先用缓存重试减小 pending。
- 首先只在本机使用 `--mode cache --retry-pending` 分批处理，不用 `--mode daily` 补全历史，不重新下载已存在的 QMT 财务资料。原始进度/隔离账本仍采用现有 CAS 和原子写入机制。

## 本机快进合入后用于小批量应用

先确认真实 QMT 已登录并正常运行、20:05 自动任务非运行中，处在计划任务之外的时间段。每一批只处理 pending 中按代码排序的前 N 只，成功会从 pending 删除，失败原样重入 pending。第一批建议 N=20：

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -u -B "D:\ChatGPT\AStockDataTools\ParquetLiveSync\qmt_extra_financial_cache_import.py" --root "D:\stock" --mode cache --retry-pending --finance-dir "D:\software\JHQMT\datadir\Finance" --batch-size 5 --max-symbols 20 --max-minutes 20 --worker-timeout-seconds 180 --capital-mquarter-nonbusiness --apply
```

**注意**：未处理的 pending 一直保留；含新增报告日期的股票当前仍可能被拒绝，后续只为这类真实新增报表设计独立 append-only 规则。以上命令是会修改财务 Parquet 及私有 pending 的真实 apply，不属于只读测试，必须先验收新定向烟囱测试和固定提交。
