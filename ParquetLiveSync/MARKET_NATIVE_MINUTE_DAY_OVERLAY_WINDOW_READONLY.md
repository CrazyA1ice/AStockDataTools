# P3.9 现有原生分钟与本地 TDX DAY overlay 的跨日只读原始差异

## 前置真实证据

P3.8 的用户 Windows 固定提交 `7fb265772eb94e5b09dafae76e698803fa58ab56` 已完成 **494/494** 单元测试与生产 241 格一致性核对，实测本地现存三个 QMT 探针私有 JSONL 在各自 2026-10-14～2026-11-12 日期窗口内：各 **22 个精确 241 根分钟日期 + 8 个无行自然日、5302 根有效行**。三股合计 66 个“本地一分钟格点完整”的股票日期，物理 SHA 未变。

这一成果**不是**来源提供商身份认证，不是官方股票日全集，也不能解除 2026-11-25 的原九条生产隔离。当前三份文件不覆盖那一天。

## 新增功能

`market_native_minute_day_overlay_window_readonly.py` 结合已有三个真实生产只读验证模块：

- `market_native_minute_window_readonly.inspect`：首次完整核对本地分钟源的真实 SHA、逐行数据、时间格点及日期覆盖；然后再次只读扫描这一文件并守恒各日期行数，最终再重新哈希确认文件身份、内容和大小未变。
- `market_native_minute_jsonl_readonly.check_rows`：仅对第一步已证实的完整 241 根日期单独重新计算未校准的原始 OHLCVA；240 根、部分缺格和无行自然日不伪装成可比较样本。
- `market_live_day_overlay_audit.inspect`：从操作者本地**真正**的 `ParquetLiveSync/work/state.json`，及其对应 DAY 回执/Parquet 文件读取每个有分钟源的日期，按原有固定基线、原状态 SHA、原回执 SHA、原 DAY 物理文件 SHA 和目标证券行逐日验收；**不是**从 detached worktree 的空 `work` 目录寻找数据。这里的“TDX DAY”仍仅是本地声明，默认不验原始供应商 ZIP 的身份。
- 若 DAY 本地状态未登记日期、日期在 overlay 范围外、或声明 DAY 中没有活跃目标证券，输出精确的“**声明来源未提供可比较证据**”类别；而任何 DAY 状态篡改、接收据/Parquet SHA 不符、提供商/入库授权伪造或数据非有限等异常必须直接失败，不能偷偷降级为“缺 DAY 数据”。跨日期 DAY overlay 状态 SHA 不得发生变化；否则终止。
- 对两个经过各自物理字节验证的来源计算每个精确 241 日期的六字段**未校准的原始数值差和相对差**。即便恰好一致，也必须保持 `paid_minutes_units_or_timestamp_calibrated=false`、`six_field_quality_passed=false`、`data_source_independence_or_provider_identity_certified=false`、`production_merge_authorized=false` 等。诊断不是跨供应商认证、涨跌复权或开盘 09:30 与付费 240 格同口径匹配。
- 每次请求至多 32 个完整 241 格日期与不超过 P3.5 限额的一个分钟文件；逐个 DAY 检查沿用原只读入口资源限制；不自动递归磁盘、不创建 DAY、不调用 xtquant、不下载 QMT 历史、不修改任何市场 Parquet/H5、缓存、生产回执、九条隔离或定时任务。

## Windows 使用方式

这三份原始 JSONL 的输入文件名、实际物理 SHA 与上一轮 P3.8 日志一致。新工具需要两个**不同用途**的路径：`--minute-evidence-root` 指向本地既有的 `work/qmt_1m_probe`；`--module-root` 必须指向**项目真实运行的** `D:\ChatGPT\AStockDataTools\ParquetLiveSync`，因为 DAY overlay 的真实 `work/state.json` 与 Parquet/收据并不位于 detached HEAD worktree 内。

示例（替换 `PINNED_P39_WORKTREE` 为经过 Git SHA 校验的实际隔离目录）：

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_P39_WORKTREE\ParquetLiveSync\market_native_minute_day_overlay_window_readonly.py" --minute-evidence-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync\work\qmt_1m_probe" --minute-file-relative "000001_SZ-20261014-20261112-2620212c96e35063.jsonl" --expected-minute-sha256 "2620212c96e350630aae8524dec531ef0201e0dc3db7b3d0f9ff0d4547762037" --symbol "000001.SZ" --start-day "2026-10-14" --end-day "2026-11-12" --module-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync"
```

如真实 `work/state.json` 不存在、没有该 DAY 或原官方来源尚未录入，必须如实返回无法取得该一层证据；不得为了运行成功新建或重做生产 DAY、擅自下载或把 QMT 的分钟文件当作独立 DAY。

## 测试与验收

P3.9 新增 **23 个**针对实物临时 JSONL SHA 与合成 DAY overlay 回执的单元用例，覆盖 241/240/239、无行自然日、已有分钟跨日守恒、缺少 DAY 状态的保守分类、DAY 身份/权限伪造与异常、DAY 状态跨日变化、错误 SHA/来源变化、单日范围上限和禁止写入。提交代码与测试已在 GitHub 的独立 Draft PR 上，尚须 Windows **累计 517 = 494 + 23** 项实机测试及三个用户现存文件的真实 overlay 联测；不能提前称本轮 23 项已通过真实 Windows。

若真实 DAY overlay 存在且验收成功，输出 66 个股票日期与 DAY 的原始差异将用于决定购买源时间偏移及量额口径是否需要逐股、逐日校准；它仍**不是**可靠的独立官方来源身份认证，也不构成对原九条隔离的恢复资格。
