# 2026-11-25 七只 QMT 1 分钟缺口：先计划、再显式授权的缓存补取

> **当前未获真实 QMT 缓存写入授权。本阶段只提交并离线测试代码，默认运行仅输出计划，不连接/读写 QMT。绝不自动执行历史下载。**

## 实机证据

2026-11-25 owner Windows pinned PR #259 查询：SZ300119～SZ300125 七只在 11 月 20/23/24 日各有 241 条 QMT 原生 1m，**仅 11 月 25 日各 0 条**。官方 DAY 共 5215 只，已接收 5206、隔离 9。PR #260 owner Windows 36/36 测试通过：另外两只开盘价候选 SH605336 09:32 成交开 7.62 = 官方，SZ300462 09:33 成交开 9.40 = 官方，但其原本 240 兼容序列仍隔离。PR #261 增加只读 SHA 固定的候选 manifest，实际离线 18/18 PASS。

## 代码范围

新文件 `qmt_seven_single_day_cache_refresh.py`，基于 Draft PR #261。**没有修改任何项目生产文件、原始 11 月 25 日私有 Parquet/JSON、20:05 TaskScheduler、企微报告器或下载器。**

默认执行：

```powershell
& 'D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe' -B 'PATH_TO_PINNED_AUDIT_WORKTREE\ParquetLiveSync\qmt_seven_single_day_cache_refresh.py' --module-root 'D:\ChatGPT\AStockDataTools\ParquetLiveSync'
```

结果严格是 `SEVEN_ONE_DAY_QMT_CACHE_REFRESH_PLAN_ONLY_NO_QMT_CALLS`，同时显示七只股票及 `qmt_download_calls=0`，**不会读取也不会写入 QMT**。

只有以后单独、明确同意改变 **QMT 自有 datadir 缓存**，且在正式任务不执行的时间窗口，才可审阅参数：

`--approve-qmt-cache-write-exact-seven-nov25`

这个参数**在本次开发和离线测试中绝不对真实客户端使用**。仅有此参数还不代表允许项目数据库修改。

## 真正获批后会执行的有界行为

1. 先固定核对原正式 2026-11-25 接收回执 SHA256 `72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837`，原 9 隔离、物理候选 Parquet 的真实 SHA、5215 股独立官方 DAY 及原校准哈希；核验生产转换模块固定 Git Blob。
2. 只读调用一次 `get_market_data_ex` 查询七只证券在 11/20、23、24、25 的现有 QMT 缓存。必须**全部满足前三日恰好 241 条、25 日零行**；如有任何状态漂移，零下载、提前停止。
3. 对固定七只 `300119.SZ`～`300125.SZ`，逐只仅调用一次 `xtdata.download_history_data(code,period='1m',start_time='20261125',end_time='20261125')`。不允许多日期、多证券、自动重试、定时调度，下载对象只允许 QMT 客户端自己的缓存。**这一步可能实际改变 QMT 自有缓存，属于必须明确授权的副作用**。
4. 若下载中途失败，停止进一步下载，并报告已完成调用数；不能自动回滚 QMT 内部文件，也不做任何项目数据修复。
5. 下载调用完成后，只读一次固定七股 2026-11-25 缓存；对每只用原 `normalize_frame` 和 `normal_qmt_day` 重新运行原购买源校准、241→240 网格和独立官方 DAY OHLCVA 校验，**仅在内存**输出 `CACHE_DAY_VALIDATED_IN_MEMORY_ONLY` 等状态。QMT 历史下载函数返回不等于分钟数据已恢复；项目 Parquet/日线/H5 和隔离记录继续不动。
6. 即使全部成功，返回 `production_merge_authorized=false`、`data_quality_cleared=false`、`original_quarantines_retained=true`；仍需新的、版本化独立私有候选和明确审核通过才能考虑实际写库。不存在“顺手覆盖原始 5206+9 回执”的路径。

## 回归验收

在隔离 Python mock 环境（**不连接真实 xtquant**）执行：
- 原开盘价 22/22 PASS；
- 原七股跨日 14/14 PASS；
- PR #261 候选证据 18/18 PASS；
- 新七股单日缓存流程 15/15 PASS（默认零连接、完整七股下载指令的有界模拟、回执/官方日线/校准 PIN、缓存漂移自动停机、第三次下载失败不重试、下载后无行仍拒绝、官方校验异常仍隔离）。
- 合计 **69/69 PASS**，语法检查 PASS。

新源码 Git Blob `8cd6bbdcd08f88a493cc7b819c44458d2eb5b68f`，新测试 Git Blob `9e993ba9b87aa07c7365b6883bac788de99c4012`，与本轮实际测试字节一致。**新 PR 的 Windows 真机验收还未进行**。

这里的 `download_history_data` 可对 QMT 客户端自身产生写入、流量与更新副作用，不能称为端到端只读。此 Draft PR 仅准备将来可能使用的明确授权路径，不暗示用户已经授权、更不因“继续下一阶段”就擅自启动缓存写入。
