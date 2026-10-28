# 2026-10-28：Windows合成测试 WinError 32：ParquetFile句柄未显式释放

## Windows复现

用户在更新到PR #70单次Footer预检复用版本后，运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

实际：`Ran 332 tests in 16.841s; FAILED (errors=1)`。唯一错误
`test_query_parquet_exact_locator_preview.ExactLocatorPreviewTests.test_explicit_fast_path_skips_full_query_but_counts_check`
发生在测试函数返回后的`tempfile.TemporaryDirectory.cleanup()`：
`PermissionError: [WinError 32] ...\synthetic stock with spaces\AllCycleAStockData\5min\2026-09.parquet`。
**不是**OHLCVA、不一致、功能断言失败或市场数据损坏。

## 根因与本次代码修复

前一轮引入`prepared_context`，同一次定位查询通过
`query.prepare_query()`取得多个RowGroup共享的`pyarrow.parquet.ParquetFile`
读取器，并在restricted/full Arrow扫描中复用对象。旧`query_bars()`
直接返回`bars/safe_summary`或抛错，**未显式调用`ParquetFile.close()`**。
Python测试的`unittest.mock`调用历史可能延长对`prepared_context`
的引用寿命，Windows对打开的文件不允许立即删除，因而偶发/特定测试报WinError 32。
这是与症状匹配的具体资源生命周期缺陷，而非凭日志可断言的唯一底层句柄来源。

本轮只修改**实验**`tools/query-parquet-exact-locator-preview.py`：
- 在`prepare_query`返回后收集全部`ctx["pending"]`中的唯一
  `ParquetFile`对象（用`id(pf)`去重）。
- 完整的源stat/locator校验、restricted Arrow、可选full Arrow逐根对账、
  安全报告构建全部放入`try`。
- `finally`对所有唯一`ParquetFile`显式`close()`，**即使源指纹、
  报告有效性、行组计数或OHLCVA对账失败**也执行，不依赖GC。
- 不改变正式默认`query-parquet-primary-readonly.py`、私有行情缓存、
  Parquet数据、现有index V3、Arrow计算/统计/安全规则。

补充2项**纯合成**回归测试：
1. 以包装器跟踪并强行保留`ParquetFile`引用（模拟mock引用滞留），
   验证默认full核验和显式fast模式均在函数返回前逐个只`close()`一次；
2. 使用失效的locator stat指纹触发异常，验证拒绝成功报告的同时仍完整关闭
   已打开的读取器。

## Windows验收

仓库根目录：

```powershell
git pull --ff-only origin main

.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_query_parquet_exact_locator_preview.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

前一版`332`项+新`2`项理论上**334项**（以实际Windows日志为准）；
此次修复版本**尚未在用户Windows真实运行**，不得提前写成`334 OK`。

只有完整测试通过以后，才继续之前的真实5min定位预览；已有
`SH600000/2026-09-30`原始安全定位报告及前两次测试文件无需重建。
临时测试目录属于系统临时目录，本修复不会在那里持久输出行情。
