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

## SH600000真实只读试点验收与统计口径修正（2026-10-29）

用户Windows新回传8项合成测试逐项均为`ok`，终端截取末行为`Ran 8 tests in 6.183s`，未见最终`OK`或退出码；**只记录为逐项通过，不推断完整退出状态**。

用户上传`private-day-query-SH600000-20260930-20261013-v1.json`实际证明：

- 显式SHA等于已准备四日版本`46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03`；基础购买数据返回1根、私有缺口返回4根、合计5根；
- 四个缺失日期均现场重审、全部私有stage的SHA和证券键重验成功；未执行任何正式路由切换、未修改原来源。
- 购买Parquet只找到1个候选RowGroup，读取28,191源行，开了9个源文件footer（8个由footer证明不相关后跳过）；查询日期是2026-09-30～10-13。
- **旧统计口径有两处错误**：源行/返回bar比值`28191.0`沿用了购买Parquet单根数据的比例，不能直接解释为组合返回5根后的整体放大比；`query_elapsed_seconds_this_invocation=0.568659`只计购买Parquet查询，不包含私有4日的现场来源复核、全部4日私有stage键读取和私有bar解码。

为修正这一统计边界，后续v2及以上safe报告分别输出：

- `purchased_parquet_source_rows_scanned`、`purchased_parquet_source_rows_per_purchased_bar`：仅购买Parquet来源的扫描成本和其自身bar分母；
- `private_stage_key_rows_decoded_during_version_verification`：校验**全部已准备日期**的stage键数，本版本为22,191，即使查询窗没覆盖私有日期也需要这一步；
- `private_stage_rows_decoded_for_selected_dates`：本查询窗选中日期的完整暂存数据解码行数，4日共22,191；
- `known_minimum_purchased_plus_stage_rows_decoded`：上述三类确定执行过的行级读取次数之和，**实际本次至少28,191+22,191+22,191=72,573**，不包括现场H5+购买PQ整日差集审计的额外读取、文件哈希字节I/O或底层Arrow物理IO；不是统一数据库的实际逐字节I/O；
- `known_minimum_rows_per_combined_returned_bar`：仅此最低已知解码量/最终返回bar数，本次若重跑相同源文件与日期应为72,573/5=14,514.6；`source_rows_read_per_returned_bar`主动置`null`，避免将购买Parquet自身单根比例误认为综合比例；
- `purchased_query_elapsed_seconds_this_invocation`保留购买接口原测时，`query_elapsed_seconds_this_invocation`调整为**完整统一查询方法调用**，新增独立的版本验证、现场复核、购买读取及私有阶段解码计时。整段时间才可用于后续真实性能对比。

以上是本轮代码修正，**未在Windows跑新的10项回归或v2真实报告**；不宣称新数值已有实测。原始`v1.json`是历史证据，必须保留原件，不改写重算它。

### 下一轮最小本机验收

仓库更新后在项目根目录执行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_query_parquet_primary_day_overlay_readonly.py" -v
```

新测试文件预期10项（8旧项+2项预算/空结果回归），如有任何失败，先处理失败，不改动源数据。全部通过后只跑相同的单股只读查询，**仅变更输出新文件名**防止覆盖旧报告：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-primary-day-overlay-readonly.py "D:\stock" --symbol SH600000 --from-date 2026-09-30 --to-date 2026-10-13 --version-sha256 "46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03" --max-candidate-rows 30000000 --max-result-bars 50 --max-overlay-source-rows 30000 --out "reports\private-day-query-SH600000-20260930-20261013-v2.json" --read-only
```

只回传新的SAFE报告与完整测试末尾`OK`或`$LASTEXITCODE`；不要上传真实商业OHLCVA或模块work目录内的`day.parquet`。

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
