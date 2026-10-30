# 2026-10-31：历史原始H5 7条日线经Hikyuu 2.8.1 C++原生驱动HMAC隔离复核

## 前置真实验收

用户Windows已通过PR #178的7/7合成测试（6.054s），并实际对1992/1993/1995年的7个历史市场×季度×数值候选目标进行只读原始H5整数与私有RAW逐值比对（7/7）。本地历史资格SAFE：`H5ParquetReconciler/reports/pre2011-historical-native-targets-5722d4b95498.json`，其私有选择清单SHA为 `5745319e7d33f0b8e5ba82d065d27d89c8140cbbd7b3d61a96a73235f8bf1027`。源RAW完整版全21年旧SAFE仍为`reports/pre2011-full21-verify-9bba81ed3c33.json`。PR #178合并到main为`fbbda26d26f6c7483e3cc7363703923f7ed8c35f`。

## 本轮：隔离原生C++读取（不生成新H5）

`tools/verify-pre2011-historical-h5-native-core311-isolated.py`：

1. 先认证既有FULL21 SHA + 7条历史资格SAFE + 私有坐标清单SHA。重新核对21个私有RAW Parquet文件SHA，重新读1992/1993/1995年选定目标，重新从原始`sh_day.h5`、`sz_day.h5`中按精确交易日二分定位，并核对全部原生整数与私有RAW完全一致。旧报告不是实时所有原源全量再审计。
2. 父进程使用随机一次性HMAC密钥，根据这7条私有RAW计算预期HMAC。仅将随机密钥通过子进程环境变量传递；不会在命令行、文件、SAFE中写入该密钥或单条OHLCVA。
3. 隔离子进程使用**唯一指定**的CPython3.11和已安装Hikyuu 2.8.1的编译`core311`，不调用`hikyuu_init()`，不读取真实生产`stock.db`，而在模块`work/h5_mirror/historical_native_isolated/run_<run-id>/`新建**虚构股票注册SQLite**。原H5文件以原路径传给HDF5驱动。股票注册日期1990-01-01至2099-12-31，避免用2026年的起始日期过滤掉1992年记录。
4. 子进程必须先验证历史H5股票数据集原生条数与真实原H5只读资格清单相同。每个目标调用`Query(source_native_stock_index, source_native_stock_index+1, DAY)`，严格要求**恰好返回一根KRecord**且日期等于资格清单标注的历史日键；七条合计最多请求七根DAY KRecord。绝不改成旧方案的`Query(-64,DAY)`末尾窗口，不允许绕过日期/计数门禁扩大扫描。
5. 每个KRecord只在子进程内逆算历史H5原生整数（已知Hikyuu原生H5解码价格×0.001、金额×0.1、数量×1；这不是购买Parquet的单位），生成HMAC并回传临时stdout。父进程只对照HMAC，不存储摘要、价格、成交量或成交额。超时/崩溃/少日线/摘要不一致全部标记未通过；C++ stderr及私有日志不会进入SAFE。
6. 原始H5前后stats、私有选择清单SHA均不变。SAFE仅包含7条是否全部匹配、总匹配数、无原始数据修改和认证仍为false等。不会创建历史标准化Parquet、不会生成原生H5镜像、不会改生产路由或active。

## 注意

历史原H5驱动数值完整匹配，**也不代表**供应商购买Parquet的`volume`是股还是手、`amount`是元还是万元、是否复权或合法历史证券身份。所有历史数据正式统一转换都需要供应商字典及独立历史交叉证据。原始H5这轮只读定位7条并在子进程内用C++ HDF5驱动读取，**没有**在本轮重新计算整份H5 SHA256；源stat只验证文件大小/mtime无变化。请确保原始行情已有备份，不上传真实H5/商业Parquet/私有选择清单。

## Windows PowerShell（每条命令一整行，只有测试通过后再跑真实原生驱动）

**第一步：** 拉开发分支，Python编译检查+8项合成回归，任何失败都停止：

    cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/pre2011-isolated-native-h5-hmac-seven-20261031; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/pre2011-isolated-native-h5-hmac-seven-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\verify-pre2011-historical-h5-native-core311-isolated.py H5ParquetReconciler\tests\test_verify_pre2011_historical_h5_native_core311_isolated.py; if ($LASTEXITCODE -ne 0) { throw "历史原生H5脚本语法检查失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_verify_pre2011_historical_h5_native_core311_isolated.py" -v; if ($LASTEXITCODE -ne 0) { throw "8项隔离原生测试失败，停止任何真实H5读取" }; Write-Host "8项历史H5隔离HMAC合成测试全部通过"

**第二步：** 在第一步全部通过后，只读调用隔离CPython3.11/Hikyuu2.8.1处理7条历史样本，超时60秒（退出时检查SAFE必须7/7成功，否则不要继续）：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\pre2011-historical-native-core311-hmac-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\verify-pre2011-historical-h5-native-core311-isolated.py --root "D:\stock" --full21-safe "H5ParquetReconciler\reports\pre2011-full21-verify-9bba81ed3c33.json" --historical-qualification-safe "H5ParquetReconciler\reports\pre2011-historical-native-targets-5722d4b95498.json" --python-exe "D:\software\Python311\python.exe" --run-id $rid --timeout 60 --out $out --isolated-historical-native-seven; if ($LASTEXITCODE -ne 0) { throw "7条历史H5原生隔离核验执行失败" }; $r=Get-Content $out -Raw | ConvertFrom-Json; if ($r.native_status -ne "native_complete" -or $r.native_matching_h5_historical_stock_days -ne 7 -or $r.all_seven_native_h5_historical_records_match -ne $true -or $r.original_h5_source_stat_unchanged -ne $true -or $r.source_h5_or_purchased_parquet_modified -ne $false -or $r.historical_vendor_physical_units_or_adjustments_certified -ne $false -or $r.production_or_private_active_pointer_modified -ne $false -or $r.ready_for_production_data_integration -ne $false) { Write-Host "原生结果未通过，保留SAFE以供定位：$out"; throw "真实7条Hikyuu历史原生HMAC门禁未通过，绝不进行标准化" }; Write-Host "历史Hikyuu C++原生7/7匹配；SAFE：$out"

只需发回测试日志和新SAFE报告。如果子进程出现`native_timeout`/`native_count_mismatch`/`native_target_day_mismatch`，保持失败报告和原始文件不变，不要修改原始stock.db、H5数据或扩大查询范围。PR在Windows验证前保持Draft。
