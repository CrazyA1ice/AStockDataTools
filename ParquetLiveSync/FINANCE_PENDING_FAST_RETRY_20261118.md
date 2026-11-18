# Pending 财务回填主线加速（2026-11-18）

## 已观察真实结果

基线 `cd4cda8d` 首批 20 只 QMT 历史缓存修复：`processed=19`、`new_snapshots=24`，`pending_total` 从 5003 降至 4984。仅 `000010.SZ` 因 `Capital` 报告日集合变化 `REPORT_KEYS_ADDED_OR_REMOVED` 保留隔离；这是需要单独验证的新/缺报表日期，不可以按 `m_quarter` 元数据差异忽略。

首批 `_stock_universe` 从交易板块+财务缓存目录重建 5656 只股票，单次查询耗时 `266.594` 秒。后续单纯重试 pending 不需要再次获得整个上市公司目录，且总是重试前 N 只会被已知无法放行的股票永久阻塞。

## P71 仅优化重试调度

- 只在 `--mode cache --retry-pending` 且已存在本地**经过 `_state` 验证的 pending 账本**时，直接以 pending stock codes 作为源目录；不重新枚举 QMT 板块和全部 DAT 文件。普通全市场首次导入及每日财务更新仍执行原有目录核验、mass conflict guard。
- 账本增加向后兼容可选字段 `pending_retry_cursor`，每只被尝试的待审股票保存新的游标（包括仍失败者）。下一批先处理游标之后的股票，到末端再绕回，不再被固定早期失败股票饿死。正式的 `import_cursor`/`daily_cursor` 保持不变。
- `--capital-mquarter-nonbusiness` 下仍逐股调用原有九表、完整原始历史版本验证。合格时保留旧快照、创建新的内容寻址版本、移除相应 pending；不合格继续留在 pending。
- 此优化**不解除**任何真实股本修订或报告日期变化的封锁，不改变 `Top10Holder` 或 `CACHE_DECODE_ERROR` 的特殊处理，不关闭现有全局日更熔断。
- 每个 QMT worker 的超时与总时间预算都只能在批次边界生效；全市场修复应循序增大 batch，不要在自动 20:05 更新窗口附近启动长时间缓存扫描。

## 推荐命令（代码本地验收后执行）

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -u -B "D:\ChatGPT\AStockDataTools\ParquetLiveSync\qmt_extra_financial_cache_import.py" --root "D:\stock" --mode cache --retry-pending --batch-size 5 --max-symbols 50 --max-minutes 40 --worker-timeout-seconds 180 --capital-mquarter-nonbusiness --apply
```

命令会真实修改对应 Capital 或其他被既有九表逻辑认可的财务快照与私有进度账本；不修改日线、分钟线、H5。请保持 QMT 登录，确保任务不在执行，不同时运行其他财务回填命令。
