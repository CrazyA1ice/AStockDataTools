# 2026-10-29：经原生驱动核对后的合成Parquet → Hikyuu H5数值精度验收

> **2026-10-29 Windows首次12项测试反馈与修复：** 实测11项通过、1项错误；出错项为`test_synthetic_parquet_to_h5_roundtrip_matches_real_native_read_baseline`，在构造NumPy结构化dtype时出现`TypeError: Tuple must have size 2, but has size 7`，并未进行完整Parquet→H5往返。生产`generate()`使用了相同错误，现已同时修正。NumPy 7项字段描述必须使用`np.dtype(list(LAYOUT))`而不是`np.dtype(LAYOUT)`。集中到`native_h5_dtype(np)`函数，增加40字节宽度、固定字段名以及字段偏移检查，并新增一个不依赖PyArrow的回归测试，更新为**13项待Windows复测**。下面旧文中的“12项”属于上一版本历史记录。

**修复版验收命令（在项目根目录）：**

```powershell
git pull --ff-only origin main
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_synthetic_parquet_to_hikyuu_h5_numeric_gate.py" -v
```

预期`Ran 13 tests ... OK`且`test_synthetic_parquet_to_h5_roundtrip_matches_real_native_read_baseline`为`ok`，不是`skipped`。测试全部通过后，再按本文原有的`synthetic_decimal_bridge_v1`命令运行，输出尚未产生时可使用v1，已存在则必须更换全新目录与SAFE名。


## 真实验收依据（只支持合成数据）

用户Windows已实际运行`read-hikyuu-281-synthetic-h5-native-isolated.py`：离线模拟回归**16/16通过（1.271秒）**，真实Python 3.11 + Hikyuu **2.8.1**原生C++驱动读取两份合成H5日线，`SH600000=3`、`SZ000001=3`，合计6条日期、OHLC、成交额和成交量全部匹配。`reports/hikyuu-native-read-core311-v2.json`中`native_h5_read_status=native_h5_six_synthetic_rows_matched`、`native_h5_compatibility_certified_for_synthetic_v1=true`、`licensed_parquet_to_h5_mapping_certified=false`。

这个结果**仅证明Hikyuu 2.8.1可以正确读取此前生成的40字节整数合成H5**，不是购买Parquet的实际市场单位、日期语义、数值精度已经得到验证。为避免误操作，当前不允许读取商业行情文件，更不允许向原H5写入数据。

## 本轮下一阶段：使用纯虚构小样本搭建Parquet/Decimal → H5数字桥接

新增`tools/synthetic-parquet-to-hikyuu-h5-numeric-gate.py`：

1. 必须从模块`reports/`提供先前有效的**同一份合成金丝雀摘要**和原生6条成功SAFE；解析版本、原生调用、全部匹配条数、成功标志及未涉及正式数据的标志。拒绝其他目录或任意声称已通过的假报告。
2. 只在模块`work/h5_mirror/<NEW-folder>/`生成两份**新虚构的Parquet**；每份3条虚构日线，PyArrow字段分别为`datetime`(int64)、OHLC (decimal128(16,3))、amount (decimal128(24,1))、volume (decimal128(24,0))。该文件**不是**真实购买Parquet的数据结构或字段映射样本。
3. 所有输入的价格、金额、数量**都明确是Hikyuu的KRecord解码后数值单位**，而不是人民币、股、手等实际市场物理单位。现阶段**不假定**真实Parquet的成交额和量单位。`open/high/low/close`乘1000并精确转换到无符号u32；`amount`乘10到无符号u64；`volume`乘1到无符号u64。这是上游Hikyuu 2.8.1`H5KDataDriver.cpp`的**编码逆操作**，不是实盘Parquet单位转换。
4. 全程使用`decimal.Decimal`、无四舍五入，直接拒绝float、NaN/Inf、负值、过于精细的小数、u32/u64溢出、非法日线日期、非法OHLC上下界。
5. 将**新合成Parquet重读**，逐值验证Decimal字段与原虚构样本严格相同，再写出Hikyuu PyTables `/data/SH600000` 和`/data/SZ000001` 40字节compound schema、zlib压缩的两份独立合成H5。
6. 重读新H5，并对比之前**真正由Hikyuu 2.8.1原生驱动验收的合成H5**里的6条整数记录，字段和值逐个一致；前后复核认证金丝雀文件SHA。新H5尚未被原生C++驱动再次读取，因此SAFE报告将`new_h5_files_tested_by_native_driver=false`。
7. SAFE报告仅记录已认证摘要、生成文件哈希、两只虚构股票的记录数量及各个fail-closed标志，**没有OHLCVA明细或任何用户行情路径**；`actual_purchased_parquet_units_verified=false`、`licensed_parquet_to_h5_mapping_certified=false`、`ready_for_full_market_mirror=false`。

## 本轮新增测试

`tests/test_synthetic_parquet_to_hikyuu_h5_numeric_gate.py`，**12项（尚待用户Windows验收）**，覆盖价格三位小数精度、金额一位小数精度、成交量整数精度、溢出、坏日期/非法OHLC、float/NaN/Inf/负值拒绝、假原生成功证明、输出路径安全，以及在具备PyArrow/NumPy/PyTables/h5py环境下的真实**仅虚构Parquet文件 → 合成H5**数值往返。最后一项缺少可选依赖时会显示`skipped`，不能据此宣称Parquet往返验收完成。

## Windows下一轮运行

从项目根目录：

```powershell
git pull --ff-only origin main
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_synthetic_parquet_to_hikyuu_h5_numeric_gate.py" -v
```

期望12项全部OK，尤其应看到`test_synthetic_parquet_to_h5_roundtrip_matches_real_native_read_baseline ... ok`，不能是`skipped`。

测试通过后，执行受限的虚构Parquet到H5桥接（若输出已存在，请同时更换目录`v2`和SAFE文件名`v2`，不可覆盖）：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\synthetic-parquet-to-hikyuu-h5-numeric-gate.py --canary-report "H5ParquetReconciler\\reports\\hikyuu-native-synthetic-day-canary-v1.json" --native-proof "H5ParquetReconciler\\reports\\hikyuu-native-read-core311-v2.json" --out-dir "H5ParquetReconciler\\work\\h5_mirror\\synthetic_decimal_bridge_v1" --safe-report "H5ParquetReconciler\\reports\\synthetic-parquet-h5-decimal-gate-v1.json" --synthetic-only
```

预期输出仅是2只虚构证券各3条整数记录全部与原生已验收金丝雀完全相同；若`pyarrow`不存在，工具会明确提示缺少合成Parquet功能依赖，**不建议为此更换或重装Hikyuu环境**。

请仅上传生成的SAFE JSON及12项测试末尾摘要，不上传任何H5、商业Parquet、全量行情、SQLite或日志。本阶段完成后，再准备严格**只读、仅聚合元数据**的真实Parquet单位/字段证据采集方案，经另行确认，才能决定真实映射。现在不会使用真实市场数据。

### 上游事实与界限

- Hikyuu 2.8.1：`hikyuu_cpp/hikyuu/data_driver/kdata/hdf5/H5Record.h`，日线OHLC为`uint32`，金额和数量为`uint64`。
- `H5KDataDriver.cpp`中返回的KRecord价格=存储整数×0.001、金额=整数×0.1、数量=整数。**不能由此推断购买Parquet里`amount`是否是人民币元、千元或万元，也不能推断其`volume`是否是股或手。**
