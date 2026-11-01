# 日线Parquet→Hikyuu布局H5：实际隔离写出最短操作（2026-11-01）

上一轮25项安全测试和真实3次读取全PASS，不重跑，也不再写索引/指针/性能测试。本轮首次直接**从已验收16年私有Parquet SHA版本选8条真实购买日线，写出新的H5文件并全部回读**。真正的写入动作是`tools/write-private-parquet-day-to-hikyuu-h5-canary.py`，其余只做3项必须的写出安全测试。

只写模块`work/h5_mirror/canaries/day_canary_<id>.h5`及`reports/parquet-to-hikyuu-day-real-write-<id>.json`；无购买原件/原H5改写。H5表结构为`/data/SH600000`固定Hikyuu整数compound列，价格×1000、成交量÷100、成交额÷1000（**待通过真实源字段文档确认**）。对每个实际Float64值做整数化和反算；SAFE会把**每个字段不可无损表示的条数和最大绝对误差**明确写出，不能只因H5读取成功就宣称两套数值完全一致。已使用h5py读取文件中全部复合整数记录；`hikyuu_cpp_native_reader_verified=false`表示**尚未证明真实Hikyuu C++能打开**，也没有生成完整市场H5，因此是实际写盘的隔离金丝雀，不是最终双向同步完成。

这条命令在Windows项目根目录一行执行：

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\write-private-parquet-day-to-hikyuu-h5-canary.py H5ParquetReconciler\tests\test_write_private_parquet_day_to_hikyuu_h5_canary.py; if ($LASTEXITCODE -ne 0) { throw "H5写出代码语法失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_write_private_parquet_day_to_hikyuu_h5_canary.py" -v; if ($LASTEXITCODE -ne 0) { throw "3项原生H5实际写入测试未通过" }; $v="H5ParquetReconciler\reports\private-2011-2026-all16-sha-bound-version-15fb74d42d0b.json"; $sha="bd64abcd0580cbed404c31bc2db3a05f9b2411880fa24d6bf3b14ecabcdb0c05"; if (-not (Test-Path -LiteralPath $v) -or (Get-FileHash -LiteralPath $v -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sha) { throw "16年已验日线版本SHA错误" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\parquet-to-hikyuu-day-real-write-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\write-private-parquet-day-to-hikyuu-h5-canary.py --version-safe $v --version-sha256 $sha --symbol SH600000 --start 2025-12-29 --end 2026-01-09 --run-id $rid --out $out --write-isolated-h5-canary; if ($LASTEXITCODE -ne 0) { throw "真实Parquet到H5独立写出失败，不触碰原件" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; $h=Join-Path "H5ParquetReconciler" $r.private_h5_relative_file; if ($r.status -ne "isolated_native_layout_day_h5_written_and_h5py_readback_verified_not_activated" -or $r.source_day_rows -ne 8 -or $r.written_h5_integer_rows -ne 8 -or $r.h5py_compound_integer_full_row_readback_verified -ne $true -or $r.original_market_files_written -ne $false -or $r.hikyuu_cpp_native_reader_verified -ne $false -or $r.ready_for_full_market_mirror -ne $false -or -not (Test-Path -LiteralPath $h) -or (Get-FileHash -LiteralPath $h -Algorithm SHA256).Hash.ToLowerInvariant() -ne $r.private_h5_file_sha256) { throw "真实H5候选文件与SAFE验收不符" }; Write-Host "PASS：真实8条购买Parquet日线写入隔离Hikyuu布局H5并逐条回读"; Write-Host "原值是否6字段均可无损表示：$($r.all_six_fields_exactly_representable_in_h5)"; Write-Host "各字段变化行数：$($r.h5_fixedpoint_source_value_changed_field_counts | ConvertTo-Json -Compress)"; Write-Host "H5：$h"; Write-Host "SAFE：$out"
```

如果3项写出测试PASS和真实8条H5生成/回读PASS，立即执行**原生Hikyuu读取**与字段可表示性处理，并把单股票写出器扩展为按交易所/证券流式构建整个日线H5；不要继续做无关的索引、版本指针或十几项性能测试。若`all_six_fields_exactly_representable_in_h5=false`，不可把整数H5的经舍入值冒充Parquet Float64原值，需要在来源允许的H5精度下指定容差，明确原值与目标整数反算后的偏差，达不到用户要求时不能宣传完全相同。

然后以同一Parquet优先/只填确实缺失键的方法开发1min和5min新Parquet分区、镜像H5并做三周期覆盖/数值等价校验，最后通达信盘后增量一次写Parquet和同步H5。全部最终目标见[唯一主线计划](MAINLINE_PARQUET_H5_TDX_20261101.md)。


## Windows实测异常及无额外性能测试的修复路径（2026-11-01）

用户实际运行新增写出工具的3/3项合成测试PASS，但进入8条真实购买Parquet→独立H5操作后返回`Isolated DAY H5 write refused; sources remain unchanged`；早期CLI把原始异常全部隐藏，**尚不能证明真实H5已写出，也不能推断源行情有问题**。本次直接修复失败诊断：仅输出固定阶段、异常类型及触发的函数/行号，允许的安全错误消息白名单；不打印任何OHLCVA、股票代码、原始文件路径或单条记录。源代码提交`604a1eb995cc24a5cd69946d210cd365a54a403f`。

下一次只需要`git pull --ff-only`、`py_compile`和用**新的12位ID**重试真实8条H5隔离写出；前面3项合成测试已经通过，不需要重复跑25项其他查询回归。失败请记录CLI方括号内的`阶段/异常类/触发函数:行号/安全错误`，不要上传真实H5或单条付费价量。成功后立即继续Hikyuu原生C++实际读取及全日线批量镜像，而不是继续增加计划/版本/索引。
