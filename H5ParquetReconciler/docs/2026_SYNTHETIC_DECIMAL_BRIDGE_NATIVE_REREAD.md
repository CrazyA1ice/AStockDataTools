# 2026-10-29 | 已生成合成 Parquet/H5 的第二次 Hikyuu 2.8.1 原生读取

## 已知 Windows 验收事实

用户现已完成两条不同的合成数据验证链：

1. 原始合成 H5 经真正的 Hikyuu 2.8.1 `cpp.core311` 原生 `Stock.get_kdata` 读取，`SH600000` 与 `SZ000001` 各3条，日期和 OHLCVA 全部匹配；可信 SAFE 为 `reports/hikyuu-native-read-core311-v2.json`。
2. 合成 Decimal Parquet → PyTables 40字节复合 H5 的转换工具，Windows **13/13测试全部OK（5.646秒）**，且用户运行后 `reports/synthetic-parquet-h5-decimal-gate-v1.json` 确认6行编码结果与**前述原生已验收合成H5基准**逐项相同。新生成H5的本身还没有被真正的C++原生驱动读取。

第二项新 SAFE 中：
- `all_six_synthetic_records_exactly_matched_native_baseline=true`
- `SH600000=3`、`SZ000001=3`
- `new_h5_files_tested_by_native_driver=false`
- `actual_purchased_parquet_units_verified=false`
- `licensed_parquet_to_h5_mapping_certified=false`
- `ready_for_full_market_mirror=false`

这组证明**只适用于生成的虚构数据**，绝不允许声称已校验购买Parquet的价格、成交额、成交量实际单位。

## 新增第三层：新生成H5必须再次通过原生读取

脚本：`tools/recheck-synthetic-decimal-h5-native-core311-isolated.py`

- 从`reports/`读取同一合成canary及已经成功的`core311`预检SAFE、Decimal Parquet→H5转换SAFE；检查严格一致的摘要SHA、固定6条、版本、全部门禁标志。
- 仅允许`work/h5_mirror/`下**已经存在的、没有符号链接的单一直属子目录**，里面必须有`sh_day.h5`、`sz_day.h5`、`sh600000_synthetic.parquet`及`sz000001_synthetic.parquet`。前后分别验证四个文件 SHA256，不接受用户实际数据文件绝对路径、H5数据库路径，也不接受外部目录。
- 在**新的私有子目录**`synthetic_decimal_bridge_v1/_native_h5_281/run001/`内新建虚构SQLite/空插件目录；运行已有Windows原生读取成功的`core311` WORKER（仅Python3.11、Hikyuu2.8.1，`-I`子进程）。
- 只对两只虚构股票查询3条日线，并验证日期、开高低收、金额、数量，与工具内固定合成值一致；父进程以二进制接收原生日志，只保留固定阶段和SAFE JSON，不保存C++原始stdout/stderr。
- 任何哈希变化、超时、退出异常、缺少`finished`标记、少于6条或任一字段数值不一致，均禁止认证。
- 新生成H5成功被原生驱动读取后，SAFE会将`new_generated_h5_native_driver_certified=true`。即使如此，`licensed_parquet_units_verified`、`licensed_parquet_to_h5_mapping_certified`和`ready_for_full_market_mirror`**仍为false**。

## Windows本机操作

在 `D:\\ChatGPT\\AStockDataTools` 仓库根目录先执行：

```powershell
git pull --ff-only origin main
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_recheck_synthetic_decimal_h5_native_core311_isolated.py" -v
```

预期是新增**9项离线模拟回归全部OK**。这些离线测试不等于真正的Hikyuu C++运行。

通过后，运行一次**实际只读取两份新生成的虚构 H5**的原生测试：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\recheck-synthetic-decimal-h5-native-core311-isolated.py --canary-report "H5ParquetReconciler\\reports\\hikyuu-native-synthetic-day-canary-v1.json" --decimal-report "H5ParquetReconciler\\reports\\synthetic-parquet-h5-decimal-gate-v1.json" --core-proof "H5ParquetReconciler\\reports\\hikyuu-core311-only-preflight-v1.json" --synthetic-dir "H5ParquetReconciler\\work\\h5_mirror\\synthetic_decimal_bridge_v1" --python-exe "D:\\software\\Python311\\python.exe" --run-id run001 --out "H5ParquetReconciler\\reports\\synthetic-decimal-h5-native-reread-v1.json" --synthetic-native-reread
```

如果该目录曾创建过`_native_h5_281/run001`，请选择**全新run ID**，例如`run002`；如果SAFE报告`v1`已存在，另换为`v2`。绝不覆盖/删除原文件。

**真正成功**的终端反馈应同时满足：
```text
Native status: native_h5_six_synthetic_rows_matched
Last native phase: finished
Matched fictional records: {'SH600000': 3, 'SZ000001': 3}
Purchased Parquet source inspected: NO
```
这只是预期，不代表当前已经运行成功。

上传新生成的SAFE JSON和9项离线测试摘要即可，不要上传用户真实H5、商业Parquet、私有SQLite或原生日志。

## 再往后：只读确定真实Parquet字段与物理单位

仅当合成双向原生验收全部成功，才进入**不会修改真实源的只读统计调查**。调查至少需要确认：Parquet原始列名/Arrow类型、价格的精度、成交量究竟用股还是手、成交额究竟用元还是千元、代码格式、时间戳时区/日期收盘归属，以及日/5分钟/1分钟跨周期合计是否一致。**没有这些证据不能设置真实数值转换倍率，更不能开始全市场写入。**
