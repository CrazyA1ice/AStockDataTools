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