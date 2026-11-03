# Windows分钟数据真实转换图形界面（2026-11-03）

> **不是模拟数据，也不需要反复复制命令。** 界面调用现有、已在本地Windows真实写盘成功的 `run-real-minute-h5-gap-unified-range.py`，逐交易日进行**购买Parquet优先→H5完整股票日补缺→私有1min/5min统一Parquet→全字段/源SHA回读**。原始 `D:\stock\AllCycleAStockData` 和 `D:\stock\HikyuuData` 始终只读。本界面**尚不写历史全量原生H5**，也不自动激活生产查询指针；原生H5全历史聚合/C++全量读取/量额单位和舍入认证属于后续独立阶段。

## 一次安装，之后双击使用

项目目录：`D:\ChatGPT\AStockDataTools`。首次只更新代码并运行**3项离线、无市场写入的GUI后台安全测试**：

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; & ".\.venv\Scripts\python.exe" -m py_compile H5ParquetReconciler\tools\minute-private-parquet-worker.py H5ParquetReconciler\tools\minute-private-parquet-gui.py H5ParquetReconciler\tests\test_minute_private_parquet_gui_worker.py; if ($LASTEXITCODE -ne 0) { throw "GUI脚本语法检查失败" }; & ".\.venv\Scripts\python.exe" -m unittest discover -s H5ParquetReconciler\tests -p "test_minute_private_parquet_gui_worker.py" -v; if ($LASTEXITCODE -ne 0) { throw "GUI后台隔离与恢复安全测试失败，不要启动大规模写盘" }; Write-Host "PASS：GUI后台3项安全测试通过，可以双击 H5ParquetReconciler\start-minute-converter.bat"
```

以后**直接双击** `H5ParquetReconciler\start-minute-converter.bat`，不需要再开PowerShell。启动时使用项目现有 `.venv\Scripts\pythonw.exe`，仅调用标准库Tkinter；不需要浏览器、不需要服务器和额外收费软件。

## 界面操作

1. 原数据根目录默认 `D:\stock`，不能指向空目录。日期默认2026-07-01至2026-10-13，可改成更长（如2025-01-01至2026-10-13）；**只检查工作日**，休市/无源数据会显示“无行情源”，不能据此宣称行情已齐。
2. 点击**开始新任务**：由独立后台Python进程逐日期运行**真实转换**。每完成一日自动保存独立stage/unified Parquet、当日验收报告和SHA，再继续下一日。界面按日期展示完成/复用/无数据、1min/5min实际行数、进度条和真实写入日志。
3. **关闭界面不停止写盘**：任务不依赖原PowerShell或界面窗口，可重新双击启动器，界面会尝试自动打开最近的任务。任务运行日志、每个日期状态和后台PID都留在项目目录。
4. **当前日期结束后暂停**：只在当天Parquet完整写盘后生效，不粗暴杀正在写入的进程；恢复时输入/保留12位任务ID，点“恢复已有任务”。同一时间全局写入锁只允许一个GUI任务真正写盘，避免两任务并行重复占盘。
5. **意外停电/关机/强制结束Python**：已完成日和SHA保留；界面可用同一个任务ID恢复。对于半写盘、缺SAFE的当天，后台**保留旧残缺文件且选用新的隔离attempt ID**重试，绝不删除/覆盖旧文件。若检测到已有完整SAFE但源SHA发生变化、同一日期的多份历史结果互相冲突，则 **fail closed** 需要先审计，不能静默覆盖商业数据或跳过异常。
6. 自动识别以前在PowerShell已完成的`minute-batch-stage-YYYYMMDD-*.json`+`minute-batch-unified-YYYYMMDD-*.json`：每日期先用现有 `verified_completed`进行stage来源和真实Parquet SHA回验，**复用旧的8月/9月/10月已验日，不重做**。对10月13日只认可2026-11-02已完成的 **1min END时间键**修正版本`real-unified-minute-parquet-20261013-end-key-11127c8d60ba.json`，不会误用旧-1min版。零记录候选日期**不认为已完成覆盖**，未来源更新后可以新建任务重新扫描。
7. 进度按日期、周期和日志显示，**不是逐证券毫秒级进度**。大日期区间会逐日处理，可能运行较久。业务消费指针和原市场文件绝不更改；输出均在仓库`H5ParquetReconciler\work`及`reports`。

## 文件与权限

- GUI：`tools/minute-private-parquet-gui.py`
- 后台任务：`tools/minute-private-parquet-worker.py`（独立进程；全局非阻塞文件锁）
- 启动器：`start-minute-converter.bat`
- 每个任务：`work/minute_gui/jobs/<12hex>/config.json`、`state.json`、`activity.log`、`worker-stdout.log`
- 当日SAFE：`reports/minute-gui-day-YYYYMMDD-<12hex>.json`；旧有批次的stage/unified SAFE仍放在原来的位置，哈希完整校验
- 私有Parquet：`work/unified_parquet/minute_gap_staging/`和`work/unified_parquet/minute_complete_day/`，原市场目录只读
- 暂停信号：`work/minute_gui/jobs/<ID>/stop_after_day.flag`；UI恢复时清除此信号

**重要边界**：这套界面是完整历史统一Parquet真实转换调度器，不是把Parquet真正转换到全量Hikyuu H5的可视化进度。不能把此前**四日期原生H5 6,427,013条**与新产生的**数千万条Parquet**混为一谈。后续H5全历史聚合必须单独实现全量源SHA登记、40字节原生表顺序写入、时间/量额量纲有界舍入校验、C++读取门禁以及受控发布。
