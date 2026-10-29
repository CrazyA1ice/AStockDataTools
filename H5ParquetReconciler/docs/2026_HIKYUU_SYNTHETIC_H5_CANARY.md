# 2026-10-29 原生Hikyuu H5镜像：完全合成数据的隔离结构金丝雀

## 真实证据与边界

上一轮用户本机只读结构报告 `hikyuu-native-day-contract-SH600000-SZ000001-20260930-20261013-v1.json` 明确确认：

- 原始`HikyuuData/sh_day.h5`与`sz_day.h5`均包含PyTables `CLASS=TABLE`、压缩`gzip`、chunked的一维compound数据集；
- 真正**落盘**字段顺序是：`closePrice uint32@0`、`datetime uint64@4`、`highPrice uint32@12`、`lowPrice uint32@16`、`openPrice uint32@20`、`transAmount uint64@24`、`transCount uint64@32`；每记录40字节，两股相同；
- 全历史SH600000有6,404条、SZ000001有8,468条；2026-09-30～10-13两股各5条，且窗口起止时间键合法；
- `structural_h5record_candidate=true`，但`field_order_matches_legacy_h5record=false`、`hikyuu_native_driver_verified=false`、`ready_for_full_h5_mirror_write=false`；H5与联合Parquet的**数量相同不等于六字段完全相同**。
- 用户上次粘贴测试日志末尾仅显示`Ran 7 tests in 0.719s`，没带最终`OK`行，因此不能据此确定7/7全部通过。真实结构报告独立表明只读probe运行成功。

公开参考：`https://hikyuu.org/ref-doc/structhku_1_1_h5_record.html`记录旧H5Record成员的逻辑类型，但**C++声明排列顺序不等于PyTables实际按字段名排列后的落盘顺序**；当前两股观测得到的真实40字节偏移优先。

## 本轮代码

新增`tools/build-hikyuu-native-h5-synthetic-canary.py`。它**只读取之前生成的SAFE结构报告，不打开任何原始H5、不读取购买Parquet、不读取已准备的真实私有日线stage**。

- 强制报告与两只股票精确对应，且HDF5属性、整数有无符号性、顺序、偏移和40字节长度与本机真实报告完全一致。任意一项不匹配直接拒绝。
- 使用`numpy`、`tables` (PyTables) 在`H5ParquetReconciler/work/h5_mirror/<全新目录>/`分别新建合成`sh_day.h5`、`sz_day.h5`，每只股票只有固定**3条完全虚构**2026-09-30、10-08、10-13日线（合计6根）；明令禁止将此目录视作真实行情库。
- PyTables创建`/data/SH600000`、`/data/SZ000001`，使用40字节uint compound和zlib (HDF5 gzip)压缩。h5py再检验CLASS=TABLE、顺序、字段类型/偏移、完整合成整数序列逐值一致；PyTables再次打开同一个文件核对记录条数。
- **只允许在模块目录内部**生成H5输出，且拒绝任何已有同名目录；`reports/`下另存全新的仅SAFE摘要（schema/文件相对路径/sha/条数，没有价格或成交数据）。失败自动清理本次新建的未完成合成目录和不完整SAFE报告。
- 明确`hikyuu_native_driver_tested=false`、`hikyuu_driver_compatible_certified=false`、`safe_for_full_market_h5_mirror=false`。通过h5py/PyTables并不证明Hikyuu的C++驱动可以读取，也完全没有认证H5/PQ价量金额映射。

新增7项完全合成测试，核验两股无损往返、拒绝覆盖、错误dtype、错误调查证据、非法路径、写入失败清理、股票集合不匹配。尚未经过用户Windows执行。

## Windows下一步（仓库根目录D:\ChatGPT\AStockDataTools）

先确认本机`tables`包是否已安装（这次写入金丝雀需要PyTables，之前只读扫描只需要h5py）：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m pip show tables
```

如提示找不到`tables`，先单独安装到当前虚拟环境（不影响原始行情文件）：

```powershell
.\.venv\Scripts\python.exe -m pip install tables
```

然后执行**新增7项**测试（不得以`skipped`算通过）：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_build_hikyuu_native_h5_synthetic_canary.py" -v
```

测试全部`OK`且不包含`skipped`后，运行一次真实**结构证据驱动**、但实际只生产虚构数据的金丝雀：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\build-hikyuu-native-h5-synthetic-canary.py --survey "H5ParquetReconciler\reports\hikyuu-native-day-contract-SH600000-SZ000001-20260930-20261013-v1.json" --out-dir "H5ParquetReconciler\work\h5_mirror\synthetic_day_canary_v1" --out "H5ParquetReconciler\reports\hikyuu-native-synthetic-day-canary-v1.json" --synthetic-only
```

预计仅新建`work/h5_mirror/synthetic_day_canary_v1/sh_day.h5`、`sz_day.h5`以及新的SAFE摘要；**若上述输出已存在，换一个全新v2目录和v2报告名，不要覆盖**。不需再跑真实四日H5/PQ一分钟审计，亦不需上传任何源H5、付费日线或虚构H5本体。请回传7项完整测试结果（含最后`OK`）及SAFE`hikyuu-native-synthetic-day-canary-v1.json`。

## 后续正式原生驱动验收

下一轮应仅用`work/h5_mirror/`中的虚构canary，隔离配置Hikyuu的数据驱动，实际用其`Stock.get_kdata(Query(..., DAY))`读取，验证三条日期/价量数值**并避免误载用户正式行情库**。只有原生C++驱动加载且小样本验证、单位映射单独通过之后，才讨论从统一Parquet读取真实行情并建立可回滚H5镜像。

### 严格限制

不能把该合成文件复制或覆盖到`D:\stock\HikyuuData`，不能将虚构的3根K线用于交易、回测或补全任何实际证券日期，不能将`hikyuu_native_driver_tested=false`改成true冒充验收。
