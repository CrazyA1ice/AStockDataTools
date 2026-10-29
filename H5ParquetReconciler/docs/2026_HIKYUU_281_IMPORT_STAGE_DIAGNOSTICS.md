# Hikyuu 2.8.1 Python 3.11 导入45秒仍超时：定位具体子模块（2026-10-29）

## 用户本机已确认

- Windows项目`.venv`执行前一轮**15项隔离预检离线测试全部OK（2.055秒）**、**9项原生H5读取模拟测试全部OK（0.477秒）**。这24项只能证明工具及安全约束能运行，不等于真实Hikyuu成功导入。
- 在已有Hikyuu 2.8.1的`D:\\software\\Python311\\python.exe`以新`--timeout-seconds 45`重跑隔离预检，`hikyuu-native-runtime-preflight-python311-v2.json`依旧报告`hikyuu_import_timeout`、版本`null`、API`{}`、原生驱动未运行、两份合成H5 SHA重新验证成功，原始市场文件/正式配置未修改。
- 这表示在`before_import`标记之后，`after_import`之前超时。上一轮修复的`atexit`清理可能仍然重要，但**并不能解释这次在import阶段的超时**；增加超时到120秒或运行原生H5读取之前，应先确定具体在哪个子模块阻塞。

## 基于真实2.8.1上游源码的诊断设计

上游[Hikyuu 2.8.1 `hikyuu/__init__.py`](https://github.com/fasiondog/hikyuu/blob/2.8.1/hikyuu/__init__.py) 在顶层依次`from .util`、`from .extend`、`from .indicator`、`from .trade_manage`、`from .trade_sys`、`from .analysis`、`from .hub`、`from .draw`，并可能装载C++绑定`cpp.core311`和NumPy/Pandas/绘图库。真正的加载可能卡在其中任一环节。

本轮在**原有**`probe-hikyuu-native-driver-runtime-isolated.py`内部的`-I`短命子进程使用临时`builtins.__import__`包装，遵循以下原则：

1. 只对从Hikyuu模块发起的已知子模块导入报告`enter`/`leave`，固定标签如`package_extend`、`python_core`、`cpp_core311`、`numpy`、`pandas`、`package_draw`等；不改变底层真正的导入调用，不跳过导入、不更改用户安装包。
2. 父进程只将**白名单标记**整理为`import_stage_diagnostics`：`active_import_stage`表示当前最后一个未完成的导入类别，`last_import_stage`及`last_import_stage_event`记录最后有效标记，`import_stage_events_seen`为上限500的计数。没有可定位的标记将报告null。
3. 无论成功还是超时，**不**在SAFE文件中存储子进程完整stdout/stderr、异常内容、真实源码/用户路径、行情数据、网络账号；子进程运行前后仍复核两只虚构股票H5文件SHA、隔离HOME/APPDATA/TMP，仍不调用`hikyuu_init`、`StockManager.init`或原生H5读取。实际执行路径/市场源和生产query配置不变。
4. 原15项测试新增3项纯合成离线回归，合计**18项，待Windows验证**：追踪嵌套模块状态、被截断但合法的标签和剔除注入的非白名单内容。
5. 仍以45秒作为首轮时限；如果`active_import_stage`显示某一模块卡住，才针对其环境/依赖进入后续修复。不能凭“最后模块类别”就绝对断言问题由该包造成，它只是阻塞的定位线索。

## Windows操作

```powershell
cd D:\\ChatGPT\\AStockDataTools
git pull --ff-only origin main
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_probe_hikyuu_native_driver_runtime_isolated.py" -v
```

预期`Ran 18 tests`、`OK`（实测仍未知）。9项原生读取模拟测试此前全部OK，不需要反复运行。

测试通过后以**新的v3报告名**运行：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\probe-hikyuu-native-driver-runtime-isolated.py --canary-report "H5ParquetReconciler\\reports\\hikyuu-native-synthetic-day-canary-v1.json" --python-exe "D:\\software\\Python311\\python.exe" --timeout-seconds 45 --out "H5ParquetReconciler\\reports\\hikyuu-native-runtime-preflight-python311-v3.json" --isolated-preflight
```

若仍超时，上传`reports/hikyuu-native-runtime-preflight-python311-v3.json`，重点关注`import_stage_diagnostics`，不上传原始H5、SQLite、完整导入日志或机器配置。

如果显示`hikyuu_imported_without_initializing`，可以转入之前已开发的原生6条合成KData读取试点；在此之前**不**直接执行`read-hikyuu-281-synthetic-h5-native-isolated.py`。

## 上游参考

- [Hikyuu 2.8.1 顶层包导入源码](https://github.com/fasiondog/hikyuu/blob/2.8.1/hikyuu/__init__.py)
- [Hikyuu 2.8.1 Python核心选择器](https://github.com/fasiondog/hikyuu/blob/2.8.1/hikyuu/core.py)
