# 2026-10-30：Parquet→Hikyuu原生H5 合成闭环的SAFE证明快照门禁

## 已归档的真实证据与当前边界

Windows `main` 分支：`test_audit_parquet_primary_day_crossyear_factor_evidence_offline.py` **8/8项OK（0.686秒）**，成功生成 `reports/parquet-primary-day-crossyear-10-stockday-factor-evidence-v1.json`。报告记录两个证券、跨2025/2026三个不同月份，共**10股票日**支持相同日线候选数值倍率；真实Hikyuu 2.8.1 C++原生KRecord仅验证其中2条。2025年度键列扫描1,333,385行、选择OHLCVA解码123,139行，跨年份合计解码241,108行情行，原始市场源不由本次离线归档程序打开。

**不能**据此授权商业Parquet的量/额物理单位、全市场H5镜像、历史5min/1min映射或正式主库覆盖。已确定的主线：购买Parquet优先→H5仅补真正缺失的股票日→模块内独立可回滚统一Parquet→Hikyuu原生H5镜像→通达信盘后单源增量。继续暂停历史分钟线微差机理研究。

## 本轮代码：真实原生回读的三个证据文件在进程前后必须同字节

已经存在`tools/synthetic-parquet-to-hikyuu-h5-numeric-gate.py`和`tools/recheck-synthetic-decimal-h5-native-core311-isolated.py`，不重新造转换器。新修复只增强**第二个工具**：原生Hikyuu隔离子进程运行前将三份输入SAFE精确字节绑定，子进程结束、合成H5/Parquet和原canary查验后再次计算摘要；**任何一份源证明发生变化就不创建新的成功SAFE**。

三份输入：
1. `reports/hikyuu-native-synthetic-day-canary-v1.json`：完全虚构日线基准。
2. `reports/synthetic-parquet-h5-decimal-gate-v1.json`：合成Decimal Parquet→PyTables H5的6行精确整数证明。
3. `reports/hikyuu-core311-only-preflight-v1.json`：隔离Core311预检证明。

每份必须位于模块`reports/`，路径不能是符号链接，大小1—200000字节；通过现有严格内容门禁后才能启动原生Worker。SAFE结果新增`input_safe_proofs_sha256`及`input_safe_proof_bytes_unchanged_during_native_reread=true`，保留先前`synthetic_decimal_report_sha256`兼容字段。

此项保护是**缩小快照竞态窗口，不是跨进程原子快照**。不改变Hikyuu数值缩放，不访问商业Parquet/H5，不读取已有正式SQLite，不激活private overlay，不写正式Parquet或H5。

## 新增测试及验收

`tests/test_recheck_synthetic_decimal_h5_native_core311_isolated.py`原有9项，增加：
- 子进程中分别将三份SAFE追加仅一个换行（JSON仍合法、布尔语义未变）；必须因为**原始文件字节SHA改变**拒绝，三个来源都覆盖。
- SAFE超过200000字节必须**在启动原生Worker之前**拒绝。

原真实原生成功模拟、文件哈希变化、Worker崩溃或超时、版本/路径边界等旧测试保留。预计**11项单测**（尚待Windows验证）。

Windows PowerShell仓库根目录，完整一行（先只做模拟）：

```powershell
git fetch origin; git switch fix/native-decimal-h5-reread-safe-proof-snapshot-20261030; if ($LASTEXITCODE -ne 0) { throw "switch失败" }; git pull --ff-only origin fix/native-decimal-h5-reread-safe-proof-snapshot-20261030; if ($LASTEXITCODE -ne 0) { throw "pull失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_recheck_synthetic_decimal_h5_native_core311_isolated.py" -v; if ($LASTEXITCODE -ne 0) { throw "synthetic tests失败" }
```

11项全部OK时，才可使用已存在的`work/h5_mirror/synthetic_decimal_bridge_v1`进行一次新的**虚构H5原生C++回读**。必须传入Python3.11/Hikyuu2.8.1独立解释器 `D:\software\Python311\python.exe`；目标run目录和输出SAFE报告每次都应是全新名字（例如使用GUID），旧文件不能覆盖。后续只需上传新的SAFE JSON，不上传生成的H5、真实商业行情或隔离SQLite。

成功验收须同时达到 `new_native_h5_read_status=native_h5_six_synthetic_rows_matched`、`new_generated_h5_native_driver_certified=true` 和两股各3行。**即使全部成功，`licensed_parquet_to_h5_mapping_certified=false`及`ready_for_full_market_mirror=false`依旧是正确结果。**

## 后续主线

合成Decimal Parquet→PyTables H5→真正Hikyuu C++ KData回读闭环验证成功后，下一步规划**现实Parquet字段的只读、小样本、无行情值导出的精度/代码/时间标签结构核查**，在正式转换之前独立认证供货源量纲和时标。实际生产镜像尚未批准。
