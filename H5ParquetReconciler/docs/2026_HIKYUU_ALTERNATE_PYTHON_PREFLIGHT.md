# 2026-10-29 Hikyuu实际Python环境定位与隔离预检

## 已有真实验收

- Windows本机上新8项隔离探针合成测试：`Ran 8 tests in 0.851s`，`OK`。
- 用户上传SAFE `hikyuu-native-runtime-preflight-v1.json`：两只股票的合成H5 SHA重新核验`true`；`hikyuu_runtime_status="hikyuu_not_installed_in_this_interpreter"`，版本null，接口{}。也就是运行此探针的`D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe`当前未安装Hikyuu。
- 这**不是**Hikyuu原生驱动读取失败，也不证明电脑其他Python环境没有Hikyuu；`native_h5_driver_read_executed=false`，`full_market_mirror_allowed=false`。原始H5/Parquet未读未改；合成H5文件已经过PyTables/h5py验证。

## 本轮新增功能

对已有`tools/probe-hikyuu-native-driver-runtime-isolated.py`增加**可选显式`--python-exe`**，仅改变隔离子进程采用的解释器，不改变主工具在项目`.venv`中用h5py校验双股合成H5的方法。

- 默认仍用当前`.venv`。若指定`--python-exe`，必须是绝对路径、真实的非软链接`python.exe`等，不使用PATH猜测，不执行shell，也不安装任何包。
- 启动仍采用`<指定的解释器> -I -c <固定安全脚本>`，隔离HOME/APPDATA/LOCALAPPDATA/TMP/XDG_CONFIG_HOME，清理HIKYUU、HKU、PYTHONPATH、PYTHONHOME、VIRTUAL_ENV及旧Conda标记。Windows按需将所选Python的`Library/bin`添加至子进程PATH以方便已有Conda发行版装载本身DLL。
- 子进程**只**尝试`import hikyuu`与检查固定名称的API类是否存在，绝不执行`hikyuu_init`、`StockManager.init`或导入`hikyuu.interactive`，也不以检测成功宣称原生H5可读。
- SAFE报告只记录`explicit_alternate_python_requested`和Hikyuu版本/API存在性，不暴露用户本机Python路径或配置，旧的全局数据源、生产数据源与22,191条私有stage均不受影响。
- 之前8项测试上新增4项合成回归，累计12项，新版本尚需在Windows跑完整`OK`。

## Windows建议按这个顺序尝试

1. 在仓库根目录更新源码并跑12项合成测试：

```powershell
cd D:\ChatGPT\AStockDataTools
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_probe_hikyuu_native_driver_runtime_isolated.py" -v
```

2. 查电脑可能存在的Python环境（**仅查看，不安装**）：

```powershell
py -0p
where.exe python
if (Test-Path "D:\software\anaconda\python.exe") {
    & "D:\software\anaconda\python.exe" -m pip show hikyuu
}
```

`D:\software\anaconda\python.exe`是此前项目日志出现过的Python环境**候选路径**，不是已确认的Hikyuu安装路径；如果不存在就不要照此执行，可用`py -0p`显示的实际解释器路径。

3. 如果`pip show hikyuu`在某个Python环境中显示已安装，则仍然使用本项目`.venv`启动隔离探针，显式选择该路径。以下以存在`D:\software\anaconda\python.exe`为例：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\probe-hikyuu-native-driver-runtime-isolated.py --canary-report "H5ParquetReconciler\reports\hikyuu-native-synthetic-day-canary-v1.json" --python-exe "D:\software\anaconda\python.exe" --out "H5ParquetReconciler\reports\hikyuu-native-runtime-preflight-alternate-v1.json" --isolated-preflight
```

若该路径不存在/没有Hikyuu，改成真正安装了Hikyuu的`python.exe`**完整路径**。报告文件已经存在则换`v2`，不能覆盖。**不要向任何环境自动安装或升级Hikyuu**，先把现有版本报告回传。

4. 上传**只有元数据**的`reports/hikyuu-native-runtime-preflight-alternate-v1.json`和12项测试完整结尾。无须上传H5、商业数据、用户`hikyuu.ini`或正式`stock.db`。

## 准入边界

Hikyuu成功导入且暴露需要的接口，仅表示可以进入**下阶段真正隔离原生驱动读取**的技术设计，不能将`hikyuu_h5_compatibility_certified`改为true。下一阶段必须在无默认数据库路径且无真实证券账户/生产行情的合成登记环境中，调用真正的H5数据驱动并逐条核验3根日期/价/量/额。若当前所有Python环境都没有Hikyuu，再评估新建*隔离测试环境*安装相容版本，不污染项目`.venv`。
