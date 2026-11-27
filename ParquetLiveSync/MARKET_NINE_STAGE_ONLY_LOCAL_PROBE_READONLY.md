# P3.15 仅核对现存九条本地分钟探针（保留历史回执认证阻断）

## 已核实的真实边界

2026-11-27 Windows 在 P3.13 固定提交 `a6c112a35d4812bf8cd6c16562c0c09ecb5119cb` 上通过旧原审计器 15/15、新专项 23/23、选定完整 25 模块 615/615；P3.13 对 `ParquetLiveSync/work/qmt_1min_market/20261014_20261112/receipts` 的 5,039 份直接 JSON 的物理 SHA 全部检验完毕，固定的 2026-11-25 原始运行回执 SHA **零命中**。加上此前分时独立的其他范围 124 JSON，现存指定 `work` 深度≤3 已有 5,163 份 JSON 的逐区只读结论，**不是同一时刻的整体快照，亦不意味着任何其他备份目录中绝无旧回执**。

P3.14 在本机对留存的 `afternoon-20261125-200502-EIGHT_PERIODS.log`、`market_update/daily/2026-11-25.json` 和 `2026-11-25.parquet` **实际执行且成功**三重证据核对：日志唯一 `MARKET_DAILY_STAGED=` 2026-11-25 记录，SHA `974b2c55b46109fb998459a6d97b9955e8e359ac4c3b0a049c0adc1bbd70dd6a`；私有元数据 SHA `eeed821ed64202d8c8b243443f2c9622785e3a0c715c333414e48c70353768a4`；真实候选 Parquet SHA `de113cbd202ea68590780e5509755d843ebc6363a2857399094c09982e6f7eff`。原 5206 accepted / 9 quarantined / 5215 expected、1249440 行、七条原分钟缺失、两条官方 DAY OHLC 不一致均相互符合。但 **原定时回执的固定 SHA `72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837` 仍无原始字节可供复查**，阶段日志的回执原链接与退出码未获认证。

P3.15 是一个**独立残留本地证据实验**：用户此前命令把大量 Python `-c` 字符串通过 Windows PowerShell 5.1 转发后丢失引号，产生 `SyntaxError`，未读取任何探针文件。新实现不再依赖命令行中的嵌入式复杂 Python 代码，也不修改 P3.11 原始安全入口。

## 新增独立只读入口

`market_nine_stage_only_local_probe_readonly.py --module-root D:\ChatGPT\AStockDataTools\ParquetLiveSync`

- 只使用真实现存的 `module/work/qmt_1m_probe` **固定目录**；不允许任意探针路径、递归查找、网络访问或隐式创建；严拒根目录、work、probe 为符号链接。
- 复用 P3.11 的 `market_local_evidence_inventory_readonly.inspect(root,'minute')` 列举物理 JSONL，并沿用**最多 16 个探针、总计 64 MiB 的更严格约束**，接受条件必须明确报告未修改行情、未修改 QMT 缓存、无 QMT 下载、无供应商认证。
- 只复用 P3.11 的单文件 `_probe_scope` 读取/核验：每个真实 JSONL 的 SHA256、实际字节长度、全部分钟行的数值与交易时钟、现存起止日期、每日 241/240/不足网格；**不调用 P3.11 的 `verify_original`、`inspect` 或将伪造的 `audit_reader` 注入生产调用链**。
- 对固定九只隔离股票按 `300119.SZ` 等真实探针符号重映射。若未匹配、只在旧日期有行、匹配到当前日期完整 241、无 09:30 的 240 或同票多文件，分别标注，不选取“最好”的文件。即使本地恰好 241 行，也只能写 `LOCAL_TARGET_DAY_EXACT_241_WITH_0930_NOT_ADMITTED`。
- 首尾各自哈希、清点完整的同一直接文件集合，拒绝任何变动；并保留源检验器自身的 SHA/单文件大小、行数、日期跨度限制。无文件时正确报告九条“没有与隔离同票的有效 JSONL”，不得虚构已恢复九条证据。
- 固定输出 `original_run_receipt_authenticated=false`、`original_run_stage_link_verified=false`、`original_quarantines_cleared=false`、`production_merge_authorized=false`、`market_files_written=false`、`qmt_download_calls=0`。此报告不具备独立供应商 QMT 认证、官方 DAY six-field 校准、源跨立验证或九条隔离解除权限。

## 验收和下一阶段

新增独立临时目录 **15 项专项测试**，覆盖空目录与全部九条仍隔离、三份其他股票、11-12 旧文件同票但不覆盖 11-25、11-25 完整 241 仍不得准入、240 缺开盘、多份同票来源冲突、坏行情 JSONL、文件数和安全状态超限、首尾文件集合改变、拒绝伪造的供应商权限、保证从不调用原运行回执入口、CLI 不泄漏绝对路径。完整选定目标由 P3.13 已过 **25 模块 615 项**增加为 **26 模块 630 项**，另旧原审计器 15 项独立重测。

此阶段代码与合成测试已提交，**尚未执行新的 Windows 15/15、630/630 与本机现存探针实测**。运行后只能根据实际本地文件报告其股票、起止日期与网格。即使全部通过、出现目标日期 241 行，正式 P3.11 审计依然因原 11-25 回执 SHA 缺失而阻断。该独立 PR 与 P3.12/#283、P3.13/#284 一样保持 Draft，不合并 main，不修改 H5/Parquet，不下载 QMT，不放开 9 条隔离。
