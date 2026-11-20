# Market Center V2E · 用户选定七页布局的可运行界面（2026-11-20）

> 根据用户从14个原型中采纳的组合：**运行总览 A、更新/核验 B、核验结果 B、故障诊断 B、运行日志 B、数据管理 A、高级设置 A**。本阶段交付实际 Tkinter 界面，不是只展示 PNG。固定基线为用户 Windows 已创建工作树的 V2D1 提交 `0bc42b1d9fc5629823ac2217de144dc64f906584`，不自动追随旧特性分支之后的新提交。

## 设计与实现对应

| 页面 | 采用样式 | 本轮实际可操作内容 | 必须诚实显示的限制 |
|---|---|---|---|
| 运行总览 | A 精简卡片 | 最近实际提交日、上次任务结果、20:05候选安全截止、QMT上次预检、四阶段摘要、可信变化与异常快捷入口 | **任务执行、数据核验、跨源验证分别展示**；QMT最近预检非实时连接；无快照不能编造增量 |
| 更新 / 核验 | B 三步操作 | ①任务模式/共享日期/历史策略 → ②股票及模块/数据源信息 → ③计划预览、复制及小范围只读行情核验 | 所有写入关闭；只读物理核验必须显式 `--market-root`，最多20只/31日且沿用V2D1冻结时点 |
| 核验结果 | B 左右分栏 | 左侧实际扫描记录表、排序与摘要；右侧原始证据及选中行详情，可收起 | “无记录”不等于认证缺失；分钟标签比较不等于认证QMT时间格 |
| 故障诊断 | B 诊断分栏 | 左侧同轮故障及正常待续批次，右侧证据/安全检查点；复制受控预览、跳原始同次日志 | 断线类别依同次日志分类，除权轮换待续不是故障；一键重试仍禁用 |
| 运行日志 | B 专业日志视图 | 深色只读日志区、垂直/水平滚动、页内关键词高亮、进入同次财务阶段日志 | 仅读取现有有限日志尾段；不得通过界面拼接任意外部路径 |
| 数据管理 | A 八周期卡片 | 分钟1/5/15/30/60、日/周/月八个可辨周期；真实状态摘要、进入定向只读核验 | **不宣称逐周期完整覆盖、缺口数量或百分比**；未进行逐股日核验时一律“未逐周期核验” |
| 高级设置 | A 分类设置卡片 | 当前项目读取的来源配置、旧调度与互斥的设计约束、四类功能门禁 | 只看配置，不修改源/任务计划/并发锁，也不伪称当前QMT在线 |

## 代码架构

- **新增、而非覆写：** `market_center_v2e_selected_ui.py` 继承已验收的 `MarketCenterV2`，保留 `latest_status`、`source_info`、`diagnose_latest`、原有 `run_readonly_audit`、现有 `plan_preview` 和统一状态/日志读取。
- 新增深蓝侧边七页导航，统一浅蓝背景、白色卡片、成功/失败/未知独立色；新首页压缩信息密度，新增两处专业左右分栏。
- `market_center_v2e_selected_ui.py` 的 `view_coverage_rows` 和 `separated_run_evidence` 为**纯内存展示层**：缺失真实证据时输出明确未知，绝不填虚构数值。实际更新、重新下载、历史修复、财务续跑的执行权限仍为 false。
- 启动脚本为 `start-market-center-v2e-seven-pages.cmd`，不替换旧 `start-market-center-v2-preview.cmd`、原正式GUI、旧Windows计划任务、生产更新器或QMT/行情/财务账本。
- `tests/test_market_center_v2e_selected_ui.py` 包含**34项**纯合成状态合同及Tkinter本地空状态目录界面检查；测试不会从正式行情目录读取或写入生产行情。

## Windows 验收路径

### 1. 新建独立固定 SHA 工作树

在 `D:\ChatGPT\AStockDataTools` 仓库中从本V2E独立分支拉取指定固定提交，并通过 `git worktree add --detach` 建立 `work\market-center-v2e-selected-ui-20261120`；保留 `work\market-center-v2d1-20261120` 和原 canonical 不变。

### 2. 首先执行新布局合成测试

```powershell
$w="D:\ChatGPT\AStockDataTools\work\market-center-v2e-selected-ui-20261120";$py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe";$env:PYTHONPATH=Join-Path $w "ParquetLiveSync";& $py -u -B -m unittest discover -s (Join-Path $w "ParquetLiveSync\tests") -p "test_market_center_v2e_selected_ui.py" -v
```

需实际看到 `Ran 34 tests`、`OK` 才能称V2E本阶段验收PASS。此前V2D1自己的测试与现场诊断仍是独立验收事项，V2E不会冒称它们本轮已运行。

### 3. 仅打开真实状态只读界面

```powershell
$w="D:\ChatGPT\AStockDataTools\work\market-center-v2e-selected-ui-20261120";$py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe";& $py -u -B (Join-Path $w "ParquetLiveSync\market_center_v2e_selected_ui.py") --state-module "D:\ChatGPT\AStockDataTools\ParquetLiveSync"
```

该启动方式**不传 `--market-root`**，因此真实市场文件核验按钮保持禁用，只读查看本地有限状态JSON和最近日志。想单独验收限制内的历史行情物理核验，必须显式提供经允许的行情根目录并在UI里再次确认，本轮视觉验收不需要。

## 人工视觉确认点

1. 左侧有七页，首页为紧凑 A 风格；切换标签后标题与活动导航同步，窗口缩小时仍有滚动条。
2. 更新/核验三步骤中选择时间、股票及模块，切换模式不重置任何输入；首页按钮正确跳到工作流。
3. 核验结果两栏，右侧证据可隐藏、重现；未知记录不得显示假数字或“已确认缺失”。
4. 故障左表右详情，财务QMT断线与除权正常轮换可区分，**自动重试永不使能**。
5. 日志搜索只在本页内高亮，日志双向滚动；数据管理八周期均不编造覆盖百分比。
6. 设置只读、来源自动选择；不会修改调度策略、行情文件、QMT数据库或原GUI。
7. 未合并main；全部生产写入、重复下载、冲突覆盖及财务续跑依然需要另行安全设计和独立授权。

## 尚未实现

这是**现有V2D1数据源支持范围内的视觉与交互重构预览**，不是完成定向行情生产更新或自动恢复；数据管理的完整历史覆盖聚合、可信前后快照、真实QMT当前在线判断、修复交易、审计回滚及设置写入权限仍未实现。用户看完实机效果再决定视觉细节，不能把UI文案当作后端已获得能力认证。

**状态：V2E_SELECTED_LAYOUT_CODE_SUBMITTED / 34_SYNTHETIC_TESTS_WINDOWS_PENDING / REAL_GUI_VISUAL_REVIEW_PENDING / V2D1_PINNED_BASE / ZERO_PRODUCTION_WRITES / NO_MAIN_MERGE。**
