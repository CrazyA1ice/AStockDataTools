# 每日自动更新控制器：由复杂的人工对话转为一次性安全改造

实施日：2026-11-21。草稿基线：Finance P5（351项 Windows 测试通过），本阶段不部署。

## 为什么需要改
用户要求日常更新不再反复人工复制PowerShell、逐只检查财务历史版本。现有正式 `scheduled-afternoon-update.ps1` 于北京时间20:05由单一任务运行（四模块）、共享写mutex、6次QMT连接预检；财务导入器已有三次断连重试、缓存解码按股票隔离、pending、持久化游标、跨日续扫、独立不可变版本保护。问题是验证器把正常的 `pending>0`、`remaining_unvisited>0` 和 `adjustments.next_batch_required` 归为 PARTIAL，通知器文案“部分失败”，最终调度器将验证PARTIAL转换为异常退出。**业务仍需保持数据未认证的状态，不能靠修改验证器为PASS来假装完整**。

## 本次 Safety-first S1 (shadow)
新增 `market_daily_autopilot_shadow.py`：显式 --state-module/--explicit-readonly，仅读取 canonical `work/last-afternoon-unified.json` 和 `work/qmt_extra/financial-cache-progress.json`，限制文件2MiB、无符号链接、读取前后sha256一致；只输出聚合、SHA，不输出财务原始内容。输出分为：
1. **执行健康**：所有阶段exit0且runner无错误，正常计划内财务/除权PARTIAL归类 ROUTINE_CONTINUATION；非0、runner errors、质量FAIL、跨源FAIL、财务日期错配或大量历史版本冲突(>=500)归类 ATTENTION_REQUIRED；缺校验信息只为 REVIEW，不能绿灯认证。
2. **覆盖进度**：财务游标、跨日扫尾时间、当次处理数、待遍历数、pending按原因；覆盖完一轮不代表pending已解决。
3. **数据质量**：保持每个阶段 PASS/PARTIAL/UNVERIFIED/FAIL，以及整体独立跨源未认证标记，不得压成“所有数据通过”。
4. **告警建议**：ACTION 才发即时提醒、REVIEW供摘要、普通轮换NONE；本阶段只做 preview，不发送通知、未写健康状态、未配置重复消息去重、未更改正式每日任务。持久化去重与异常冷却必须在后续单独审查后集成，不能凭当日状态猜测“异常是旧的”。
5. **安全边界**：不调用QMT、不抓取新财务、没有任何文件写入、不修改20:05调度、财务pending或正式H5/Parquet。P1–P5保持Draft，无生产部署。新增12项纯合成单元测试，预计 `test_market_center*.py` 全量 **363项**，尚未Windows实机验收。

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
