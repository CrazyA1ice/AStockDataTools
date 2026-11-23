# S9｜财务 pending 全量只读分类与九表元数据清点

## 上阶段实机证据（2026-11-22）
用户在 S8 固定提交 aca55b748973c2dab01e554792fc098b2858e2ad 的 Windows 环境完成674次测试执行（含重复），并读取正式账本：85只pending，其中84例SOURCE_HISTORY_CONFLICT，1例CACHE_DECODE_ERROR。三只抽样股票分别为000010.SZ/000036.SZ/000055.SZ；三者PerShare均没有本地快照，000010.SZ另有8表无active pin。两个已检查的事务journal目录均无记录。这只是S8抽样证据，不可推定85只全部有同样症状。

## S9实现及原则
新增market_scoped_finance_pending_full_census.py：复用现有P2账本分类、P3快照pin结构审核和S8正式目录身份验证。仅对正式账本内的全部pending股票（最多256只）执行九表本地文件名、日期、pin元数据的只读扫描；不读真实Parquet表行、不连接QMT、不写入状态、不修改20:05计划任务。
1. 对每只pending按reason、asof和attempts列明来源。SOURCE_HISTORY_CONFLICT只解析账本**首个记录的冲突表**和报错类型；不能假设九表来源差异已全面分析。唯一CACHE_DECODE_ERROR优先列出股票及现有账本详情，后续还需独立来源复核。
2. 对每只股票九表用紧凑状态码：M=无本地快照、来源未知；U=有快照但无pin；R=部分日期已pin；P=所有日期在元数据层面存在pin（**不是Parquet内容SHA验证**）；A=同一日期多个未pin版本导致候选歧义。旧P3会检查pin JSON的身份、文件名、日期及SHA字段格式。
3. 对所有pending汇总每张表的状态计数，额外汇总PerShare缺少本地快照的股票数，但明确per_share_qmt_source_empty_proven=false；本地文件缺失不能证明QMT源为空。
4. 两类现有事务journal分别统计，不自动恢复或删除；对所观察的快照文件名、大小、修改时间以及active pin小文件SHA，在扫描末尾再次校验，同时比对正式账本SHA。此行为不能替代持有写锁的原子一致性读取。
5. 拒绝符号链接/可疑文件名、未来日期、无效账本、其他根目录；窗口为中国时间19:50至20:25的20:05正式任务保护时段禁止扫描。限制pending最多256、每目录256文件、全局16000候选、快照压缩字节总元数据40GiB、pin最多16KiB。
6. 输出只读全量聚合，但默认仅显示3条逐股详情（先缓存解码错误，再未分类冲突，然后按股票代码）；可用--page与--page-size查看其他详情，避免一次返回数万字被Windows粘贴截断。扫描不写任何报告文件。

## 安全阻断与能力边界
无论统计结果如何，始终can_apply=false、can_commit=false、can_download=false、qmt_live_connection_checked=false、multisource_verified=false、all_snapshot_contents_sha256_verified=false、all_historical_versions_verified=false。全量仅指账本pending股票的九表**本地元数据**覆盖，不指全市场完整性，更不等于84例历史冲突已获修复授权。

## 测试与下一步
新增test_market_center_scoped_finance_pending_full_census.py 共26项合成测试；包括85只pending汇总、解码错误优先呈现、PerShare缺失区分、pin缺失/部分固定/歧义、伪造pin、未来快照、账本及pin并发改动、20:05保护窗口、root保护、分页及无apply。测试只操作系统临时目录，带.parquet后缀的假数据不是真正Parquet，故仅验证元数据清点逻辑。
S7固定SHA验收入口增加S9模块和测试；预计Python AST20文件，10组专项182次、33个market_center文件533次、原操作面板11次，共726次测试执行（含重复）。**仅是预估，尚未在用户Windows验证S9。**
下一次请先在全新的detached worktree用固定SHA执行统一验收，成功后在相同worktree只读执行S9：--root D:\stock --workspace D:\ChatGPT\AStockDataTools\ParquetLiveSync\work\qmt_extra --page-size 3 --explicit-readonly。失败时只报告阻断原因，不修复任何正式数据。
PR #241继续Draft，不合并main、不部署生产、不调用QMT下载、不改正式财务账本/pending/Parquet/H5、不使用GitHub Actions。
## S9 Windows验收结果与桌面软件内建（2026-11-22）

用户固定提交 d6d8302d0239f99261819a7ec55406e462e48ef2 在Windows实机完成OFFLINE_ACCEPTANCE_PASS：Python AST 20、PowerShell AST PASS、10组专项182项、33个市场中心回归文件533项、原操作面板11项，共726次测试执行（含专项重复）。正式账本仍为85只pending、账本SHA 9327b75fa7920294593dd11bb4221255c3f14410551705a98371c111f6b334fc，无已检查到的事务journal。

全量85只的首个记录冲突表：Capital 42、Top10Holder 33、Top10FlowHolder 5、HolderNum 4。唯一CACHE_DECODE_ERROR为688259.SH，原账本显示QMT provider UTF-8解码两次失败、已有4次尝试。85只PerShare无本地快照；000010.SZ八表有无pin历史版本，而000036.SZ最新多个日期版本的pin元数据已存在。该结果只是本地快照元数据，不是全部历史原始值核验、真实QMT接入或多源验证。

对长期要求用户复制长命令的做法作纠偏：不再把S8/S9诊断只留在独立脚本。三页桌面工具 market_simple_desktop.py 的“数据总览”在正常刷新时直接使用已有财务账本展示pending分类，且不触发QMT网络请求；“异常与日志”页增加“检查财务问题（只读）”按钮，以后台线程调用已验收的S9本地账本/九表目录清点，把全量汇总与优先关注的3只股票变为中文可复制诊断摘要。根目录直接来自受约束的正式财务账本，不要求用户再次输入 D:\stock；只读检查在19:50—20:25既有20:05保护时段拒绝执行。保持原三页结构、现有“刷新财务缓存并检查历史（不入库）”入口，不再添加新独立界面与新的数据库写入机制。

重要发现：qmt_extra_financial_cache_worker.py的DOWNLOAD_TABLES明确排除PerShare，但get_financial_data仍读取E.FIN_TABLES九张表。公开QMT接口文档存在八表与九表不同版本清单，所以85只PerShare全无本地快照可能属于接口表支持/采集机制差异，**不能用85只缺PerShare直接判断85只股票数据损坏**。后续应在用户实际xtquant版本核对支持表清单，再决定是否按可选表处理，不擅自修改当前正式历史或丢弃PerShare。

界面自助诊断只是服务化展示和运营减负，不应误报“自动修好84只历史冲突”。旧不可变Parquet、active pin、正式pending及20:05任务全部保留；对真正的来源修订要先完成精确日期/字段比对再定义允许的安全合并策略，不允许自动覆盖。PR保持Draft，桌面功能未合并/安装之前不能声称生产界面已具备此能力。
## 原三页软件的单股解码故障自助处理（2026-11-22）

新增原「异常与日志」页内的 **「定位解码异常股票（需确认刷新）」** 按钮，不添加第四页，也不构建新的外部脚本。按钮默认禁用；只有运行已有的S9内置只读检查、经只读回执校验发现**恰好一只**CACHE_DECODE_ERROR股票，才启用。当前实机只读证据该股票为688259.SH；但程序不会硬编码代码，而是每次从正式pending账本的已验证S9报告提取。若诊断失败、来源名单与数量不一致或多只股票同时出现解码错误，按钮保持禁用。

点击定位**不会调用任何QMT API，也不会创建Parquet快照或修改财务pending**。该动作在准备表单前再次只读核对最新pending账本，若错误已经消失或账本不可信则停止；成功时切换原「下载 / 更新」页，自动选「增量更新 / 自选股票 / 财务」，填入实际故障股票代码，并按当前盘后安全截止预填最近31个自然日的公告窗口。该窗口是便捷诊断范围，**不是历史财务全覆盖或曾经公告日期的证据**；用户必须检查并可修改日期，之后亲自点击已有「刷新财务缓存并检查历史（不入库）」且在弹窗里确认，才调用既有有界QMT缓存刷新。不会自动启动下载、反复重试或清空pending。

增量缓存刷新成功也不代表历史冲突已修复或正式财务Parquet已入库；本地状态需要等原有带审批的安全处理链确认才能变更。84例历史冲突继续保留，必须通过报表日期/字段级来源核验来制定保留旧版本的合并策略。正式20:05任务、QMT worker和财务importer本阶段**完全不修改**。

新增10项小型模型/GUI自测，核查名单必须等于账本解码原因数量、只允许单股、最近31日、定位动作只预填且不偷偷启动子进程、已解决或变化的待审记录不可被旧报告重试、界面有运行中任务时不能改目标以及异常时清理按钮状态。原UI测试19→此前30→本次40项；本提交的Windows测试尚未实机运行，因此禁止把之前的S9 726次测试PASS当作本次修改通过。
## 已内建QMT逐表只读定位：不再靠聊天推测PerShare缺失原因

针对正式账本单股688259.SH的CACHE_DECODE_ERROR，现有“异常与日志”页在确认待审为恰好一只后，增加 **「检查QMT九表（只读）」** 按钮。它不会默认自动执行，也不会对84只SOURCE_HISTORY_CONFLICT股票批量连接QMT。点击后再次核对正式pending账本原因，禁止在北京时间19:50—20:25的正式任务保护时段运行；使用正式仓库的Windows .venv Python与既有 qmt_extra_financial_cache_worker.py 中的 `--probe-readonly` 模式，45秒有界子进程，标准输入关闭、输出上限16KiB，任何失败只显示界面错误、不自动重试。

与正式财务缓存导入完全分离：既有 worker 的日常 `--mode daily/cache --output ...` 模式保持原样，仍是已使用的九表读取+8表下载策略；新的 `--probe-readonly` 模式不要求输出路径、不允许 --output、--mode、--start 或 --end，最多只对一只股票调用QMT `get_financial_data` **9次、每次只问一张表**，不调用download_financial_data/download_financial_data2、不写入本地文件或进度账本，输出一条带固定前缀的JSON诊断。如此可单独发现哪张表触发UnicodeDecodeError、连接不可用、源API异常、表未返回、缓存有记录或空/未缓存。**QMT无返回记录不能判定上游没有记录**；PerShare标记为可选表兼容性尚未认证。

官方迅投的部分XtData接口文档列出Balance/Income/CashFlow/Capital/Holdernum/Top10holder/Top10flowholder/Pershareindex共8表；另有XtQuant API版本默认清单列有PerShare为第9表。现有用户环境是否支持PerShare仍未通过实机逐表探针确认。因此不修改现有财务源 schema、不会从九表验收直接降为八表、不强制改写历史快照、不清空85只pending。

新增6项已有qmt_extra数据单测与7项原三页桌面模型/GUI单测，覆盖九次单表无下载、PerShare与八表解码隔离、空缓存不等于供应商为空、保护窗口、CLI拒绝写参数、回执身份校验与桌面调用有界性。**所有本阶段新增测试仅完成静态变更核验；未在用户Windows真实QMT与桌面GUI执行，之前S9的726次测试通过不可替代此轮实测。**

下一步在实际QMT客户端点击此按钮，根据九表结果决定有针对性的兼容修复：如果仅PerShare报错，可将可选表读取独立兼容而不拖累其余八表；如果八个核心表某个报错，针对该表处理；若九个单表均正常而整批失败，则定位QMT批量组合调用。任一情况均不能在尚未确认源数据真实性前自动合并84例历史差异。本PR继续Draft，不自动部署或修改20:05更新任务。
## QMT只读逐表检查的实用性修正（2026-11-22）

用户强调后续异常应当由现有软件自己定位而不是反复要求PowerShell。根据已有九表只读入口的代码复查，本轮没有增设任何新独立诊断工具或生产自动修改逻辑，重点解决真实Windows用户会遇到的运行和解释问题：

- 增加 **合法单股 `--probe-readonly --symbols 688259.SH` CLI的端到端合成测试**，mock掉 xtquant SDK、固定中国时钟，核实正式参数确实通过校验，且最多调用九次单表 `get_financial_data`、不调用任何QMT下载接口、不写本地文件。此类正向测试能防止此前曾发现的代码正则转义错误再次出现。
- 实际只读回执将安全获取**本地安装的xtquant包版本号**（找不到或不合法时标明UNKNOWN），并由界面展示。此版本号只是兼容诊断线索，**不是接口支持能力认证**，不得据此默认为PerShare可用。
- 依照九表逐表返回结果在中文界面内给出分流：核心八表自身存在异常时优先列出实际表名；核心八表均能读而仅PerShare异常时建议先排查可选表兼容性；全部核心缓存空时明确提醒不能证明供应商源数据为空；全部单表能读而批量九表失败时提示检查组合接口。上述都属于**排查建议，不是根因已确认或允许自动修复**。
- 严格拒绝QMT回执伪称来源历史一致、PerShare接口兼容已认证或允许写入；存在已运行的QMT探针时暂停新的本地账本清点，重新清点前清除旧探针文本，防止误把旧数据当最新结果。
- 本轮只改变现有worker的只读输出、原三页GUI展示和这些文件原本已有的测试；生产财务importer、财务数据Parquet、旧active pin、pending、20:05计划任务保持不动。新提交**尚无用户Windows执行结果**，不得冒充上一轮726次旧SHA验收已覆盖本轮。