# 2026-10-30：真实日线购买Parquet→Hikyuu原始整数的有界只读精度预检

## 主线进度

2026-10-30 用户完成：
- `test_audit_parquet_primary_day_crossyear_factor_evidence_offline.py` **8/8 OK**，五SAFE归档完成，**10/10真实股票日**支持同一套候选日线数值倍率（真实Native C++仅2026-09-30两股2/2）。
- `test_recheck_synthetic_decimal_h5_native_core311_isolated.py` **11/11 OK（1.970s）**；`synthetic-decimal-h5-native-reread-runec409feb8683.json`明确 `native_h5_six_synthetic_rows_matched`、`last_native_phase=finished`、SH600000/SZ000001分别3条，`new_generated_h5_native_driver_certified=true`。PR #154已合并。
- **这只完成合成Decimal Parquet→PyTables H5→Hikyuu 2.8.1原生驱动的技术闭环**，不意味着真实付费Parquet的物理单位获得认证。

原有主线不变：购买Parquet优先→已有H5只补真实缺失股票日→模块私有可回滚统一Parquet→Hikyuu原生H5镜像→通达信盘后只更新统一Parquet。历史分钟K线细微差异机理研究继续暂停。

## 本轮不是简单重复前一个浮点精度脚本

旧 `audit-real-parquet-day-float64-h5-tick-candidates.py` 曾检查“**假设Parquet本身就是Hikyuu解码后的单位**”时价格×1000、amount×10、volume×1的刻度可行性；该脚本已在Windows得到真实两股票日SAFE，但**该前提不是两源真实样本已观察到的Parquet↔H5缩放关系**。

2025/2026三个实际月份10股票日的原始H5↔Parquet候选诊断观察为：
- Parquet价格 ≈ H5原始 `openPrice/highPrice/lowPrice/closePrice ÷1000`。
- Parquet volume ≈ H5原始 `transCount ×100`。
- Parquet amount ≈ H5原始 `transAmount ×1000`。

因此，若仅作**候选数值映射**，真正写入Hikyuu H5原始`u32/u64`刻度时应测试：

| 原始H5整数 | Parquet数值的候选操作 | 原生字段整数范围 |
|---|---|---|
| 4个OHLC `*Price` | `Decimal(str(float)) ×1000` | unsigned 32-bit |
| `transAmount` | `Decimal(str(float)) ÷1000` | unsigned 64-bit |
| `transCount` | `Decimal(str(float)) ÷100` | unsigned 64-bit |

**注意金额÷1000和数量÷100不是物理单位的官方认证，也不是合成H5的amount×10、volume×1两项驱动解码刻度。**本工具不执行真实写入，只用已有原始H5的两个匹配整数检验这个内存候选转换的可行性。

## 新增真实市场只读工具

`tools/audit-real-pq-to-native-h5-raw-exactness-readonly.py`

1. 必须携带此前Windows成功生成的 `reports/parquet-primary-day-crossyear-10-stockday-factor-evidence-v1.json`，校验固定10股票日/原生2股票日/字段倍率/全局认证false/五份SAFE SHA256，并在读市场后再次核对证明SHA。严格拒绝伪造的“全市场可转换”标志。
2. **仅针对2026-09-30 SH600000和SZ000001**，Parquet只允许原有 `day/2026-09.parquet` 的8列，源文件≤150,000条/32组；H5只允许原有 `sh_day.h5`、`sz_day.h5`，每种证券对目标日执行有界二分定位单根原始复合整数，使用既有经过Windows合成测试和真实双源试点的读取器。
3. 对每个字段只输出**两个目标股票日的数量统计**，区分（a）Decimal最短文本精确整数刻度，（b）二进制float64有理数严格整数刻度，（c）需要四舍五入，（d）u32/u64越界，（e）与实际H5原始整数**逐值严格相等且正数非零**，（f）两源双零或一零。不能把十进制可量化、0.005元容差匹配和原始整数真正完全相等混为一谈。
4. 任何缺失、重复、无效/负值、格式错误、超出源扫描预算直接拒绝；只读源文件的size/mtime在前后核对，**不是全源文件内容SHA-256认证**。
5. 从不执行H5写入，不导出任何市场OHLCVA/原始整数/源时间戳/用户绝对文件路径/代码名称，不读取生产SQLite、不切换生产路由。唯一新产物是模块`reports/`一个不能覆盖的脱敏SAFE JSON。
6. 所有 `licensed_parquet_physical_units_certified`、`real_float64_to_native_h5_mapping_certified`、`ready_for_full_market_mirror`等旗标保持**false**。哪怕本轮12字段全部精确相等，也只支持**2个已选股票日**，不能扩展到整个A股或分钟周期。

## Windows验收：单条PowerShell整行执行

从仓库根目录执行本轮**10项合成测试 + 至多一次真实两股票日、日线月文件有界只读**：

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch failed" }; git switch feat/day-real-pq-to-native-h5-raw-exactness-readonly-20261030; if ($LASTEXITCODE -ne 0) { throw "switch failed" }; git pull --ff-only origin feat/day-real-pq-to-native-h5-raw-exactness-readonly-20261030; if ($LASTEXITCODE -ne 0) { throw "pull failed" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_real_pq_to_native_h5_raw_exactness_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "synthetic tests failed; no market scan" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\real-pq-native-h5-raw-integer-exactness-20260930-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-real-pq-to-native-h5-raw-exactness-readonly.py --purchased-root "D:\stock\AllCycleAStockData" --h5-root "D:\stock\HikyuuData" --day 2026-09-30 --prior-ten-safe "H5ParquetReconciler\reports\parquet-primary-day-crossyear-10-stockday-factor-evidence-v1.json" --out $out --read-only-native-int-preview; if ($LASTEXITCODE -ne 0) { throw "real read-only pilot failed" }; Write-Host "SAFE integer feasibility report: $out"
```

只有测试**10/10 OK**才继续执行真实只读试点。原生H5文件不会创建或覆盖；如已经有SAFE报告，GUID自动选择新名字。用户只需返回终端结果及生成SAFE JSON，不上传商业H5/Parquet或原始价量额。

## 下一阶段决定条件

- 如果所有2×6个非零字段**确切与原有H5整数相同**且短十进制无舍入，可以进入**完全独立隔离目录、明确标识候选而非生产镜像**的原生H5两股票日写入试点设计；正式通用单位许可仍false。
- 如果金额/数量不匹配或部分字段要舍入，先记录失败的字段计数，从供应商字段定义与现有真实native KRecord数值证据分析差异，不擅自发明舍入规则或扩大样本。
- 坚持购买Parquet主源、H5仅补10月真实缺日，以及未来可回滚统一Parquet/原生镜像的最终方向，**不再回到历史5分钟残差反复排查**。
