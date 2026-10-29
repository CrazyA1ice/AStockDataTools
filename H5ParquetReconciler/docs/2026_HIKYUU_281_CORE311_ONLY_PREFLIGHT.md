# Hikyuu 2.8.1：绕过绘图模块的核心绑定隔离预检（2026-10-29）

## 本机证据

- 用户项目Windows原有完整包隔离预检**18/18项测试OK（2.123秒）**，但使用Python3.11中已安装的Hikyuu 2.8.1运行**45秒超时**。
- 上传`hikyuu-native-runtime-preflight-python311-v3.json`显示`hikyuu_runtime_status=hikyuu_import_timeout`；`active_import_stage=package_draw`，`last_import_stage=bokeh`，`last_import_stage_event=leave`，累计63个事件；6条合成H5的校验仍通过，原生C++ KData驱动**没有执行**。
- 这些证据只能确认导入仍停留在绘图模块，**不能断言Bokeh本身有故障**，也不能凭完整导入超时推断底层`hikyuu.cpp.core311`不可用。

## 本轮采用的最小实验

Hikyuu **2.8.1标签**`hikyuu/core.py`针对Python3.11调用`from .cpp.core311 import *`；`hikyuu/cpp/__init__.py`为空。顶层`hikyuu/__init__.py`则额外加载指标/交易/分析/绘图和插件，包含耗时的绘图初始化，因此完整导入并非验证底层HDF5驱动的必要条件。

新增`tools/probe-hikyuu-281-core311-only-isolated.py`：

1. 从之前的可信SAFE报告**重新核验两份纯合成H5哈希**；父进程`.venv`只调用外部已经安装Hikyuu 2.8.1的`D:\\software\\Python311\\python.exe`。
2. 子进程独立`-I -c`，使用已有的`_sandbox_env`把HOME、APPDATA、LOCALAPPDATA、TEMP等限制在模块内`work/h5_mirror/.../_core311_only_probe/`；不调用用户的默认Hikyuu配置、真实`stock.db`、正式行情H5或购买Parquet。
3. 在子进程内使用`importlib.metadata`确认本机`hikyuu==2.8.1`、解释器Python3.11，使用`importlib.util.find_spec`定位已安装的包目录，再和实际distribution路径比对，拒绝任何陌生/异常包路径或缺少必要`cpp`目录。
4. 仅在该子进程内创建一个**内存的`hikyuu`包占位模块**，指向安装目录而不执行原顶层`hikyuu/__init__.py`；在Windows设置与Hikyuu自身初始化相同的`cpp`动态库目录，然后只导入`hikyuu.core`→`cpp.core311`。同时强制确认实际加载了位于已验证`cpp`目录的编译扩展`hikyuu.cpp.core311`（`.pyd`/`.so`），拒绝`core.py`无声回退为`cpp.core`的假阳性；只查询`StockManager`、`Stock`、`Query`、`Parameter`、`KDataDriver`、`DataDriverFactory`、`KRecord`接口是否存在，**不实例化/初始化StockManager，不读取任何K线**。
5. 检查成功后flush固定机器状态标记并`os._exit(0)`，避免Hikyuu native绑定退出引起不相关的阻塞。父进程只从单个固定标记解析，超时/导入异常/缺少接口均失败关停；SAFE JSON绝不包含子进程stdout/stderr、路径、K线行情字段。
6. 本阶段即使`core311_bindings_ready=true`，仍然强制`native_h5_driver_read_executed=false`、`hikyuu_h5_compatibility_certified=false`、`full_market_mirror_allowed=false`。此探针只是下一步**原生H5读取金丝雀**的独立准备实验，不改原生读取工具的默认导入路径。

### Windows验收

仓库根目录：

```powershell
git pull --ff-only origin main
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_probe_hikyuu_281_core311_only_isolated.py" -v
```

预期为新**9项离线/模拟测试全部OK**；用户Windows实测前不能声称已经通过。若测试通过，再运行实际core-only子进程（新的SAFE文件名）：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\probe-hikyuu-281-core311-only-isolated.py --canary-report "H5ParquetReconciler\\reports\\hikyuu-native-synthetic-day-canary-v1.json" --python-exe "D:\\software\\Python311\\python.exe" --timeout-seconds 35 --out "H5ParquetReconciler\\reports\\hikyuu-core311-only-preflight-v1.json" --core-only-preflight
```

**结果分流**：

- `hikyuu_core311_status=core311_bindings_ready`：说明仅core311绑定可加载；下一轮再开发**仅使用core311的StockManager+虚构SQLite+合成H5金丝雀**，原生读取验证还未成功。
- `hikyuu_core311_status=core311_import_timeout`：查看`last_core311_phase`（固定白名单，不含敏感路径）；再细化C++扩展加载/DLL依赖，而不是尝试全量市场数据。
- `hikyuu_core311_status=core311_import_failed_at_*`或`core311_bindings_incomplete`或`core311_extension_not_loaded`：检查当前wheel与2.8.1标签的兼容情况，不修改已安装Hikyuu的软件包。
- 若报告路径已存在，必须改成全新`-v2.json`名称，**不能覆盖**；无论哪种状态都无需上传H5、原始SQLite或市场数据，只提供SAFE JSON。

## 2.8.1来源

- [Hikyuu 2.8.1核心选择器](https://github.com/fasiondog/hikyuu/blob/2.8.1/hikyuu/core.py)
- [Hikyuu 2.8.1顶层初始化](https://github.com/fasiondog/hikyuu/blob/2.8.1/hikyuu/__init__.py)
- [Hikyuu 2.8.1 cpp子包](https://github.com/fasiondog/hikyuu/blob/2.8.1/hikyuu/cpp/__init__.py)
