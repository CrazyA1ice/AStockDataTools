# V3严格写入A/B比较器：Windows 109项合成测试故障修复

日期：2026-10-26；依据用户本机 `python -m unittest discover -s H5ParquetReconciler/tests -p "test*.py" -v` 原始输出。

## 真实失败情况

- Windows Python3.11在合并PR #25之后执行共**109项**，结果为 **5 failures、7 errors**。
- 5项FAIL及5个附属subTest ERROR均集中于 `test_compare_v3_write_order_ab.py` 的错误路径测试。`MatchedReadOnlyABTests.compare()` 用了 `with self.subTest("module path override")`，它会捕获测试中的`ValueError`并登记为subTest ERROR，导致调用方 `assertRaisesRegex(ValueError, ...)` 误判没有抛异常。这不是实际比较器没有拒绝错误报告，而是**测试辅助函数吞掉预期异常**。
- 另外两项ERROR来自合成SQLite测试中 `with sqlite3.connect(...)` 不会自动关闭数据库连接。Windows删除`TemporaryDirectory`时打开的数据库文件被占用，出现`PermissionError [WinError 32]`。
- 同份日志中此前全部非比较器模块的测试显示`ok`。**这不是52组付费Parquet主索引的数据质量审计，也不说明索引损坏**。

## 本轮修复

只修改 `tests/test_compare_v3_write_order_ab.py`，不改 `tools/index-parquet-5min-coverage.py`、`tools/audit-parquet-5min-coverage.py`或 `tools/compare-v3-write-order-ab.py` 的生产行为：

1. 改为 `with mock.patch.object(C.core, "MODULE_DIR", self.module)`，仅替换测试模块路径且在退出时自动复原，**让被测函数正常抛出ValueError供assertRaisesRegex捕获**。
2. 读取测试数据库使用 `with closing(sqlite3.connect(path)) as db`；写测试数据库采用 `with closing(sqlite3.connect(path)) as db: with db: ...`，保证提交后连接被关闭，不留下Windows文件句柄。
3. 新增1个回归测试，验证错误确实传播给调用方，同时复核模块目录已恢复；原109项加1，**预计110项**。

未接触主V3索引（52/522）、H5、付费Parquet，也没有清理、覆盖本机既有数据库或报告。此轮GitHub端修复需要再次本机验证，不能把静态审查称为通过。

## 下一步最小复验（仓库根目录 Windows PowerShell）

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_compare_v3_write_order_ab.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

只有当新的一轮完整测试真正成功后，再运行独立只读52组审计：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --read-only --report "reports\pq-5min-2025-v3-readonly-full-audit-52.json"
```

如果目标报告名已经存在，必须改用另一个新的`--report`文件名。审计只读取已有索引和Parquet footer，不新增RowGroup；报告精确唯一键/重复键仅代表当前52个已提交行组，不能据此自动合并H5/Parquet。

两份新的source/pk-sorted写入A/B仍需先通过上述测试及52组独立完整审计，才可安全继续。
