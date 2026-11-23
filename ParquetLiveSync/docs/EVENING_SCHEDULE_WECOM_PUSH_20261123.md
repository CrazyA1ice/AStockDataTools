# 2026-11-23｜保留20:05既有行情顺序，财务最后执行，企业微信替代系统弹窗

## 用户确认的运营偏好

- **只有一条正式20:05（中国时间）Windows任务** `AStockDataTools-ParquetLiveSync`，不设置独立00:30财务任务、零点后补跑或新的GitHub Actions。
- **顺序不变**：八周期K线→板块→除权批次→**QMT财务（最后）**。阶段逐项记录退出码/日志；某阶段失败仍尽力处理其他互不依赖阶段，结束后通知准确的SUCCESS/PARTIAL/FAILED。
- 财务直接采用已实机验证的`-QMTPrimaryVersioned`，源历史修订保存不可变新快照，旧版留存；其它七张可用财务表不因已知`688259.SH` Top10Holder单表异常而被删除。该异常pending留存，仍可能在常规全九表扫描中产生一个解码错误，后续需优化静默隔离。
- 财务正常最多40分钟，且动态计算到**北京时间23:20前**的有界余量，另留5分钟作为单个QMT worker超时及收尾缓冲；若行情阶段结束太晚、余量不足10分钟，当晚财务不启动，明确记为**DEFERRED_CUTOFF**，保存原财务游标，下一晚继续，不隐式下载到午夜后。
- Windows任务安装模板的Trigger仍是唯一20:05，不再带`StartWhenAvailable`，避免错过晚间后凌晨重跑；硬兜底执行时间上限3小时40分（正常20:05→23:45北京时间）。**硬兜底有强制终止风险，不应视作数据写入原子性的替代品**，故前置阶段预算/数据快照原有原子写入规则仍需遵守。若当天出现极端长时间的早期行情阶段，不能绝对保证每个阶段都完成。
- `install-schedule.ps1 -Action Install` 若查到旧名称`AStockDataTools-QMT-Financial-Daily`独立定时任务，**只禁用、保留注册**，不创建第二任务；要求禁用成功才安装唯一20:05任务。此前实际本机是否存在该旧任务尚未检查。状态命令会报告独立任务状态。

## 不再使用Windows系统弹窗

旧`notify-market-update.ps1`的Windows Toast最多使用620字符摘要，失败时改用20秒WScript.Popup，无法保证全文或离线接收。新版本**完全移除Toast/Popup逻辑**，采用标准HTTPS企业微信推送作为一次性可选通道。消息正文从**同一轮运行的完整`last-afternoon-unified.json` / `last-precutoff-market-only.json` 回执**组装，严格核对`started_local`避免误发旧报告；包含每个阶段执行情况、校验与跨源状态、已知错误、财务夜间顺延说明，不再使用旧620字符通知短文本。若超过安全的微信消息字节上限，按UTF-8完整字符**分段编号**，避免中文截断；所有内容的完整原始日志和结构化回执仍在本机。

支持两种官方目的地：
- `wecom_app`：企业微信自建**个人应用消息**，适合单人接收（需要一次性输入CorpID、Secret、AgentID、UserID，存在本机，不发给ChatGPT）。该方式不要求另建企微群。
- `wecom_webhook`：已有企业微信群机器人Webhook，仅允许官方`https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...`，不会调用任意第三方域名。

**凭据永远不进GitHub**：一次性工具`setup-market-notification.ps1 -Provider App` 或 `-Provider Webhook` 在本机隐藏输入Secret/Webhook，验证配置结构并设置只对当前Windows用户可读的ACL；目标是主仓库被gitignore排除的`ParquetLiveSync/work/qmt_extra/market-notification.private.json`。该工具本身不发消息或改变计划任务。远端腾讯云TecentSystem新闻机器人、QQ/微信现有发送器、群关系、订阅及令牌全不修改。

发送时：先落地本机`work/qmt_extra/market-notification-outbox/<run-id>.json`，按序发送每个编号分段并标记API_ACK；同轮已确认不重发。超时/服务端响应不明时标记UNKNOWN，不会**盲目重发可能已经送达的部分**，避免刷屏；错误打印只输出定型状态，不泄露App Secret/Token/群Webhook。注意：**API_ACK只是企业微信接口接受，不等于手机端实际展示**；首次必须用真实个人应用/群消息做设备收件验收。如果私有配置未创建则只留下本地outbox回执并报告`NOT_CONFIGURED`，**不宣称消息已推送**。若外部推送失败，行情数据结果不会反向伪装成功/失败；本机运行报告仍可查看。每次非DryRun还会将**完整的人类可读通知文本**落到同一私有outbox中的`<run-id>.txt`，无凭据时也可查阅，不会丢失消息内容。

## 开发部署与可回滚性

本阶段只在现有 Draft PR #241上提交源码和离线测试；没有调用用户Windows任务计划程序，不禁用当前旧任务，也没有推送真实消息。需在Windows测试Python`test_market_update_push.py`、`test_market_daily_verification.py`和PowerShell`test_notify_market_mock.ps1`、`test_install_afternoon_schedule_mock.ps1`、`test_schedule_evening_push_mock.ps1`后，经过专门的正式仓库源文件更新/备份/计划任务安装操作，才能称为上线。

正式启用后只需每日晚上正常开机并保持QMT可连接：20:05单任务执行，K线→板块→除权→财务；完成后企业微信分段消息。若关机/断电或Windows不在线，当晚无法生成和推送任务结果；不能声称能够离线执行。回滚方式为恢复备份脚本和原定时任务设置、撤回或移走私有推送配置，不触碰已入库财务Parquet。
