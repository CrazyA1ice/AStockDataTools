# 2026-10-29 Hikyuu 2.8.1 Python311隔离导入超时：区分导入与退出清理

## 实测现象和根因假设

用户在`D:\ChatGPT\AStockDataTools`用明确安装Hikyuu 2.8.1的`D:\software\Python311\python.exe`执行`probe-hikyuu-native-driver-runtime-isolated.py`，输出：

```
SAFE Hikyuu runtime probe: H5ParquetReconciler\reports\hikyuu-native-runtime-preflight-python311-v1.json
Runtime status: hikyuu_import_timeout
Native HDF5 driver executed: NO
```

前一版仅按`subprocess.run(timeout=20)`覆盖整个进程寿命：即使`import hikyuu`已成功，在`atexit`清理阶段挂住同样会被标为导入超时。核对上游Hikyuu**2.8.1**标签的`hikyuu/__init__.py`可见其导入时注册`hku_cleanup`（`atexit.register(hku_cleanup)`），调用`StockManager.instance().cancel_load()`并在`not data_ready`时持续等待。仅为检查Python绑定接口的预检**刻意不初始化**StockManager，所以这条退出路径有潜在的无限等待问题。**上次20秒超时尚不能证明到底卡在import还是atexit**，因此仍必须拿新的分阶段SAFE结果确认。

## 修复

- 原`tools/probe-hikyuu-native-driver-runtime-isolated.py`仍使用`-I`子进程及私有HOME/APPDATA/TMP，无用户默认Hikyuu配置；内部在导入前后和结构化结果输出前使用固定、无路径/行情信息的`ASTOCKTOOLS_SAFE_HIKYUU_PHASE:`标记，`flush=True`。
- 完成`import hikyuu`和小范围API存在性检查后，先写完整SAFE结果并刷新stdout，然后由**短命预检子进程**使用`os._exit(0)`，仅跳过其有风险的`atexit`/解释器析构；父进程仍通过`subprocess.run`拿到完整结果，重新复核两份合成H5的SHA256，输出SAFE JSON。
- 如果仍超时，仅从stdout解析固定标记（任意日志/错误内容不保存），状态分别标为`hikyuu_subprocess_startup_timeout`、`hikyuu_import_timeout`（进入import）、`hikyuu_post_import_probe_timeout`（import结束后）、`hikyuu_subprocess_exit_timeout`（结构化结果输出后进程尚未退出）。没有阶段标记就标为启动超时，不能推断确切原因。
- 默认超时调整为**45秒**，支持`--timeout-seconds 10..120`，非法参数在执行子进程之前拒绝；保持`native_h5_driver_read_executed=false`和`hikyuu_h5_compatibility_certified=false`。
- 原生合成H5读取脚本`read-hikyuu-281-synthetic-h5-native-isolated.py`的短命子进程也在打印并刷新最终SAFE结果后执行`os._exit(0)`，避免已完成六条模拟KRecord的读取却在Hikyuu退出清理时被误判超时；绝不跳过中途失败，SIGSEGV/超时仍然失败。
- 现有12项预检测试新增3项：阶段标记区分、假Hikyuu模拟阻塞atexit仍能完成、拒绝不合法超时，合计**15项待用户Windows本机验收**。原生读取**9项测试**也要重新跑一次确认静态合约。
- 不安装升级Hikyuu，不重建H5，不触碰原始`D:\stock\HikyuuData`、付费Parquet、真实`stock.db`、私有stage和生产路由。

## Windows命令

在仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_probe_hikyuu_native_driver_runtime_isolated.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_read_hikyuu_281_synthetic_h5_native_isolated.py" -v
```

预期为`Ran 15 tests ... OK`及`Ran 9 tests ... OK`，**这只是合成/模拟回归通过，不是原生数据驱动已经通过**。

然后**用新的v2报告名**重新执行Python311隔离预检；上次v1文件不能覆盖：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\probe-hikyuu-native-driver-runtime-isolated.py --canary-report "H5ParquetReconciler\reports\hikyuu-native-synthetic-day-canary-v1.json" --python-exe "D:\software\Python311\python.exe" --timeout-seconds 45 --out "H5ParquetReconciler\reports\hikyuu-native-runtime-preflight-python311-v2.json" --isolated-preflight
```

只有`hikyuu_runtime_status == "hikyuu_imported_without_initializing"`并且`hikyuu_api_presence`显示相应接口存在后，**才考虑**执行原生读取试点：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\read-hikyuu-281-synthetic-h5-native-isolated.py --canary-report "H5ParquetReconciler\reports\hikyuu-native-synthetic-day-canary-v1.json" --python-exe "D:\software\Python311\python.exe" --run-id run001 --out "H5ParquetReconciler\reports\hikyuu-native-read-281-canary-v1.json" --synthetic-native-read
```

`--run-id`和输出SAFE报告名都必须全新。若已有`run001`，改为`run002`并使用新`v2`报告。异常SAFE状态不要自行改用真实Hikyuu数据库绕过；回传SAFE文件供进一步核对。

## 上游依据
- [2.8.1 Hikyuu包初始化与atexit](https://github.com/fasiondog/hikyuu/blob/2.8.1/hikyuu/__init__.py)
- [2.8.1 StockManager](https://github.com/fasiondog/hikyuu/blob/2.8.1/hikyuu_cpp/hikyuu/StockManager.cpp)
