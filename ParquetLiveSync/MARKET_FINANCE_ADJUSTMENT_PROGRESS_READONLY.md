# P3.18：只读取证当前补充行情与财务缓存的两份独立进度账本

## 目的与证据范围

实际 2026-11-25（运行标识 `20261125-200502`）定时轮次在 P3.17 得到日志、输入、报告和阶段路径的物理 SHA 交叉确认：校验前 `SUCCESS`，执行层 `PASS`，数据层 `PARTIAL`，整体跨源 `UNVERIFIED`，整轮最终 `PARTIAL`。当晚四阶段进程全部退出码 0；八周期有原九条隔离、板块 904992 条成员、除权本批 80 只且仍须轮转、财务本批 177 只、待审 77、未遍历 4526，财务历史完整性未认证。P3.14 源阶段日志 SHA `974b2c55b46109fb998459a6d97b9955e8e359ac4c3b0a049c0adc1bbd70dd6a`，私有日元数据 SHA `eeed821ed64202d8c8b243443f2c9622785e3a0c715c333414e48c70353768a4`，真实候选 Parquet SHA `de113cbd202ea68590780e5509755d843ebc6363a2857399094c09982e6f7eff`。11-25 原定时回执固定 SHA `72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837` 仍没有恢复物理原件，不能解禁原九条隔离。

历史 `77` 和 `4526` **只表示当次财务日报告中的队列快照**。实际当前的本地进度没有在 P3.17 核验，不能假设它们依然如此；除权也不能只凭 11-25 的 80 推断当前进度。

## 两份不同状态的真实来源

在源码 `qmt_extra_data.py` 中：`WORK = <module>/work/qmt_extra`；`_state_path(workspace) = workspace/progress.json`；`state.cursor['adjustments']` 是除权已处理的股票代码高水位游标，`financial_pending` 是此模块自己的旧财务挂起队列。该游标**没有**全市场余量字段，只靠一个代码值无法认证扫描全部股票。

在 `qmt_extra_financial_cache_import.py` 中：`STATE_FILE='financial-cache-progress.json'`。另一个状态文件独立保存 `daily_date`、`daily_cursor`、`daily_sweep_start`、`daily_sweep_reached_end`、`daily_sweep_finished`、`pending_retry_cursor`、`pending`。它们不等同于前一份 `progress.json` 的 `financial_pending`，**不能把两份 pending 相加后与 11-25 历史数字比较**。单一 `daily_sweep_reached_end=true` 是账本声明，不代表官方交易数据、全部财报历史、供应商独立认证或九条行情隔离解决。

## 新增仅两文件只读工具

`market_finance_adjustment_progress_readonly.py --module-root D:\ChatGPT\AStockDataTools\ParquetLiveSync --stock-root D:\stock`

- 只使用模块内部固定 `work/qmt_extra`，仅允许读取该目录下**直接** `progress.json` 与 `financial-cache-progress.json`，要求 `--stock-root` 明确对应现存 `D:\stock\AllCycleAStockData\qmt_extra` 的实际根目录身份。
- 现存非链接正规 JSON 才视为已检查；文件缺失仅输出 `present=false`，**不创建初始账本、不静默视为 pending=0 或完成**；任一非空文件最多 8 MiB，两个共最多 16 MiB；先按完整物理字节 SHA、打开文件的 `os.fstat` 与独立路径 `os.stat` 一致性校验，再针对相同两个确切文件重哈希、检查目录元数据稳定性。没有跨文件写锁，明确 `state_cross_file_atomic_snapshot_certified=false`。
- 严格验证记录 `format/root`、日期与股票游标类型、pending reason／table／attempts；只输出数量、类别、游标和每个文件 SHA/字节数，不输出私有 pending 股票名单或正文。符号链接、路径身份不符、非法 JSON、超预算、运行中变化全部拒绝。
- 财务缓存 `pending` 计数只依据其自己的状态，真正剩余的未遍历股票数需要同一轮已认证股票全集，不从游标字符串或 11-25 旧数字反推；除权同理。
- `qmt_cache_queried_or_modified=false`、`market_files_written=false`、`original_run_receipt_authenticated=false`、`original_quarantines_cleared=false`、`finance_full_history_coverage_certified=false`、`adjustments_universe_exhaustion_certified=false`，并明确无 QMT 下载或生产权限。

新增 16 个只用临时目录和合成状态文件的单元测试。现有 P3.15 已在用户 Windows 通过旧原审计器 15/15、15 项 P3.15 专项、26 模块 **630/630**；叠加本阶段后待验收目标 **27 模块 646 项**，旧审计器额外 15 项。**P3.18 尚未取得 Windows 新 16 项和 646 项实机通过结果；也尚未读取用户真实当前两份进度账本**。只有通过固定提交下的 Windows 测试，才能运行对实际已安装 `ParquetLiveSync/work/qmt_extra` 的只读核验并报告当前保存的游标/待审分类。保存的进度并不是 QMT 当前事实或历史原收据。

所有相关 PR 继续 Draft，不触发调度、QMT SDK、行情下载、H5/Parquet 写入、旧回执重建、九条隔离释放或 main 合并。
