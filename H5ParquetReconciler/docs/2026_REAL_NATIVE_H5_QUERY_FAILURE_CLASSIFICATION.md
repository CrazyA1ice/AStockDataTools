# 2026-10-30：真实Hikyuu H5 native查询失败分阶段定位（禁止泄露行情）

## 最新真实试验与可确认事实

- 用户此前修复后的测试报告为`Ran 13 tests in 1.663s`；本次传来的文本没有完整`OK`行，不应仅凭这几行声称完整Windows验收成功。上一轮已定位五个测试伪阳性来自合法目录名`H5ParquetReconciler`包含`Parquet`。
- 用户真实`realday002`（不能复用此ID）完成、SAFE `real-hikyuu-native-20260930-hmac-v2.json`生成。显示`native_status=runtime_unavailable`,`native_final_phase=finished`,`native_last_work_phase=before_native`,`native_get_kdata_called=true`,`native_matching_stock_day_count=0`,`all_two_native_h5_real_daily_records_match=false`。这意味着子进程启动、StockManager初始化并准备查询真实H5；**不证明读取值不同，更不证明成交额/量单位错误**。原始H5文件大小、mtime未变化（不是内容SHA证据），未修改正式源。
- 发现真实worker的`stock.get_kdata(hk.Query(-64,hk.Query.DAY))`，与**用户Windows已成功的合成native试验**`stock.get_kdata(hk.Query(0,3,hk.Query.DAY))`使用不同构造。按照Hikyuu Query的start/end/ktype次序，两参数位置方式的第二个参数可能被解读为`end`，从而造成错误范围/重载歧义；这是**可疑原因，尚非已证实的真实失败根因**。

## 本轮更改

只修改`tools/verify-real-hikyuu-h5-native-day-isolated.py`子进程的查询路径与固定SAFE状态，不改变父进程对原始H5的只读、原始文件不修改、HMAC、真实报告输出限制，也不会访问Parquet或正式stock.db。

- 在隔离真实core311运行时依次执行`n=stock.get_count(hk.Query.DAY)`，检查`1<=n<=25000`，构造`hk.Query(max(0,n-64),n,hk.Query.DAY)`并调用`get_kdata(query)`。采用以前已通过的**3个位置参数的索引查询协议**，并且native返回记录条数必须与查询窗口完全一致、总数≤64。此方案不会读全H5 KRecord，尽管底层HDF5仍可能进行其固有的内部读取。
- 只有最近64个交易日日线中恰好有一条2026-09-30时才比对原始H5值的匿名HMAC；日期缺失、重复、数量不符或source byte-stat变化都不标记成功。原始OHLCVA/内部整数/密钥、H5相对和绝对路径不出现在SAFE。
- 新增**无源数据泄露**的固定`native_status`分类，覆盖：`failed_at_before_count`,`failed_at_before_query`,`failed_at_before_get_kdata`,`failed_at_kdata_returned`,`failed_at_before_hmac`,`native_no_day_rows`,`native_kdata_count_invalid`,`native_target_day_not_found`,`native_target_day_duplicate`等。不会复制任何原生异常字符串/堆栈/父子进程stdout/stderr（原生日志可能包含用户源文件名或行情值）。
- 扩展阶段标记`before_stock_lookup`,`before_count`,`count_ready`,`before_query`,`query_ready`,`before_get_kdata`,`kdata_returned`,`target_found`,`before_hmac`，由SAFE的`native_last_work_phase`指出故障发生在哪个阶段。`native_get_kdata_called`仅代表已尝试调用，不代表原生解码已成功；依旧只靠完整HMAC比对判定`all_two_native_h5_real_daily_records_match`。
- 在既有13项合成/模拟回归基础上新增**3项**安全状态解析及模拟失败阶段测试，升为**16项（等待用户Windows复验）**。生产H5镜像许可证、物理单位/原生→Parquet量纲认证始终false。

## 本地PowerShell操作——每块各一条完整单行

更新代码：

```powershell
git pull --ff-only origin main
```

仅运行新原生小模块16项合成/模拟测试，不能因最后一行缺失`OK`就宣称已验收：

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_verify_real_hikyuu_h5_native_day_isolated.py" -v
```

确认下一运行ID和SAFE报告都不被占用：

```powershell
Test-Path "H5ParquetReconciler\\work\\h5_mirror\\real_day_native\\realday003"
```

```powershell
Test-Path "H5ParquetReconciler\\reports\\real-hikyuu-native-20260930-hmac-v3.json"
```

以上两项必须均为`False`，且16项测试全部OK，才运行下列**仅打开两份用户真实H5进行只读C++调用**：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\verify-real-hikyuu-h5-native-day-isolated.py --h5-root "D:\\stock\\HikyuuData" --prior-two-source-safe "H5ParquetReconciler\\reports\\real-parquet-h5-raw-day-unit-factor-candidates-20260930-v1.json" --python-exe "D:\\software\\Python311\\python.exe" --run-id "realday003" --timeout 60 --out "H5ParquetReconciler\\reports\\real-hikyuu-native-20260930-hmac-v3.json" --native-read-only-two-stock-day
```

如果`realday003`已经存在，使用全新的run-id及SAFE文件名；**不删除或覆盖**`realday001`/`realday002`，不修改用户原始H5或市场数据库，不扩大到无限查询。

## 后续判断

- `native_status=native_complete`、`native_matching_stock_day_count=2`、`all_two_native_h5_real_daily_records_match=true`并有`native_final_phase=finished`才说明该两股票日原始H5↔native KRecord解码通过HMAC核对。仍**不能**认证购买Parquet供应商的物理单位或全市场通用比例。
- 若`failed_at_before_query`，优先检查core311 Query构造签名；若`failed_at_before_get_kdata`，表示native取数调用出错；若`native_target_day_not_found`，需要单独核验真实H5日期是否处于最近64条，**不要**绕过限制；若`native_kdata_count_invalid`，需核对stock注册库和数据集范围。不在SAFE里输出具体行情。
- 如果返回仍为`runtime_unavailable`，应核对本地是否拉取最新提交；新worker正常捕获任何Python异常时会返回固定`failed_at_...`状态。C++进程崩溃或超时会由父进程产生`native_invalid_or_crashed`/`native_timeout`。
