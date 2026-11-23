# 每日自动更新控制器：由复杂的人工对话转为一次性安全改造

实施日：2026-11-21。草稿基线：Finance P5（351项 Windows 测试通过），本阶段不部署。

## 为什么需要改
用户要求日常更新不再反复人工复制PowerShell、逐只检查财务历史版本。现有正式 `scheduled-afternoon-update.ps1` 于北京时间20:05由单一任务运行（四模块）、共享写mutex、6次QMT连接预检；财务导入器已有三次断连重试、缓存解码按股票隔离、pending、持久化游标、跨日续扫、独立不可变版本保护。问题是验证器把正常的 `pending>0`、`remaining_unvisited>0` 和 `adjustments.next_batch_required` 归为 PARTIAL，通知器文案“部分失败”，最终调度器将验证PARTIAL转换为异常退出。**业务仍需保持数据未认证的状态，不能靠修改验证器为PASS来假装完整**。

## 本次 Safety-first S1 (shadow)
新增 `market_daily_autopilot_shadow.py`：显式 --state-module/--explicit-readonly，仅读取 canonical `work/last-afternoon-unified.json` 和 `work/qmt_extra/financial-cache-progress.json`，限制文件2MiB、无符号链接、读取前后sha256一致；只输出聚合、SHA，不输出财务原始内容。输出分为：
1. **执行健康**：所有阶段exit0且runner无错误，正常计划内财务/除权PARTIAL归类 ROUTINE_CONTINUATION；非0、runner errors、质量FAIL、跨源FAIL（含当次全局校验）、财务日期错配或大量历史版本冲突(>=500)归类 ATTENTION_REQUIRED；非计划内的K线或板块PARTIAL、缺校验信息只为 REVIEW，不能绿灯认证。
2. **覆盖进度**：财务游标、跨日扫尾时间、当次处理数、待遍历数、pending按原因；覆盖完一轮不代表pending已解决。
3. **数据质量**：保持每个阶段 PASS/PARTIAL/UNVERIFIED/FAIL，以及整体独立跨源未认证标记，不得压成“所有数据通过”。
4. **告警建议**：ACTION 才发即时提醒、REVIEW供摘要、普通轮换NONE；本阶段只做 preview，不发送通知、未写健康状态、未配置重复消息去重、未更改正式每日任务。持久化去重与异常冷却必须在后续单独审查后集成，不能凭当日状态猜测“异常是旧的”。
5. **安全边界**：不调用QMT、不抓取新财务、没有任何文件写入、不修改20:05调度、财务pending或正式H5/Parquet。P1–P5保持Draft，无生产部署。新增15项纯合成单元测试，预计 `test_market_center*.py` 全量 **366项**，尚未Windows实机验收。

## 财务与估值：保留全部9类表
原始9类：Balance、Income、CashFlow、Capital、Top10FlowHolder、Top10Holder、HolderNum、PershareIndex、PerShare。来源接口中没有证明每日PE/PB与总市值直接构成这些表的永久字段，建议未来分别建立 `valuation_daily` 派生视图/表：
- total_market_cap = close_at_trade_day * effective_total_shares_at_day
- free_float_market_cap = close_at_trade_day * effective_float_shares_at_day
- pe_ttm = total_market_cap / trailing_twelve_month_parent_net_income，净利润<=0标为不可得而非负PE可比；EPS_TTM可以校验但不可盲目混用母公司与合并口径
- pb = total_market_cap / latest_known_parent_equity
- 分红、经营现金流、自由现金流等保留清晰口径及单位
- 每条关联“交易日/实际公告日m_anntime/报表截止日m_timetag/数据来源版本/股本生效日”，回测必须按当时实际披露数据 as-of 加载，严禁未来函数。成交价的前后复权和股本单位也不能混用。

## 财务更新发现优先与速度
先做 **两级候选计划**：
A. 最新公告或可靠增量变更事件 -> 候选股票（财报、业绩修订、股本/分红公告与更正公告需分别覆盖）；事件必须有来源、时间戳、股票身份、公告唯一ID及可追溯披露时间，来源不可用时不得自称“全市场无更新”。
B. 候选股票的单次、批量、日期窗口 download_financial_data2 + 缓存读取与旧快照保守比较 + 待审隔离。全市场轮转继续作兜底，不能仅靠候选漏掉退市证券或迟到修订。缓存 DAT mtime/size只能辅助粗筛、不能保证识别新财务公告。
C. 用真实QMT先基准测试同等 50/100/200只：读取公告发现开销、窗口下载耗时、9表读取与保存耗时、QMT通信次数和旧版遗漏；记录候选召回率。未实测不得宣称节省百分比，更不能贸然把FinanceDailyStockLimit调大到全部5000或添加第二写入计划任务。

## 后续集成（同一改造主线，非每次事故开新诊断PR）
S2：P1–P5工具合并审查后，加入幂等告警状态/错误指纹去重、失败冷却与按周摘要；重要的是无代码热更新/自动合并/自动修改财务。
S3：引入有证据的公告事件候选发现 + 受控单写锁计划 + 轮换兜底，先影子基准后小流量正式切换。
S4：一页今日状态+最近异常+估值覆盖质量，不要求手动运行测试。
所有阶段只有一套正式任务，Windows无Actions，用户可随时关闭新功能回退既有20:05调度。

## 已开发：真实东方财富公告候选 + QMT与东财三表交叉核验（2026-11-22）

**功能状态：真实接口实现已入Draft，但未在用户Windows联网实测、未接入20:05正式下载决策。**本次是从仅有规划向可手动真实采样前进，不得将其表述为“公告驱动自动更新已经上线”。在 `market_finance_secondary.py` 集中实现：

- **公告候选发现**：依赖可选安装的 `akshare`，用东方财富 `stock_notice_report` 获取财务报告、信息变更与持股变动公告。兼容目前AKShare按 `symbol=公告类别,date=YYYYMMDD` 查询的现代接口，以及旧 `report_type/recent_page` 接口；由真实Python函数签名选择，未知签名保守阻断。现代模式最多7天×3类别；原三页GUI的首次试运行限定最近3天、最多2页（旧接口）、最多9次按日公告请求。分类更正/修订候选、提取原始公告日和标题，使用SHA指纹去重；因为列表缺官方不可变公告ID、有限页和源可能漏项，`feed_complete_for_date_range=false`、`can_schedule_download=false`，没有结果也**不能**认为市场无新财报。数据源失效标记部分失败，绝不主动停止正常全市场轮转。
- **独立三表对照**：对最多3只既有 `SOURCE_HISTORY_CONFLICT` 待审股票，用老代码 `E._financial_snapshot_rows` 只读验证已保存 QMT 不可变Parquet快照及active pin。东方财富 `stock_balance_sheet_by_report_em` / `stock_profit_sheet_by_report_em` / `stock_cash_flow_sheet_by_report_em` 每股票各读一次，按最多4个共同报告期对照6对官方文档中口径相近字段：`Balance.tot_assets↔TOTAL_ASSETS`、`Balance.tot_liab↔TOTAL_LIABILITIES`、`Balance.total_equity↔TOTAL_EQUITY`、`Income.revenue↔TOTAL_OPERATE_INCOME`、`Income.net_profit_excl_min_int_inc↔PARENT_NETPROFIT`、`CashFlow.net_cash_flows_oper_act↔NETCASH_OPERATE`。小范围金额浮点容差另标NEAR，不冒充严格一致；缺列、重复版本、多对多、来源异常均标为未认证，不强制归并版本或覆盖正式财务。
- **已接入原GUI**：「异常与日志」新增「近期公告与东财三表对照（只读试验）」。只在人工点击后进行：读取主仓库真实财务账本确定股票与根目录，后台120秒隔离子进程，最多3只来源历史冲突股票，既不调用QMT下载、也不写Parquet/H5、pins、pending、20:05任务。使用原主仓库虚拟环境，需要事先具备 `akshare`；不自动安装新包。只输出有限摘要及真实报告期字段差异，不给出入库授权。旧三页功能不变。
- **本次验证范围**：新增专门13项合成测试，另在原桌面测试中增加4项，用于公告API新旧签名、候选身份、错误源不视作空、报告期日期编码、六字段数值、历史修订歧义、缺本地快照、来源API异常、GUI范围/超时/身份及无下载防误操作。原 `run-gui.ps1 -QuickCheck` 显式加入此测试文件，但正常GUI启动不跑测试。尚无用户实机联网结果，不能据此声称命中率、API稳定性或耗时降低。

**下一业务门槛**：先实际抽样确认公告候选覆盖（尤其更正公告、退市、京市）、源接口的实时可用性、对照金额单位/合并报表口径与报告版本，量化候选召回率和真实 QMT 下载时长；通过后才允许将候选优先级接入唯一20:05写锁任务。现有全市场轮转和QMT不可变历史保护始终保留兜底。巨潮/交易所原公告PDF可为重大争议提供最终证据，但本次还未实现原PDF自动采集或证据裁决。