# Hikyuu 2.8.1：隔离调用原生HDF5驱动读取完全合成日线（2026-10-29）

## 真实证据、版本与边界

- 已知用户电脑`D:\\software\\Python311\\python.exe`安装`hikyuu 2.8.1`，该路径与虚拟环境分离；更新的旧版隔离预检测试`Ran 12 tests in 1.592s / OK`。
- 此前仅由用户提供PyTables/h5py合成H5 SAFE报告：`SH600000`和`SZ000001`各有3条完全虚构日线，40字节H5Record字段，SHA256已经记录并通过原工具复核。用户**尚未提供使用Python311真正执行隔离运行时预检的SAFE报告**，也**尚未执行本工具的Windows验收**。
- 上游Hikyuu **2.8.1标签**`H5KDataDriver.cpp`：原生读取日线`/data/<market+code>`，`sh_day/sz_day`配置是显式文件路径；整数OHLC×0.001，transAmount×0.1，transCount不缩放。上游`StockManager.cpp`的`init`需要基础证券登记库，所以不允许对用户现有`stock.db`或默认`hikyuu.ini`初始化，绝不能把h5py读取当原生驱动读取。
- **注意**：Hikyuu的驱动缩放并不证明购买Parquet的成交量/成交额单位；即使本轮全部通过，也不允许直接生成真实全市场镜像或切换生产查询。

## 本轮新增源文件

`tools/read-hikyuu-281-synthetic-h5-native-isolated.py`调用项目内先前的`probe-hikyuu-native-driver-runtime-isolated.py`复核双股票**完全虚构**H5元数据、路径及文件哈希。之后：

1. 必须显式指定已有的`--python-exe`绝对路径（例如Python311），拒绝默认`.venv`或相对解释器；禁止shell、安装包、覆盖输出和引用市场源。
2. 使用`-I`子进程，HOME、APPDATA、TMP、当前工作目录全部隔离至模块`work/h5_mirror/synthetic_day_canary_v1/_native_h5_281/<run-id>/`；`--run-id`必须是**新名字**，允许失败后保留现场并使用run002安全重试。
3. **仅在子进程本次新建的文件**`fictional_registry.sqlite3`登记两只虚构A股及辅助空表；不打开、不拷贝任何用户真实`stock.db`、默认Hikyuu配置或购买Parquet。调用`StockManager.instance().init(...)`时显式传入唯一虚构SQLite和两份合成H5绝对路径，关闭历史财务加载和行情预加载。
4. 仅支持**2.8.1**安装版本，不自动尝试其他版本的API、配置；使用真正的`Stock.get_kdata(hk.Query(0,3,hk.Query.DAY))`分别读取3条虚构日线。检查全部日期、开高低收、成交金额、成交量严格匹配上游驱动的整数缩放预期（浮点容差1e-8）。
5. 子进程崩溃、超时、缺包、版本不匹配、SQLite不兼容、StockManager初始化异常、行数/任意数值异常全部失败关停，输出`native_h5_synthetic_six_records_matched=false`。测试中即使Hikyuu导入成功，**也不算原生KData读取成功**。
6. 子进程前后再次复核合成源H5 SHA/大小；SAFE报告仅记录子进程机器状态、两股各已匹配条数及安全标志，不包含虚构或真实OHLCVA明细、stdout/stderr、原始用户名与文件绝对路径。

**首次Windows运行状态未知**：2.8.1的Python wheel绑定、模拟SQLite辅助表及环境DLL可能需要后续据报告调整。不能声称已实测通过。

## Windows执行顺序

```powershell
cd D:\\ChatGPT\\AStockDataTools
git pull --ff-only origin main

.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_read_hikyuu_281_synthetic_h5_native_isolated.py" -v
```

本文件新增9项**离线合成/模拟测试**，`Ran 9 tests / OK`才进行下面两个隔离步骤。

**先运行Python311导入/API安全预检（如果此前没有运行）：**

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\probe-hikyuu-native-driver-runtime-isolated.py --canary-report "H5ParquetReconciler\\reports\\hikyuu-native-synthetic-day-canary-v1.json" --python-exe "D:\\software\\Python311\\python.exe" --out "H5ParquetReconciler\\reports\\hikyuu-native-runtime-preflight-python311-v1.json" --isolated-preflight
```

查看SAFE结果的`hikyuu_runtime_status`；如果不是`hikyuu_imported_without_initializing`，就先停止，回传JSON。

**如果Python311导入成功，尝试首次真正的原生C++驱动读取：**

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\read-hikyuu-281-synthetic-h5-native-isolated.py --canary-report "H5ParquetReconciler\\reports\\hikyuu-native-synthetic-day-canary-v1.json" --python-exe "D:\\software\\Python311\\python.exe" --run-id run001 --out "H5ParquetReconciler\\reports\\hikyuu-native-read-281-canary-v1.json" --synthetic-native-read
```

预计只会在模块内`work/h5_mirror/synthetic_day_canary_v1/_native_h5_281/run001`新建**虚构的**数据库/日志，并在`reports/`新建安全JSON。若遇到`run ID already exists`，请改为`--run-id run002`且改用`...-v2.json`全新报告名；不能覆盖已有报告和运行目录。若子进程直接崩溃或SQL schema不兼容，报告将标注`native_subprocess_invalid_or_crashed`或`native_runtime_failed_at_*`，此时不要自行改用默认Hikyuu数据库来绕过。

## 请回传

- 新增9项合成测试完整结尾；
- `reports/hikyuu-native-runtime-preflight-python311-v1.json`（若此前没有）；
- `reports/hikyuu-native-read-281-canary-v1.json`，**即使失败也要上传SAFE JSON**；
- 不需要上传H5、SQLite或真实行情/交易数据。

仅当6条虚构K线的日期、全部OHLCVA**由Hikyuu原生驱动读出且逐值相同**时，才能视为针对Hikyuu 2.8.1的隔离合成H5兼容验证完成；之后再进入Parquet数值单位与精度校验。

## 参考源码（2.8.1标签）

- https://github.com/fasiondog/hikyuu/blob/2.8.1/hikyuu_cpp/hikyuu/data_driver/kdata/hdf5/H5KDataDriver.cpp
- https://github.com/fasiondog/hikyuu/blob/2.8.1/hikyuu_pywrap/_StockManager.cpp
- https://github.com/fasiondog/hikyuu/blob/2.8.1/hikyuu_pywrap/_KRecord.cpp
- https://github.com/fasiondog/hikyuu/blob/2.8.1/hikyuu/data/sqlite_upgrade/createdb.sql
