# 2026-10-27：真实Parquet双顺序A/B已验证；启用显式Arrow查询预览（不切默认）

## 1. 三份来自用户本机的真实安全报告

由 `pq-cold-ab-rowgroup-first.json`、`pq-cold-ab-arrow-first.json` 和
`pq-cold-ab-comparison.json` 共同支持。实验为 `SH600000`、
`2026-09-30`、`5min`、仅48根，源文件stat清单 SHA256
`7b5152e56ef1139256cecc161a9319261f71db3b63d0a5d61cae82bff5549f48`，
涵盖9份Parquet清单文件。两次实验输入源stat指纹一致，且每一次实验中两引擎
**48根 OHLCVA 六项数值、原始时标、源文件路径及RowGroup均逐根完全一致**。

| 执行顺序 | 既有 ParquetFile RowGroup查询 | Arrow Dataset Fragment过滤 | 基线/Arrow |
|---|---:|---:|---:|
| `rowgroup-first` | 4.579644s | 1.425189s | 3.213359× |
| `arrow-first` | 1.925149s | 1.383294s | 1.391714× |

单次实验的 Arrow 全程耗时处于1.383–1.425秒，基线处于1.925–4.580秒。
因此结论只能是：**同一只股票、同一交易日的这两轮测试，Arrow在两种顺序下更快**。
第一轮观测3.21×，第二轮1.39×；后者是更保守的本次观测。第二次运行基线大幅缩短，
可能与文件系统/OS页缓存、顺序、系统负载有关，不能将差异完全归因于谓词下推。

47个候选RowGroup、元数据源行上限5,685,792，旧引擎向Python返回过滤前源行
5,685,792；Arrow只向Python返回满足条件的48条、涉及18个非空输出行组。
**Arrow实际物理解码源记录和磁盘IO字节均未知**，不得把48条过滤后输出当作物理
仅加载48条，也不能声称候选47组已经减少为18组。
数据源hash仅由清单、文件大小与mtime组成，**不是文件内容hash**；
OS冷页缓存与跨日期的稳定性尚未认证。

前一轮 Windows 本机 **298/298** 合成测试已 `OK`；
这三份真实A/B对上述具体证券日期成功，不构成全部证券/历史日期/三周期的生产验收。

## 2. 本轮代码：仅显式可选Arrow预览，不替换现有主查询

新增 `tools/query-parquet-arrow-preview-readonly.py`，复用**已经实测成功**
的 `benchmark-parquet-arrow-filter-cold.py::arrow_filtered_query`，
而不是复制维护一份不同的过滤逻辑：

- 使用相同 `prepare_query` 预检：最多31天、单只合法A股候选代码、
  Parquet RowGroup源行硬预算/结果数上限；无B股、无自动时间平移或量额换算。
- 读取Arrow Dataset按相同`ts`及`symbol`过滤，保留开高低收/成交量/金额六字段、
  原始时标、源文件与RowGroup信息；重复时间键、非法OHLCVA与不符合预算即拒绝。
- 调用前后检查源stat签名，变化即失败。默认**仅跑Arrow**；
  显式`--verify-rowgroup`同时运行原引擎，在内存严格比较完整结果；
  验证会增加耗时，不可用于单独宣称Arrow加速。
- 命令行**只保存新`reports/`中的聚合JSON**，不输出付费OHLCVA、不开启私有缓存、
  不写H5/Parquet/SQLite、不导入并集。Python `query_bars()` 返回的具体OHLCVA
  只在本机调用者内存里，禁止放进Git、工单或共享报告。
- 新增合成测试覆盖day/1min/5min精确比较、带空格路径、空证券结果、重复与预算、
  源stat发生变化时失败、比较对照差异时拒绝、CLI报告隐私和拒绝覆盖。
- **原有`query-parquet-primary-readonly.py`默认查询方式完全不变。**
  当前预览不能证明Arrow已符合全部旧引擎的生产语义；不改历史私有缓存、V3索引。

## 3. Windows 下一轮有限验收（从仓库根目录）

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

同样的真实样本，启用显式Arrow预览并要求原引擎逐根验证；
新生成文件与之前3份A/B分离，保留历史证据：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-arrow-preview-readonly.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --verify-rowgroup --read-only --out "reports\pq-primary-arrow-preview-SH600000-20260930-verified.json"
```

如果验收正确，改做**另外两类未测过的有限真实样本**，验证三周期的结果字段和原时标，
建议沿用已存在的真实数据日期2026-09-30：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-arrow-preview-readonly.py "D:\stock" --symbol SH600000 --period day --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --verify-rowgroup --read-only --out "reports\pq-primary-arrow-preview-SH600000-20260930-day.json"
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-arrow-preview-readonly.py "D:\stock" --symbol SH600000 --period 1min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --verify-rowgroup --read-only --out "reports\pq-primary-arrow-preview-SH600000-20260930-1min.json"
```

三个输出都只分享`H5ParquetReconciler/reports/`的聚合JSON。若目标文件已存在，换
`-v2.json` 等新名，**不能覆盖**。如果单日候选源行超过30M，预算保护将报错；
先分析原因，不提高上限直接批量扫描。若源缺失，`matching_bar_count=0`不能解释为认证
当天不开市。

## 4. 阶段性门槛

**已证明**：同一证券单日、两种实验顺序均更快，48根完全一致、源stat指纹一致。
**尚未证明**：跨股票、跨月份/年份、day与1min、冷缓存独立性、物理IO字节、
全历史无错、可默认替换生产引擎。因此下一步的评价依据应是多样本有限范围真实报告
与明确的成功/失败门槛，而不是继续编造冷查询的通用加速倍数。
