# Market Center V2E · 七页界面整合版（2026-11-20）

## 设计来源与分支关系

用户明确选择将新分支 feat/market-center-v2e-seven-page-selected-ui-20261120 的界面设计作为新版主界面。该视觉分支从V2-D1早期提交0bc42b1d9fc5629823ac2217de144dc64f906584分出，没有后来引入的QMT即时连接、正式代码指纹和财务历史版本清单，因此不可直接覆盖新的代码。

本整合分支以当时V2-D2C开发提交c1d6a72620f8bb2dbeb285402b62b9a160cd0eba为基线，只移植V2E的实际可运行Tkinter七页界面，保留后续各阶段安全后端，不改变官方20:05唯一自动更新任务及任何生产数据。

## 七页布局（用户选定 A-B-B-B-B-A-A）

| 页 | V2E界面结构 | 已保留或集成的功能 |
|---|---|---|
| 运行总览 A | 深蓝侧边栏 + 四张精简状态卡 + 四阶段2×2卡片 | 可信数据变化、财务待审数、本轮故障提示、可点击的QMT连接检查和正式代码/备份范围盘点 |
| 更新/核验 B | 三步向导：方式与日期、股票与模块、预检与只读核验 | 原共享日期范围、历史三策略的只读预览、20股票/31天冻结范围、有界Parquet只读审核 |
| 核验结果 B | 左侧可排序逐股记录、右侧原始证据面板 | V2B2资格门禁、V2C分钟时间标签比较、无认证不允许自动补写 |
| 故障诊断 B | 左侧同次错误、右侧恢复门禁与证据 | V2D1真实QMT财务断连识别、除权正常轮换、V2D2A用户主动实时QMT探测、V2D2B代码哈希/当日财务范围、V2D2C历史财务版本范围盘点；底部动作分两行、无横向溢出；一键重试始终禁用 |
| 运行日志 B | 深色双向滚动日志、关键词本地高亮 | 同次财务日志查看、限定私有日志目录、无任意路径读取 |
| 数据管理 A | 八周期两行×四列卡片及数据源说明 | 无逐周期物理核验时仍标未认证，禁止显示伪造完整率 |
| 高级设置 A | 分组的调度/数据源/权限卡片 | 只读显示当前来源与20:05约束，增加QMT即时探测和财务版本只读盘点权限解释 |

V2E UI继承最新版MarketCenterV2，而不是重新实现QMT探测、金融批次恢复或读写权限，避免绕过底层证据门禁。点击检查QMT才执行一次get_client；正常启动和状态刷新不调用QMT。历史财务清单是只读历史所有日期元信息，**不复制历史文件、不读取Parquet载荷、不创建备份、不验证回滚或开放写入**。正式版本SHA仍须独立审批。

## 重要边界

- 这不是“可以下载和更新的新版生产程序”。真实下载、历史修复、财务单批次续跑仍未开放；显示“当前连接成功”也不能授权继续写入。
- 最新已提交日期不证明逐股票/周期完整；239分钟时间标签差异仍只是供应商时间格假设。
- 11月20日真实财务故障曾在000755.SZ后遭遇五股QMT连接中断；跨日不能盲目重放昨日daily或清空游标，原程序已有unfinished sweep跨日延续逻辑。
- 备份范围统计为0字节并不表示旧的历史财务版本不需备份；V2D2C的历史盘点是**针对原失败批次的限定元信息清单**，不覆盖所有历史股票/账本和恢复事务。
- 新布局是单独入口 market_center_v2e_selected_ui.py，原 market_center_v2_preview.py 不被覆盖，可安全回退。CLI/后端安全策略与唯一20:05任务均不改。
- 暂不合并main；任何部署/启用正式财务补写应有独立审批和原子独占写锁。

## Windows 用户验收

在 D:\ChatGPT\AStockDataTools 中先fetch指定分支并建立新detached工作树，避免污染正式main与已验收的历史工作树。使用canonical项目 .venv (也可用新启动脚本中自动回退至仓库根的.venv)。

逐个执行以下11组测试，各组失败立即中止：
- test_market_center_v2_preview.py
- test_market_center_v2_readonly_audit.py
- test_market_center_v2_evidence_gate.py
- test_market_center_v2_minute_grid.py
- test_market_center_v2_finance_connect_retry.py
- test_market_center_v2_faults.py
- test_market_center_v2_qmt_live.py
- test_market_center_v2_recovery_inventory.py
- test_market_center_v2_finance_history_scope.py
- test_market_center_v2e_selected_ui.py
- test_market_center_v2e_integration.py

本次仓库文本中共列出229个test_方法，**未在本会话实际Windows运行，需用户回传输出后才能称229/229通过**。真实GUI窗口截图验收七页：侧栏切换、首页图表、三步范围保留、只读核验与双分栏、故障详情及按钮不溢出、QMT即时按钮主动点击才检查、最新代码和全部历史财务版本预览、日志搜索、数据管理不虚构数据完整率、高级设置全只读。

建议先只带 --state-module 看设计，不传 --market-root，避免触碰生产市场文件。视觉通过后再传 --market-root 验收受控只读核验与历史财务清单，不运行任何更新命令。
