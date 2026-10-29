# 2026-10-29：原生 Hikyuu H5 格式探查（严格只读，非镜像生成）

## 已通过的研究主线

- 用户Windows最新回传批量版 **14/14项合成测试OK（6.643秒）**，包括已有显式不可变SHA查询与新的模块私有活动指针只读消费（指针变化、恶意格式、锁文件、模式互斥）；**真实私有活动指针仍未激活**。
- 先前SH600000/SZ000001的真实批量只读SAFE报告：各返回1根购买Parquet日线+4根已验收私有日线，合计10根；一次实时四日H5/PQ完整性重查，57.327676秒；购买历史原件与原始H5、生产查询均未变。
- 从本轮开始，按`2026_PARQUET_PRIMARY_EXECUTION_PLAN.md`转入**独立原生Hikyuu H5镜像**准备；但不可直接把`day.parquet`导出的任意HDF5表声称可供Hikyuu使用。

## 源格式证据与必须区分的两种概念

Hikyuu公开的历史H5Record定义（日线数据驱动原理）是`datetime: uint64`、`openPrice/highPrice/lowPrice/closePrice: uint32`、`transAmount/transCount: uint64`；通常通过`/data/SH600000`等市场证券表组织。公开结构定义的出处为`https://hikyuu.org/ref-doc/structhku_1_1_h5_record.html`；另有旧版PyTables写法参考`https://gitee.com/billee/hikyuu/blob/master/testdata.py`（**历史资料，不保证用户当前Hikyuu版本完全相同**）。

现有仓库`reconcile-local-a-share-h5-parquet.py`已使用`datetime/openPrice/highPrice/lowPrice/closePrice/transCount/transAmount`逻辑字段集合读取旧H5，并以`YYYYMMDD0000`处理日线，但这不证明字段的**有符号性、内存偏移、顺序、压缩布局、PyTables标记和真实Hikyuu驱动兼容性**。既有合成旧H5测试甚至使用`<i4`价格并不同字段顺序，必须查真实`sh_day.h5/sz_day.h5`后再决定镜像写法。

## 本轮新增脚本

`tools/probe-hikyuu-native-day-h5-readonly.py`：输入现存原H5根目录、1～10只规范A股代码和同年≤31天的日线窗口，**严格不写任何源文件、也不读购买Parquet、不会生成镜像**。它会：

- 精确使用`HikyuuData/<market>_day.h5`，拒绝源文件或源目录链接，记录文件大小和mtime前后并拒绝变化；
- 只读取HDF5`/data/<SYMBOL>`表的类型、整数kind/字节宽度、偏移、字段顺序/集合、PyTables`CLASS=TABLE`标记是否存在（只记属性名不记值）、每股票全表行数；
- 复用现有`h5_key_slice`二分搜索计算**指定日期窗口**的行情记录数量，最多读取边界时间键；不遍历全历史价格列、不输出任何Open/Close/Vol/Amount值；
- 将字段布局是否与**历史**H5Record结构相容记录为`structural_h5record_candidate`，绝不宣称已被安装的Hikyuu实际读取；
- 安全JSON仅在`H5ParquetReconciler/reports/`创建**新文件**，默认不会覆盖既有报告。

`hikyuu_native_driver_load_tested=false`、`ready_for_full_h5_mirror_write=false`、`h5_daily_units_supplier_certified=false`三个标志是硬约束。实际转换前必须在用户当前Hikyuu环境进一步测试真正的驱动读取（例如stock.get_kdata/Query.DAY返回值）、全历史索引顺序、单位比例和全市场数据安全；不能因为字段名兼容而直接上线。

**注意**：本次读取特意限制在SH600000和SZ000001两支已证实能在统一Parquet取到记录的证券，结构探查不能证明全市场的H5完全同构；不会要求用户上传h5或商业行情。

## Windows下一轮验收

在仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_probe_hikyuu_native_day_h5_readonly.py" -v
```

预期**7项合成测试**，均需`OK`，该文件尚未Windows实测。

通过后在原始源只读探查SH600000和SZ000001：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\probe-hikyuu-native-day-h5-readonly.py "D:\stock" --symbols SH600000 SZ000001 --from-date 2026-09-30 --to-date 2026-10-13 --out "reports\hikyuu-native-day-contract-SH600000-SZ000001-20260930-20261013-v1.json" --read-only
```

只上传本次的**结构安全JSON**和7项测试输出；不要上传`sh_day.h5/sz_day.h5`、任何`day.parquet`或完整OHLCVA数据。由于本次仅查实际旧H5元数据，通常不需要再跑55秒的H5/PQ全量市场交集审计。

## 后续路线

本轮真实格式验收 → 在`H5ParquetReconciler/work/h5_mirror/`创建极小的**隔离合成镜像**并用用户真实Hikyuu驱动读取 → 探索购买Parquet主源+已验收overlay如何无损按价/量/金额映射 → 批量原生H5镜像及回滚 → TDX盘后数据单点写入Parquet、镜像增量同步。所有数据在本地，不提交到GitHub；保持原数据只读，勿误称10月14日以后已有真实K线。
