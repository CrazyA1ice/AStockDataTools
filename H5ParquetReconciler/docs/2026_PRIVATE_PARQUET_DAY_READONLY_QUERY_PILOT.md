# 2026-10-29：四日22,191根实测成功，推进显式版本的只读日线统一查询

## 真实本地证据（用户Windows回传）

2026-09-01～10-28日线只读审计原已证明：H5-only 22,191 根全部位于购买Parquet整日缺失的4个交易日。2026-10-08已暂存5,546根。本轮实际执行三条隔离stage：

| 日期 | 用户命令返回 | 私有Parquet SHA-256 |
| --- | ---: | --- |
| 2026-10-08 | 5,546 | 详见先前验收的独立manifest |
| 2026-10-09 | 5,547 | `2e12aa9cbb6b7bc31c4fd0df830d8adc07404d8c908d6e5612cd692a58ee9abb` |
| 2026-10-12 | 5,549 | `a8bc56392080143ea7eb398f14c67fddcaa2dad1a09e452020632c45553f5a06` |
| 2026-10-13 | 5,549 | `5d7e7c03c85d0373da4138d7c96a7b1ee6ffd3281e829b877b6d169fde24448b` |

四日 `build-parquet-primary-day-overlay.py --action prepare` **实际成功返回**：
- `prepared_days = ["2026-10-08","2026-10-09","2026-10-12","2026-10-13"]`
- `private_rows = 22191`
- `version_sha256 = 46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03`
- `production_query_route_modified = false`
- `status = prepared_private_day_overlay_not_production`

以上来自用户终端执行回传，不代表GitHub服务端已读取/独立重算其本地商业行情哈希。既有两组 Windows 合成测试 7/7 + 11/11 全通过。**未执行活动指针激活，正式行情库、H5镜像、10-14之后的盘后数据仍未补齐。**

## 本轮新增代码：显式版本只读日线查询（测试待Windows运行）

`tools/query-parquet-primary-day-overlay-readonly.py` 是**研究版**查询入口，与既有 `query-parquet-primary-readonly.py` 独立，现有默认只读查询、分钟线和cache接口均保持原样。

- 仅支持 `day`、规范A股证券代码、1～31天日期窗和既有的有界市场源行预算；**必须明确**传入不可变私有版本 SHA。绝不自动读取 `active-day-overlay.json`。
- 对所选版本全部stage重新验证版本SHA、报告SHA、每个stage清单与Parquet字节哈希、行数、日期、市场/唯一键；不信任用户编辑后的路径或元数据。
- 对查询涉及的每一个已暂存缺失日，运行**现场完整证券日缺失核对**（Parquet仍无该日记录、H5条数仍相等），并检查源文件的大小与mtime前后稳定；如果购买Parquet后来到货，新加了任何当天记录，拒绝过期版本，**不做默默混合**。
- 通过既有 `query_bars()` 读取原始购买Parquet，禁用私有OHLCVA缓存，叠加仅来自该已审计完整缺失日期的私有H5候选日线；严格禁止同日同股票重复或超结果上限。
- 只向模块 `reports/` 写入新的**安全统计JSON**，仅含计数、来源与版本SHA，没有逐条OHLCVA；实际数据只在本地内存API返回，需 `--show-first-bars` 明确选择才打印不超过10条至本机终端。
- H5日线价格÷1000、成交量×100、成交额×1000仍只是候选量纲，**不视作供应商认证**。分钟线没有被补齐，也不改H5镜像。
- 真实对账需要重新扫描被查询的H5-only整日，即使查询一只股票，也可能有较高本地I/O；这是第一版的可验证性优先设计，不作“高性能生产版”承诺。

## Windows执行（仓库根目录）

先更新：

```powershell
git pull --ff-only origin main
```

先执行独立合成回归（预期8项，**实际结果待用户回传**）：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_query_parquet_primary_day_overlay_readonly.py" -v
```

再进行真实单股票有界只读试点（调用用户本机已准备的版本，不需要也不应该 `activate`）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-primary-day-overlay-readonly.py "D:\stock" --symbol SH600000 --from-date 2026-09-30 --to-date 2026-10-13 --version-sha256 "46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03" --max-candidate-rows 30000000 --max-result-bars 50 --max-overlay-source-rows 30000 --out "reports\private-day-query-SH600000-20260930-20261013-v1.json" --read-only
```

执行成功应生成 `H5ParquetReconciler/reports/private-day-query-SH600000-20260930-20261013-v1.json` 的**不含付费原始K线的统计摘要**，其中 `private_overlay_dates_live_rechecked` 应有4天，`private_overlay_bars_returned` 应根据该股是否在各日有H5数据而确定，不能凭空预设每一天一定交易。 `--show-first-bars` 默认0，不输出价格。若已有同名输出文件，更换v2等新名字，禁止覆盖旧证据。

**后续路线**：核验真实安全摘要和运行代价 → 再考虑独立激活私有指针的消费协议 → 构建完整安全统一 Parquet 更新与 Hikyuu 原生镜像 → 接入确有源数据的通达信盘后。不能把本试验入口称为生产主库，不允许覆盖 `D:\stock` 原件或上传私有stage中的付费Parquet。
