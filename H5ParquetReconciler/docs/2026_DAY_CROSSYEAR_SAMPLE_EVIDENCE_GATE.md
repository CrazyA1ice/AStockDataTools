# 2026-10-30：跨年份10个股票日的候选数值倍率，进入Parquet主源证据门禁

> **2026-10-30 Windows 验收完成：** 用户在 `main` 分支运行
> `test_audit_parquet_primary_day_crossyear_factor_evidence_offline.py`，
> **8/8 项全部 `OK`（0.686秒）**；随后五SAFE离线聚合成功，生成
> `reports/parquet-primary-day-crossyear-10-stockday-factor-evidence-v1.json`。
> 新SAFE确认日线10/10候选数值匹配、2025年度两列键读取1,333,385行、
> 2025目标OHLCVA解码123,139行、跨年合计OHLCVA 241,108行，
> 以及真实Hikyuu 2.8.1 C++仅2条原生日线验证。
> `licensed_parquet_to_native_h5_mapping_certified=false`、
> `ready_for_full_market_mirror=false`、
> `ready_to_modify_parquet_primary_source=false` 均保持不变。
> **这项归档已完成，无须再次扫描原始市场文件或重复执行五SAFE聚合。**


## 本轮Windows真实验收与结论边界

用户已在Windows运行第151轮修复后的**10项合成键定位+跨年读取回归，全部OK（4.655秒）**。实际只读的`real-h5-parquet-crossyear-day-factors-keylocated-20250930-20260824-v2.json`显示：

| 真实目标日期 | 股票日线配对 | H5 raw volume×100 与 Parquet | H5 raw amount×1000 与 Parquet | OHLC raw整数÷1000 与 Parquet |
|---|---:|---:|---:|---:|
| 2025-09-30 | 2 | 2/2 | 2/2 | 四字段各2/2 |
| 2026-08-24 | 2 | 2/2 | 2/2 | 四字段各2/2 |
| 2026-09-28、29 | 4 | 4/4 | 4/4 | 四字段各4/4 |
| 2026-09-30 | 2 | 2/2 | 2/2 | 四字段各2/2 |
| **总计** | **10** | **10/10** | **10/10** | **四字段各10/10** |

注：四个跨年新样本的成交量及成交额正数非零配对均4/4；2026-09同月留出日也4/4正数非零，2026-09-30发现日已有2/2真正的倍率配对。所有价格/成交量/成交额匹配遵守此前有容差的数值诊断契约，**并非每个源文件逐字节或float64无误差相等**。

2025年度2025-09-30因其年文件1,333,385行/12组的所有Footer时间范围都重叠，之前的日期剪枝无法选组。第149轮键列扫描定位两只股票同日到**1组共123,139行**，第150/151轮真实跨年程序重新只读**1,333,385条`ts/symbol`键、解码123,139行OHLCVA**，加2026-08月文件后合计OHLCVA扫描241,108行/3组。跨年SAFE记录原始源未修改（仅stat/Footer检查，并非整份数据SHA256）。

**极重要的区分：**
- 2026-09-30的2条真实H5 KRecord，已单独经Hikyuu **2.8.1原生C++读取**及HMAC验证raw H5整数↔native KRecord 2/2；其他8条只有raw H5整数↔购买Parquet候选倍率，并**未逐条执行原生C++**。
- 从该两条native已验证样本可推得上述Parquet/native KRecord候选倍率约为价格1、量100、额10000，但并不证明供应商“股/手/元/万元”的**物理单位来源**，不证明复权、全部时间边界、全部证券或5min/1min均符合倍率。
- 仓库中已明确的主线是：**购买Parquet优先，原始H5仅补真实缺失交易日，形成独立可回滚的统一Parquet，然后开发真实Hikyuu原生H5镜像，后续通达信盘后数据只更新Parquet一次。** 历史分钟线细微差异的机理研究已经根据用户既定决定暂停。详见`2026_PARQUET_PRIMARY_EXECUTION_PLAN.md`。

## 本轮新增离线门禁

新工具：`tools/audit-parquet-primary-day-crossyear-factor-evidence-offline.py`。**只接受**模块`reports/`内五份既有脱敏SAFE：

1. 2026-09-30真实Parquet↔raw H5两股发现日报告。
2. 同日Hikyuu2.8.1 C++原生KRecord真实读取2/2 HMAC报告。
3. 2026-09-28/29真实H5↔Parquet留出4/4报告。
4. 2025年度仅键列目标定位，扫描1,333,385键行/1目标组123,139行的报告。
5. 2025-09-30与2026-08-24跨年数值验收4/4报告。

它复用原各SAFE验证器，要求来源链SHA256完全匹配、所有正数命中及4个价格字段每日期完整、6种倍率网格无歧义、无零值伪证据、扫描预算/行组计数守恒、源未修改、无生产写入或授权旗标。任一条证据被更改、替换或误写为“认证了供应商物理单位”，**立即拒绝**。不会读取任何原始H5/Parquet、Hikyuu C++、SQLite、K线值或用户真实市场源路径。

仅在通过时创建一个**新**`reports/`安全JSON，保留五份输入SAFE内容SHA256和样本计数，所有物理单位、分钟周期、生产H5镜像、Parquet主库正式修改权限一直是false。**该工具不会自行生成H5、Parquet或激活private active指针。**

## Windows PowerShell：每条命令一整行

更新仓库：

```powershell
git pull --ff-only origin main
```

运行新增**8项纯JSON离线测试**：

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_audit_parquet_primary_day_crossyear_factor_evidence_offline.py" -v
```

检查目标报告不存在：

```powershell
Test-Path "H5ParquetReconciler\\reports\\parquet-primary-day-crossyear-10-stockday-factor-evidence-v1.json"
```

只有8项`OK`、目标不存在时，执行一次**完全离线**的五份SAFE聚合，不扫描市场数据：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\audit-parquet-primary-day-crossyear-factor-evidence-offline.py --raw-safe "H5ParquetReconciler\\reports\\real-parquet-h5-raw-day-unit-factor-candidates-20260930-v1.json" --native-safe "H5ParquetReconciler\\reports\\real-hikyuu-native-20260930-hmac-v3.json" --heldout-safe "H5ParquetReconciler\\reports\\real-h5-parquet-heldout-day-factors-20260928-29-v1.json" --key-safe "H5ParquetReconciler\\reports\\real-2025-annual-parquet-day-keyonly-20250930-v1.json" --crossyear-safe "H5ParquetReconciler\\reports\\real-h5-parquet-crossyear-day-factors-keylocated-20250930-20260824-v2.json" --out "H5ParquetReconciler\\reports\\parquet-primary-day-crossyear-10-stockday-factor-evidence-v1.json" --offline-day-factor-evidence-only
```

上传输出的新SAFE和8项测试结果即可。**无需再次全扫描133万条年度键、更无需上传或修改用户原始商业文件。**

## 下一步与不可跨越的边界

- 完成这一小样本研究的**严格归档**，作为未来Hikyuu原生镜像的日线**候选数值因子**，不得因10/10自动判定全市场，待供应商字段字典/生产行数范围/历史时间标签/复权独立认证。
- 沿既定主线研究既有**4日合计22,191行的私有日线overlay版本**的安全只读消费，与Hikyuu原生H5**完全虚构样本**的转换闭环，随后独立分区的可回滚镜像试点。绝不覆盖`D:\\stock\\HikyuuData`或原始购买Parquet。
- 按用户原决定暂停历史五分钟细微差异机理研究；如未来需对5min/1min做产品级映射，须独立定义时标、单位及完整性门禁，不把日线10条直接当成分钟线授权。
