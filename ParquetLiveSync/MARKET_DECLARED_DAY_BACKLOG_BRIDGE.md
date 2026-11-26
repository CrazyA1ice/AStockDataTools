# 声明来源 DAY 差异接入长期质量待办（只读）

这是 AStockDataTools 的通用行情质量治理模块，**不是 2026-11-25 的单日修复脚本**，也不是认证数据商身份或正式写库的程序。前置 PR #269 在用户 Windows 上的 254/254 项测试全部通过；真实 TDX DAY 只读来源链对 SH605336（开盘 7.62）和 SZ300119（开盘 15.60）再次通过 SHA/内容验收。原九只分钟异常仍被隔离。

## 解决的问题

PR #269 的 `market_day_universe_crosscheck.py` 会对一份真实 SHA 固定的 DAY 物理覆盖文件与**用户另行提供、同样 SHA 固定但仍未经独立身份认证**的证券日交易状态 JSON 分桶。这些“声明来源差异”过去只能以单独报告查看，无法汇入此前已完成的、按交易日/证券/周期/来源/规则稳定编号的 `market_quality_backlog.py`。

新 `market_declared_day_backlog_bridge.py` 使用两个**新增的、明显限定证据范围**的通用质量规则：
- `DECLARED_DAY_STATE_CONFLICT`：参考声明有成交而 TDX 文件缺失或零成交、参考声明无成交但 TDX 文件有正成交。状态 `DETECTED` 仅指**两份声明互相不一致**，不代表独立交易所行情错误已被证明；在待办中为 P2，而不是正式市场数据损坏 P1。
- `DECLARED_DAY_REFERENCE_UNCERTAIN`：TDX 有证券代码但声明参考未列，或参考把证券日交易状态写成 UNKNOWN。状态 `INSUFFICIENT_EVIDENCE`，待办 P3；不能把未列股票称为非法证券，也不能把 UNKNOWN 记成无成交。

已匹配的成交/无成交记录不新建故障；不会因为一日所有对照匹配而证明完整交易所股票日全集。仍需独立来源身份、名单覆盖范围、量价校准、分钟时间格点及六字段验证。

## 实施流程

1. **数据取证**：`market_day_universe_crosscheck.inspect` 只读读取现有 TDX `state.json → 日回执 → DAY Parquet`，验证 SHA、日期、OHLCVA，与用户明确提供的相对路径参考 JSON/文件 SHA 对照。输入不能来自为通过测试而复制的同源 DAY 假清单。
2. **严格交叉核对**：桥接层再次验证原 crosscheck 的规范 JSON SHA、九种已定义分桶、字段种类、每桶排序和计数、全局无重复证券、参考证券数量守恒以及 TDX 物理存在证券数量守恒。若比较期间字段/来源或权限标志变更，直接 fail-closed。
3. **产生通用事件**：将需要处理的股票日差异转换为 `market_quality_engine.analyze_batch` 的标准质量 case，交由现有 `market_quality_backlog.build_backlog` 按长期规则版本签发稳定事件 ID；同一个证券日可保留证据版本而不覆盖旧问题。案例 `source_id=tdx-day-declared-compare` 和 `period=day` 与原 `qmt-daily-stage/1min` 来源分离。
4. **可选保留生产隔离**：显式参数 `--include-existing-producer-quarantines` 可额外读取**同一天已存在的**每日 QMT 暂存回执，把原隔离质量 case 一并投入只读聚合；必须精确校验原隔离条数，既不消除原规则也不把 DAY 结果当作 QMT 1 分钟已恢复。
5. **报告和安全**：`--summary-only` 隐藏逐事件细节，仍报告稳定事件数和 SHA 来源范围。所有正式写入、自动修复、自动关闭旧隔离、QMT 下载和行情质量 PASS 许可固定为 false。

**重要哈希含义：** 原 `tdx_overlay_parquet_bytes_sha256` 是 TDX 日线文件本身的字节 SHA，**不是 QMT 原生分钟数据 SHA**；参考 JSON SHA 证明该文件字节未变，**不是交易所/数据商的来源签名**。规范化 case 的 SHA 是诊断证据版本哈希。稳定 incident ID 是规范化身份哈希。

## 只读 CLI

只有当你**确实有合法取得的另一个来源的证券日参考 JSON 及其真实文件 SHA**，才运行以下示意命令。不能用 TDX DAY 自己复制一份来制造独立来源验证通过：

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_WORKTREE\ParquetLiveSync\market_declared_day_backlog_bridge.py" --module-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --trading-day 2026-11-25 --anchor-symbol SH605336 --reference-root "D:\PrivateEvidence\DeclaredDayUniverse" --reference-relative "2026-11-25.json" --reference-sha256 "<该参考文件真实SHA256>" --include-existing-producer-quarantines --summary-only
```

若参考文件不存在或其 SHA 改变，命令直接失败，不使用网上猜测的证券名录替代，也不触发自动补数据。若原当日生产回执缺失、已有隔离数量不一致，也直接拒绝合并。

## 测试、发布与后续

前置 PR #269 的用户 Windows 实机回归 **254/254 PASS**，当天原 TDX DAY 来源链的实际 SHA 没有变化。

本轮新增桥接器及两条通用规则，在隔离 Python 3 环境使用**与通用内核/待办模块接口相符的独立合约桩**完成 25 项无文件写入单测：包括多个日期、不同来源标签、分桶与物理数量守恒、差异分类、原隔离保留、非法来源权限、SHA 改变、重复证券、空差异、证据不足等，**25/25 PASS**。这仍不能代替用户 Windows 对本草稿分支、真实 Q/B 代码与新规则执行的完整回归；用户本机原 254 项结果不能自动扩大为 279 项。真正的外部参考证券日清单尚未提供，因此**未对真实独立来源做交叉比较，更没有清除九只股票隔离**。

下一阶段应先获得有据可查的独立证券名录/交易日及供应商身份凭证，再进行跨日期真实差异复核；此阶段不得自动持久化新待办数据库、写 Parquet/H5、更新 Windows 定时任务或企微推送、下载 QMT 历史、合并 main。
