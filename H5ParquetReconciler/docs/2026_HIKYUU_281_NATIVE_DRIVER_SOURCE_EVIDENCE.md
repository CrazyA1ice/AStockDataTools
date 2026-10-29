# Hikyuu 2.8.1 原生日线 H5 读取依据与隔离验收准备（2026-10-29）

## 本次新增的本机事实

- `D:\\software\\Python311\\python.exe -m pip show hikyuu` 返回 `Name: hikyuu`、`Version: 2.8.1`、安装位置 `D:\\software\\Python311\\Lib\\site-packages`。Python 3.15 和 Anaconda base 的`pip show`未找到该包；另发现Conda `hikyuuQ` 环境，但未检查其Hikyuu版本。
- Windows合成运行时测试此前1/12失败，修复`WindowsPath`严格类型判断后，用户本机12项全部通过：`Ran 12 tests in 1.592s`、`OK`。
- 此时尚未运行 **Python 3.11 的隔离运行时SAFE预检**，因此`hikyuu_imported_without_initializing`、真实Python binding接口及原生C++ H5加载均不能预设通过。
- 项目`.venv`不必安装Hikyuu，仍由该环境使用h5py核验双股合成文件SHA；通过显式`--python-exe`调用已有Python 3.11作为**隔离子进程**。

## 与2.8.1版本完全对应的源码检查（不是latest/master猜测）

实际核对上游`fasiondog/hikyuu`的`2.8.1`标签：

- `hikyuu_cpp/hikyuu/data_driver/kdata/hdf5/H5KDataDriver.cpp`：`_init()`按参数`sh_day`、`sz_day`（case insensitive）从明确的文件路径打开只读H5；日线读取访问`/data/<market><code>`，并通过HDF5 compound字段名转换为C++ `H5Record`（内存结构顺序可不同于PyTables落盘顺序）。
- 同文件`_getBaseKRecordList()`将H5原始整数转换为Hikyuu `KRecord`：**OHLC乘`0.001`、`transAmount`乘`0.1`、`transCount`原值不变**；H5 datetime是`YYYYMMDDHHMM`。这只是**Hikyuu自身编码与解码规则**，完全不能证明购买Parquet中volume/amount的单位是什么，不能简单从购买Parquet做×1000/×10转换批量生成H5。
- `hikyuu_pywrap/data_driver/_DataDriverFactory.cpp`将`DataDriverFactory`、`getKDataDriverPool`等接口暴露到Python；`hikyuu_pywrap/data_driver/_KDataDriver.cpp`暴露`KDataDriver.getCount`与`_getKRecordList`等抽象接口，但当前未证实用户wheel中可将原生工厂返回的pool变为直接可用的Python对象。
- `hikyuu_pywrap/_StockManager.cpp`有`StockManager.instance().init(base_info_param, block_param, kdata_param, preload_param, hikyuu_param, context)`；**初始化还会加载证券基础信息**，不能直接沿用已有`stock.db`、默认`hikyuu.ini`或`hikyuu.interactive`，否则可能触碰用户正式行情/配置。后续若采用StockManager路线，必须先构造隔离的虚构证券注册库或评估更简单的原生HDF5驱动直通接口。

## 下一步在 Windows 运行的安全命令

在仓库根目录执行（先确认已拉取最新代码；SAFE输出用新的名称，避免覆盖）：

```powershell
git pull --ff-only origin main
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\probe-hikyuu-native-driver-runtime-isolated.py --canary-report "H5ParquetReconciler\\reports\\hikyuu-native-synthetic-day-canary-v1.json" --python-exe "D:\\software\\Python311\\python.exe" --out "H5ParquetReconciler\\reports\\hikyuu-native-runtime-preflight-python311-v1.json" --isolated-preflight
```

这只运行`import hikyuu`并报告绑定API存在性，**绝不调用StockManager.init、hikyuu_init或native读取**。如果显示`hikyuu_import_failed`或`hikyuu_subprocess_failed`，先检查隔离环境的DLL/依赖是否适配；不要通过移除`-I`或指向正式行情库绕过失败。报告不存在时不生成源数据，已存在时另用v2名称。

收到`hikyuu-native-runtime-preflight-python311-v1.json`后，才能设计针对2.8.1用户wheel、全程在模块`work/h5_mirror`里运行的**真正原生H5解码金丝雀**：两只股票各3根虚构日线、匹配每一条datetime/ohlc/amount/volume，不允许原始H5、购买Parquet或真实SQLite证券数据库进入子进程。成功后仍需要实际验证Parquet原数据的对应单位并做精度/溢出审计，再考虑镜像批量生成。

## 外部来源

- [Hikyuu 2.8.1 H5KDataDriver.cpp](https://github.com/fasiondog/hikyuu/blob/2.8.1/hikyuu_cpp/hikyuu/data_driver/kdata/hdf5/H5KDataDriver.cpp)
- [Hikyuu 2.8.1 Python DataDriverFactory binding](https://github.com/fasiondog/hikyuu/blob/2.8.1/hikyuu_pywrap/data_driver/_DataDriverFactory.cpp)
- [Hikyuu 2.8.1 StockManager binding](https://github.com/fasiondog/hikyuu/blob/2.8.1/hikyuu_pywrap/_StockManager.cpp)
