# 2026-10-27：Parquet主源重复查询性能改进——显式私有本地缓存（冷/热对照）

## 真实查询依据

用户上传 `pq-primary-query-SH600000-5min-2026-09-30-v2.json`：
- 目标证券：SH600000；原Parquet五分钟线；2026-09-30；`matching_bar_count=48`，源时间标签09:30～14:55；
- 2026年9份月文件Footer均打开，8份有足够Footer证据证明与目标交易日不重叠，只有2026-09.parquet参与进一步规划；`month_filename_disagrees_with_footer_query_range=0`；
- **仍需读取47个RowGroup、5,685,792条源行情记录**，查询放大`source_rows_read_per_returned_bar=118454.0`。此前V1同样是47组/5,685,792条，所以PR#60只优化元数据规划，不能宣传已加速真实源行解码。安全回执未含付费OHLCVA、未访问H5、未修改源或做数量单位转换。

这说明月文件选择已够准确，长期真正问题是源Parquet同月内行组非常大、单股票单日的记录在多个源行组交错，行组时间范围不能精确剔除。**不能通过简单的PyArrow行级过滤声称会降低解码行数；需要实际不同实现的冷查询基准。**

## 本轮交付：只有用户明确启用才保存付费行情私有缓存

新增`tools/private-parquet-query-cache.py`，更新`tools/query-parquet-primary-readonly.py`：

1. **默认关闭**：与现有`query_bars(...)`和CLI旧命令完全兼容；不加`--local-cache`就不会创建或读取K线私有缓存，始终只读Parquet源。
2. 用户显式`--local-cache`或Python`query_bars(...,local_cache=True)`后，第一次无缓存仍走原始、完整的**RowGroup→六字段OHLCVA**安全读取与源值合法性校验、重复键拒绝、行组读数预算，最多允许一个单次缓存16MiB；首次读取**不会因为启用缓存减少569万源行**。
3. 首次读后，只在本模块已有被Git忽略的`H5ParquetReconciler/work/primary_query_cache/`存储请求范围内的**真实购买OHLCVA子集**，同一目录内临时写入再原子替换，防止半截JSON缓存。该私有文件**包含付费行情，不能上传GitHub、公共网盘或发送给助手作为安全报告**；不能误称“缓存没有OHLCVA”——只有CLI写入`reports/`的safe summary不含价量额。
4. 后续同参数请求首先仅枚举相关年份、周期Parquet**源文件清单+文件大小+mtime纳秒**，匹配上次快照才复用缓存；再次查询零Parquet K线行、零Footer读取，返回与冷查询相同的原始数据及source文件/行组溯源字段。源文件新增/删除、大小或mtime变动、请求日期/证券/周期/安全预算变化，缓存失效并重新从Parquet读取；缓存JSON破损会重新构建，不会给出伪造的完整结果。
5. 上述判定是**stat-based身份校验，不是50GiB源包内容SHA256**，无法识别同大小且mtime被强制回填的内容修改；在涉及高安全、合规用途或敏感源更改时，应额外采用真实文件哈希/来源版本校验。
6. CLI在`reports/`生成两个互不覆盖的新**安全元数据JSON**；新增`query_delivery`（`parquet_source_scan`或`local_private_cache_hit`）、`local_cache_used`、`source_rows_scanned_this_invocation`、`source_file_footers_opened_this_invocation`、`query_elapsed_seconds_this_invocation`。命中缓存后`source_rows_scanned=0`，之前冷查询的行数单独保存在`previous_source_rows_scanned_to_build_cache`，避免“引用旧扫描统计误称本次又解码大量行情”。
7. 缓存内的源数值全部只在本机，CLI依然默认不打印真实OHLCVA；仅显式`--show-first-bars N`才在**本机终端**显示最多10根。缓存是**重复请求的优化**，不改善从未查询过的新股票/新日期的首次查询成本，也不能用缓存代替证券日完整性/复权认证或TDX增量来源核验。

## Windows两次相同查询：测实际冷/热性能

先更新并运行全部合成测试：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

首次启用私有缓存（**会在本机work目录生成含付费OHLCVA的缓存**）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-primary-readonly.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --read-only --local-cache --out "reports\pq-primary-SH600000-20260930-cache-cold.json"
```

再执行同样请求，不覆盖第一个报告：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-primary-readonly.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --read-only --local-cache --out "reports\pq-primary-SH600000-20260930-cache-warm.json"
```

比较`matching_bar_count`都应是48；冷查询`local_cache_used=false`且实际读取源行可能仍5,685,792；第二次如果文件stat没变则应`local_cache_used=true`、`source_rows_scanned_this_invocation=0`、`source_file_footers_opened_this_invocation=0`，实际秒数请以两份JSON的`query_elapsed_seconds_this_invocation`为准，**不要编造具体加速倍数**。不想本机留存付费子集时，不加`--local-cache`即可，已创建的本地私有缓存可手动清除`H5ParquetReconciler/work/primary_query_cache/`，不会触碰源Parquet。报告文件仍只在本模块`reports/`内。

新增**5项合成Arrow回归测试**覆盖冷缓存→热缓存零值读取、stat失效、默认关闭、不同安全预算不绕过、缓存损坏重算；前271项推算新总数约**276项**。本轮代码尚未在用户Windows环境实际运行；用户需提供新安全报告确认。

## 后续瓶颈

缓存不能解决**首次查询**的约569万源行解码。下一性能阶段优先在有限时间预算下基准测试Arrow/DuckDB过滤与列选择、月文件Parquet行组排列规律，决定是否有必要只为经常访问的股票和日期额外保留小型增量索引或备份K线。仍禁止复制整套50GiB历史源、未经验证合并源量额或将本地付费缓存推送GitHub。

TDX盘后数据仍计划进入**独立可回滚新增层**，不是直接覆盖购买的2011-2026.09 Parquet历史主源。H5只用于证实缺口后的参考补充。
