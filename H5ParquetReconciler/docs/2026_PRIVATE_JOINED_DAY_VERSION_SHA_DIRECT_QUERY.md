# 2026-10-30：用不可变逻辑版本SHA直接查询私有日线，不再手动传父与delta

## 前置实测

用户Windows `test_register_private_joined_day_logical_version.py` **14/14 OK（16.928秒）**，已将真实私有父Parquet10条+新增SH600519增量5条登记为一个**独立的不可变逻辑版本**：

`bfedbb6b1f538a2a1ec73bb2bc02233290ebdccfc734ba33caa4ff42e2acdf14`

登记统计为3只股票/15条日线，**购买Parquet3条、已核实整日缺口的原H5候选12条**。记录中的`previous_joined_version_sha256=null`、`private_joined_pointer_changed=false`；随后`status`的`active_joined_version_sha256=null`、`original_market_files_accessed=false`、`production_query_route_modified=false`。PR #162已合并main（`071fec877`）。

## 本轮工具

`tools/query-private-joined-day-by-version-sha-readonly.py`提供`query_version(sha,symbols,first,last,out)`本地Python接口和相应CLI：

1. 使用**显式不可变逻辑版本SHA**读取`work/unified_parquet/joined_day_versions/<sha>.json`。强制验证版本文档内容SHA、登记时父版本/增量关系和实际私有物理Parquet、manifest、SAFE SHA，整份检查父10根与delta5根的Schema、来源计数、股票日唯一键、时间戳与OHLCVA合法性。
2. 自动从版本记录定位所需的父版本、delta SAFE。复用`read-private-day-snapshot-with-symbol-delta.py`既有读取器，以`emit_safe=False`在**本机内存**读取、过滤，避免在查阅半途写出中间SAFE。前后再次检查版本文件及双方Parquet源SHA、同时拒绝并发版本登记锁出现。
3. 调用者必须明确指定1～10只股票和日期窗口，范围不得超出该逻辑版本。完整数据经过验证之后才按条件筛选。不支持默认活动指针；**不会读取/激活**`active-private-joined-day.json`、`active-private-snapshot.json`、`active-day-overlay.json`。
4. 只在`H5ParquetReconciler/reports/`下创建全新的**脱敏统计SAFE JSON**，不写入任何付费真实市场价格、成交额、成交量、单股行情或股票代码。含逻辑版本SHA、版本文件SHA、两套Parquet的SHA、来源根数、当前查询筛选根数、来源状态声明。
5. Python函数返回`bars_by_symbol`仅供**用户自己的本机进程内处理**，不得未经授权打印、缓存到公开报告或提交GitHub；CLI不会打印真实OHLCVA。
6. 原购买Parquet及Hikyuu原H5这次**不会打开、不被修改**，也不查询最新市场、也不改任何生产接口。因此这是对历史私有快照版本的**可复现访问**，不是2026年10月30日真实市场行情最新状态证明。
7. H5候选量纲未认证（12条），旧2股票金额0/2原始H5整数无损映射尚未解决。**不能**据此开始真实原生H5镜像、替换购买数据或任何交易生产任务。

新增**16项纯虚构数据合成测试**：通过已建立的真实PyArrow临时父+增量物理文件创建逻辑版本，验证整体查询、只查询新增股票、原始文件不改、版本/父/增量损坏拒绝、伪造来源SAFE、日期代码越界、活跃指针绝不访问、并发锁、运行过程中版本被改、错误SAFE不发布、外部路径与已有报告不覆盖。**本轮尚未经过Windows验收，因此PR保持Draft。**

## Windows单行命令：合成测试过关才读取真实15条私有日线

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-joined-day-version-sha-query-20261030; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/private-joined-day-version-sha-query-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_query_private_joined_day_by_version_sha_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "16项合成测试失败，停止真实私有逻辑版本读取" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\private-logical-sha-read-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-private-joined-day-by-version-sha-readonly.py --logical-version "bfedbb6b1f538a2a1ec73bb2bc02233290ebdccfc734ba33caa4ff42e2acdf14" --symbols SH600000 SZ000001 SH600519 --from-date 2026-09-30 --to-date 2026-10-13 --out $out --explicit-private-version-read; if ($LASTEXITCODE -ne 0) { throw "真实15条私有逻辑版本SHA直接查询失败" }; Write-Host "脱敏查询SAFE：$out"
```

验收时仅上传终端摘要和新SAFE统计JSON，不上传真实日线`day.parquet`、购买Parquet、H5或其他商业行情原始记录。测试若不通过整行命令会中止，不会接触真实私有物化数据。

## 后续主线

显式SHA查询稳定后，再专门为`day`构建**新增交易日**真实物理分区：先根据数据源实际到货日历获取实证、购买Parquet为主，在真实整股票日购买数据不存在时才允许已独立审计的原H5补齐；需要独立来源SHA及源更新时间约束，不能直接从现有10月8/9/12/13缺日证据推演10月14日以后的数据。扩大规模时再做日期/股票分区索引、异步/有界增量性能。原生H5需要进一步确认金额真实物理单位和整数转换策略；当前生产源绝不改。
