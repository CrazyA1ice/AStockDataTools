# Finance P5：两只Capital疑难股票，旧快照 vs 当前QMT已有缓存的单次只读比较

## 前提
Finance P4于2026-11-21用户Windows固定SHA `029632080b3bd3a85e4476edcfae81805e107e37` 验收340/340 OK：8只样本，9份旧快照内容地址、schema及记录身份已验证，8个active pin的SHA256已核验；合计1052行/45280压缩字节。P3确认42只Capital首阻断中36只是报告期集合变化，6只是业务/日期字段变化。即使本地快照指纹通过，也不说明QMT当前缓存或源头可信。

## 目的与边界
增加 `market_center_finance_capital_cache_compare.py`，需同时显式提供 `--explicit-readonly` 和 `--explicit-qmt-cache-read`，以及canonical状态模块、市场根目录、精确账本SHA。任意缺失或账本变化fail-closed。北京时间19:50–20:25禁止扫描。

先重用P3验证账本SHA和8组元数据，随后从账本中只选择 **2只 Capital**：报告期增删类1只、业务/日期字段改变类1只；优先复用P3样本。每只重审本地所有相应Capital历史候选快照，文件名指纹、schema、行身份由现有P4/底层validator核查，遵守每类范围和总计最多8文件、8MiB压缩预算。只构造选中旧版的Counter并集，不覆盖任何不可变版本。

之后启动最多2个15–30秒受限的独立Python子进程，每只只调用 **一次 `xtdata.get_financial_data([stock], [\"Capital\"], start_time=\"\", end_time=\"\", report_type=\"report_time\")`** 读取QMT现有本地财务缓存；没有 `download_financial_data2`、没有任何其他下载/历史更新接口，且不向磁盘写缓存输出。子进程只将各条记录每字段的规范哈希，通过被父进程捕获的管道传递，不将原始财务值/报告期输出到终端、文件或GitHub。返回值预算3MiB，每只缓存记录≤2000且字段≤128；异常、超时、非法回复立即失败关闭。

父进程按规范哈希比较旧报告期键集合与当前缓存、共同报告期下的业务字段差异、历史多版本间业务字段冲突、仅m_quarter变化的可能性。只输出计数、变动字段名称与受限股票标识；任何比较结果只代表 **当次QMT现有本地缓存**，不能保证源头完整/更新及时、不能证明九表全部一致、不能批准忽略旧冲突或更改财务pending。对账本SHA在QMT调用前后再核验；出现变更则拒绝公布对比结果。

本P5为现场用户主动触发，绝不自动部署或运行于20:05。全部输出标记 `download_calls=0`、`can_repair=false`、`market_file_writes=false`、`source_authenticity_certified=false`。

## 验收
2026-11-22用户Windows已完成原P5 **15/15项专项模拟测试PASS**，离线预检两类样本成功；随后经双显式授权读取了 `000010.SZ` 与 `000055.SZ` 两次QMT已有Capital缓存，报告键差异13个及 `freeFloatCapital` 变化2个键，未下载/写入/清pending。这仅为抽样本地缓存证据，不能认证历史源头。当前新增报告键日期模式及其扩展专项模拟测试**尚未Windows复验**，需在该模式成功返回后才报告日期。PR保留Draft。

## P5 离线预检门禁（2026-11-22 新增）

在发起任何QMT本地缓存读取之前，支持同一个 `market_center_finance_capital_cache_compare.py` 的 `--preflight-only --explicit-readonly` 模式（**不能**同时传 `--explicit-qmt-cache-read`）。此模式复用与真正compare完全相同的 P3账本SHA/P4旧快照内容校验/Capital两类首阻断股票选择与8文件/8MiB预算，但**不启动独立QMT子进程、不读取当前缓存**。若没有两种证明类别各一只合格样本、旧快照缺失或当前账本SHA与预先锁定值不同，立即拒绝。

成功回执仅展示两只股票代码、两类记录证明类别、旧快照版本/候选数与防护标志；并严格声明 `qmt_cache_calls=0`、`download_calls=0`、`current_qmt_cache_compared=false`、`actual_conflict_report_dates_located=false`、`can_repair=false`。这一预检不会证明当前QMT缓存和旧历史一致，也不意味着两只样本覆盖了其余全部Capital冲突。

**运行示例（命令中的SHA必须来自当前正式P2账本审计，不能使用文档中2026-11-21旧SHA）：**

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" "D:\ChatGPT\AStockDataTools\work\gui-quickcheck-review\ParquetLiveSync\market_center_finance_capital_cache_compare.py" --state-module "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --market-root "<实际AllCycleAStockData绝对路径>" --expected-progress-sha256 "<当前完整64位账本SHA>" --preflight-only --explicit-readonly
```

预检成功后，真实QMT本地缓存比对必须由操作者另外显式指定 `--explicit-readonly --explicit-qmt-cache-read`，并重新通过全部旧快照/账本SHA校验；新预检**不会自动启动**真实QMT读取。原始财务值不出终端，不创建修复/回滚授权。

## P5 股本变动日期键定位（2026-11-22 实机已验收）

用户的真实 P5 缓存读取已重现两类Capital冲突：`000010.SZ` 现有缓存比原快照多 **13个报告键**（另116个共同键 `m_quarter` 指纹变动）；`000055.SZ` 共同的173个键中，**2个键**的 `freeFloatCapital` 指纹变动。旧比较只输出这些差异的计数和字段名称，无法直接回答是哪几个日期。

新增明确的可选开关 `--report-key-date-details`。它**仍须同时**指定 `--explicit-readonly --explicit-qmt-cache-read` 与当前账本的完整SHA；禁止与 `--preflight-only` 混用。对既有QMT缓存读取的数量仍为每只一次（至多2只），同样有25秒子进程默认超时、P3/P4旧快照验证与账本SHA前后复核。正常 P5 不传此开关时，报告键指纹与输出计数维持原逻辑。

日期标签从与原SHA256哈希**同一个** `m_timetag` 字段解析，不替换或重新定义报告键。仅接受明确的YYYYMMDD、YYYYMMDDHHMMSS、规范ISO日期/时间或可严格转换的Unix毫秒时间戳；错误、不明确、多键映射同一天、历史修订歧义均拒绝日期明细，绝不猜测。日期预算 **最多32个差异键**，超限不截断；仅输出旧版独有/当前缓存独有的报告键日期、共同键中发生变化的**非m_quarter字段名称及日期**。大量 `m_quarter` 差异仍仅保留原计数，不列出116个日期标签。

**证据性质：** 返回的是本地QMT `m_timetag` 对应的日期标签，**不是已经认证的法定财报报告期或公告日期**；不提供任意财务原值、数额、完整持仓或未经限制的历史明细。无论本轮结果如何，`source_authenticity_certified=false`、`can_repair=false`、`market_file_writes=false`、pending不变、20:05任务不变。仅对之前的2只试点股票复核，不代表全体45只Capital首阻断记录。

Windows现场应先运行P5专项模拟测试，再用固定Git HEAD、固定当前账本SHA调用相同脚本并显式添加 `--report-key-date-details`；实际日期尚未取得，不能将预期13个日期/2个日期当成已经实测的值。

## Capital 日期语义核对及最小防误用改动（2026-11-22）

用户在本机固定 `60e5d32dda65779917ee0f22deeb18cde3e798a3`、财务账本 SHA `344aebeacecdaab7113b65e36fbd09932b96b7fababbc0dcadface8d28c9c7b7` 的 P5 日期模式验收：**24/24项测试 PASS**，离线预检成功，QMT已有 Capital 缓存只读2次、下载0、写文件0、未解除pending。

- `000010.SZ`：新增13个 `m_timetag` 日期键：2025-08-13、2025-09-30、2025-10-23、2025-12-13、2025-12-17、2025-12-31、2026-03-31、2026-04-15、2026-06-12、2026-06-30、2026-08-05、2026-09-18、2026-09-30。**5个是日历季度末，8个不是**。另有116个共同键的`m_quarter`变化，原非季度字段值对比0差异。
- `000055.SZ`：`2026-11-12`、`2026-11-13` 两个变化日期上的 `freeFloatCapital` 哈希值与历史快照不一致，两个日期都是非季度末。现有记录不能证明历史版与现时版谁正确。

复核迅投 QMT 股本表字段说明：在 **Capital/CapitalStructure** 表内，`m_timetag` 表示**股本变动日期**，`m_anntime` 才表示**公告日期**；`freeFloatCapital` 是旧版本**自由流通股本**字段名称，较新版本可能称 `free_float_capital`。官方参考：[迅投知识库·行情函数](https://dict.thinktrader.net/innerApi/data_function.html)（CAPITALSTRUCTURE 字段表）。Capital变动日期可能不在季度末，**不能因其不是季末就断定数据错误**。QMT本地日期键也不是第三方证实的事件生效日或公告日，必须等待对应公司公告/交易所股本变动证据。

P5现有`report_key_date_details`字段名为兼容历史回执而保留，新增**纯日历分类元数据**：`capital_date_role=SHARE_CAPITAL_CHANGE_DATE`、`capital_announcement_date_field=m_anntime`、`capital_announcement_dates_verified=false`、`calendar_quarter_ends_required=false`、`change_event_sources_verified=false`、`free_float_capital_alias_normalized=false`、`calendar_only_date_counts`。仅按日期标签划分季末/非季末，不影响历史SHA指纹、原始差异分类和冻结pending；对`freeFloatCapital`和`free_float_capital`不自动视作一致或覆盖旧值。新增两项模拟测试核验13键5/8日历分类、相邻日期2个自由流通股本差异，确保不触发自动修复。

**下一环节**：先只读审阅与这些日期有关的`m_anntime`（仅日期及字段是否存在）及公开股本变动证据；在有明确披露依据前不调用东方财富三表、不补历史金额、不更新QMT源头、不放行pending。新的日历分类代码**尚未在用户Windows运行**，不能将旧回执误称为已包含新字段。

## P5 Capital m_anntime 限定证据预检（2026-11-22，新增待 Windows 验收）

在用户 Windows **26/26专项模拟测试PASS**、真实 P5 日期定位已取得两只股票的13+2个异常Capital变动键后，下一阶段仅聚焦这些异常键对应的 **`m_anntime`（QMT记录的公告日期字段）是否存在及日期标签**，不能直接假定其代表被监管平台认可的真实公告。

通过同一个 `market_center_finance_capital_cache_compare.py` 新增的**单独显式开关** `--capital-announcement-evidence`，必须**同时**提供 `--report-key-date-details --explicit-readonly --explicit-qmt-cache-read` 与当前正式待审账本固定完整SHA。该模式原有 P3/P4 旧快照/账本SHA验证及两只第一阻断Capital样本抽取逻辑完全保留，最多两只每只一次 `xtdata.get_financial_data(..., ["Capital"], report_type="report_time")` **本地现有缓存读**。没有下载接口、没有东方财富三表查询，没有市场文件、日志或财务pending写入；北京时间19:50–20:25继续禁止运行。

父进程使用原先完整规范哈希比较确定差异日期：仅对 **旧版本独有、缓存独有、共同日期但非m_quarter字段不同** 的记录输出 `capital_announcement_evidence.entries`（沿用原最多32个差异日期预算，不截断；不显示其余正常Capital记录/116个m_quarter差异日期）。单项含 `capital_change_date`、`difference_reason`、`historical_m_anntime`、`cached_m_anntime`，其中两个公告字段状态只允许：

- `FIELD_ABSENT`：源行根本没有 `m_anntime` 字段；
- `EMPTY_OR_ZERO`：字段存在但为零、空或null；
- `UNPARSEABLE`：字段存在但不能严格解码为受支持日期标签；
- `PARSED_DATE`：有经严格解码的 `YYYY-MM-DD` **本地日期标签**（并不是实际公告的独立真实性证明）；
- `RECORD_NOT_IN_THIS_VERSION`：此股本变动键在相应旧/新版本内不存在。

返回值**不包含**旧值、新值、股本金额、原始日期字段/完整QMT行，不因 `m_anntime` 存在就推断公司披露真实性或证明哪个历史版本正确。所有日期状态、可选日期标签和字段名均需结构/范围校验，异常直接阻断；日期相同/不同也不自动解决股本冲突。输出 `official_announcements_checked=false`、`availability_is_not_disclosure_proof=true`、`can_certify_or_repair=false`、`market_file_writes=false`、`can_repair=false`、`source_authenticity_certified=false`；原 SHA 和冲突结论不变，pending保持冻结。

此阶段新增6个纯模拟专项测试（原26项→**预期32项**），包括状态解码、异常键范围/无原值输出、伪造子进程回执拒绝、仅两次本地缓存读取、用户/内部模式双显式授权与离线预检拒绝混用。**新提交的 Windows 测试和本机 `m_anntime` 状态尚未运行，不能据此声称已经取得公告日期**。正式QMT或交易所原始公告不属于这一步；待本地状态经用户验收后，再针对确有公告日期线索的两只异常样本查证监管/交易所原始公告而非再全市场财报核对。
