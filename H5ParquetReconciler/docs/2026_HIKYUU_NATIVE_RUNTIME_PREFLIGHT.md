# 2026-10-29：Hikyuu原生运行时接口隔离预检（不加载真实数据库）

## 输入验收证据（已由Windows实际完成）

- 用户Windows新增7项完全合成H5构造测试：`Ran 7 tests in 0.716s`，`OK`，没有跳过。
- 用户本机合成金丝雀 SAFE JSON：`hikyuu-native-synthetic-day-canary-v1.json`，`synthetic_only=true`，SH600000和SZ000001各3条假日线、每条40字节，两个文件分别由PyTables/h5py按整数逐值完全往返一致。
- 实际合成文件：`work/h5_mirror/synthetic_day_canary_v1/sh_day.h5`与`sz_day.h5`，SHA分别为：
  - SH: `c9515254c469597c3cb1d40efed9f858b2f54f3acca606124566dc7305d1136d`
  - SZ: `361956473234f8c51261073cbb0fd0e91221bc92f90fcee43843621982e67269`
- `hikyuu_native_driver_tested=false`、`hikyuu_driver_compatible_certified=false`、`safe_for_full_market_h5_mirror=false`仍为真实状态；尚未用Hikyuu原生C++/Python数据驱动读出合成K线。

## 为什么本轮还不直接调用 StockManager？

Hikyuu的公开Python文档确有`StockManager.instance().init(base_info_param, block_param, kdata_param, preload_param, hikyuu_param[, context])`与`Stock.get_kdata(Query(...))`，但需要真实的、版本匹配的`baseinfo`和`kdata`参数/元数据注册。不能直接调用用户现有默认`hikyuu_init`或`hikyuu.interactive`加载正式库，亦不能把空白SQLite伪装为有效的隔离基础信息库。

本阶段先确认**用户当前`.venv`中究竟装了哪个Hikyuu版本、C++ Python binding暴露哪些类**，后续再根据实际接口开发真正的**隔离HDF5 native driver load**。这是一项更窄、但必须完成的真实运行时证据，不应把`h5py`读到3条冒充`Hikyuu`读取了3条。

## 新脚本

`tools/probe-hikyuu-native-driver-runtime-isolated.py`：

1. 只接受`reports/`中此前合成金丝雀SAFE文件，逐一核对完整SHA及`work/h5_mirror`下两份文件路径，并经h5py校验**仅合成时间键**为20260930、20261008、20261013；任何不符立即拒绝。
2. 使用**同一`.venv` Python可执行文件**的隔离子进程（`-I`），独立设置`HOME/USERPROFILE/APPDATA/LOCALAPPDATA/TMP/TEMP/XDG_CONFIG_HOME`至`work/h5_mirror/synthetic_day_canary_v1/_runtime_preflight`，剥离父进程`HIKYUU_*`与`HKU_*`变量。
3. 子进程仅做`import hikyuu`、获取`importlib.metadata.version("hikyuu")`和固定小集合API存在性：`StockManager`、`Stock`、`Query`、`Parameter`、`KDataDriver`、`DataDriverFactory`、`H5KDataDriver`、`hikyuu_init`、`KRecord`。**不导入`hikyuu.interactive`，不执行`hikyuu_init`，不初始化StockManager，亦不加载任何行情文件。**
4. 子进程崩溃、导入失败、缺包、20秒超时都原样标成“导入状态未知/失败”，且不会将原生兼容标为真。不会把子进程banner、日志、异常堆栈或文件路径写入SAFE JSON。
5. 子进程结束后再次核对合成文件SHA，最后仅在`reports/`**新建**一个统计JSON。强制`native_h5_driver_read_executed=false`、`hikyuu_h5_compatibility_certified=false`、`full_market_mirror_allowed=false`。

这仍不是native driver读取，只是**为下一轮构造安全的native真实读取绑定方式提供版本与API证据**。不要借此切换任何生产路由。

## Windows下一步

在`D:\ChatGPT\AStockDataTools`仓库根目录运行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_probe_hikyuu_native_driver_runtime_isolated.py" -v
```

预期新8项完整`OK`，且不出现Skipped。通过后：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\probe-hikyuu-native-driver-runtime-isolated.py --canary-report "H5ParquetReconciler\reports\hikyuu-native-synthetic-day-canary-v1.json" --out "H5ParquetReconciler\reports\hikyuu-native-runtime-preflight-v1.json" --isolated-preflight
```

若预检成功，请上传**只有统计元数据**的`hikyuu-native-runtime-preflight-v1.json`和8项测试末尾。无须上传`sh_day.h5`、`sz_day.h5`、`stock.db`或`hikyuu.ini`；也无须重新生成canary或再做55秒行情源复核。若当前虚拟环境未安装Hikyuu，SAFE会显示`hikyuu_not_installed_in_this_interpreter`，不要自动修改其他Python环境。报告已存在时，改用`v2`新文件名。

## 后续真正的Hikyuu原生读取验收

根据回传安装版本和API，新增隔离的Hikyuu HDF5 driver初始化测试程序，优先使用正式公开的数据驱动参数与合成基础信息注册。只允许`work/h5_mirror`中两份合成文件；禁止默认配置、用户原始data-dir、真实`stock.db`、远程市场数据或真实交易。只有Stock.get_kdata(Query.DAY)或等价原生C++驱动返回**三条完全一致的合成日期/价量**，并核对数值缩放，才可将`hikyuu_native_driver_read_executed`设为true。之后仍须重新评估Parquet价格/量/额的映射和镜像批量构建。
