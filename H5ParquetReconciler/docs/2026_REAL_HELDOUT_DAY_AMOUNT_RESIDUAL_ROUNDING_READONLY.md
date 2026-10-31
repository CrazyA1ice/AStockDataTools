# 2026-10-31 四组真实留出日成交额原生整数残差复核（纯只读）

## 已验收前提（Windows真实日志）

- QDC购买day原Parquet与随包校验清单24/24文件SHA256、文件大小、footer行数匹配，总14,115,707行（PR #183已合并）；QDC随包说明声明amount单位为元，H5原生整数单位及取整规则尚无官方认证。
- 2026-09-30两组独立金额残差真实SAFE：reports/real-day-h5-amount-residual-20260930-b724d250f30e.json；2/2非零残差，均落在(0.01,0.1]个候选H5原生整数刻度且候选值低于H5整数。half-even与ceil均匹配2/2，floor 0/2：不能辨认唯一取整方式。
- 2026-09-28、29留出四组实际先前SAFE：reports/real-h5-parquet-heldout-day-factors-20260928-29-v1.json；4/4 amount候选raw-H5整数×1000相对容差匹配，4/4 volume候选×100，四个OHLC字段各4/4在容差内；金额4组均正值，尚未获得严格原生整数残差及取整假设对比。
- 以上只是已验收的之前工具；本次新增代码/测试尚未运行Windows真实验证。

## 新开发工具和安全边界

新增 tools/audit-real-heldout-pq-h5-amount-residual-readonly.py。先按指定文件核对这两份旧SAFE：数据日期、四组总数和两日期各自factor与正值计数、原9月30日的残差分桶和half-even/ceil/floor计数、无写入及所有转码认证false；计算输入SAFE全文SHA256。缺少/伪造报告立即拒绝，尚未接触原始市场文件。

仅访问原购买day/2026-09.parquet和两个H5原日线文件中的固定2026-09-28/29两股共4组。与旧工具相同的限量Reader最多跨两次300000条源行、每日期最多32行组；H5仅按日期二分读取指定股票的原生整数。重算旧4/4倍率汇总和两个日期的统计、扫描行组数，必须与旧SAFE完全一致，否则拒绝出新报告。保留原数据源的大小/mtime、Parquet footer及两份SAFE哈希前后不变的检查。

调用之前amount残差工具的纯函数统计候选金额(Parquet amount/1000)相对于H5 raw整数的严格匹配、是否需取整、偏差方向、固定粗分桶、half-even/floor/ceil匹配率、1e-5原有容差。额外统计候选情况下half-even与ceil或floor产生不同整数的样本数，以判断哪些样本能区分取整假设。**不是自动选择规则，也不会改写任意真实H5或Parquet**；SAFE仅包含总体和日期级计数以及既有SAFE SHA，不输出原价格、额、量、H5原整数、股票代码、具体行时标和市场源文件绝对路径。

所有真实来源字段的物理量纲和1990–2010历史H5转换、H5镜像以及生产数据路由许可仍保持false。即便4/4舍入候选匹配，也不等于Parquet float64可从原生H5整数无损恢复。不能以它授权正式镜像。

## Windows执行：所有PowerShell命令单行

1. 更新Draft PR分支并仅执行15项小型虚构Parquet/H5合成测试：

    cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/heldout-real-amount-residual-20261031; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/heldout-real-amount-residual-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\audit-real-heldout-pq-h5-amount-residual-readonly.py H5ParquetReconciler\tests\test_audit_real_heldout_pq_h5_amount_residual_readonly.py; if ($LASTEXITCODE -ne 0) { throw "语法检查失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_real_heldout_pq_h5_amount_residual_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "15项合成测试失败，禁止真实Parquet/H5读取" }; Write-Host "15项留出日成交额残差合成测试通过"

2. 第一条全部OK后，运行固定4组真实只读检查，生成全新模块reports/SAFE：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\heldout-real-day-amount-residual-20260928-29-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-real-heldout-pq-h5-amount-residual-readonly.py --purchased-root "D:\stock\AllCycleAStockData" --h5-root "D:\stock\HikyuuData" --heldout-safe "H5ParquetReconciler\reports\real-h5-parquet-heldout-day-factors-20260928-29-v1.json" --discovery-amount-safe "H5ParquetReconciler\reports\real-day-h5-amount-residual-20260930-b724d250f30e.json" --out $out --read-only-heldout-amount-residual; if ($LASTEXITCODE -ne 0) { throw "4组留出日金额残差真实只读失败" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.heldout_stock_days_compared -ne 4 -or $r.prior_heldout_factor_counts_reproduced -ne $true -or $r.ready_for_full_market_mirror -ne $false -or $r.lossless_native_h5_amount_conversion_certified -ne $false -or $r.source_parquet_h5_or_market_sqlite_written -ne $false) { throw "SAFE权限门禁异常" }; Write-Host "留出日金额残差SAFE：$out"

额外覆盖相对容差1e-5的包含边界（基数200000、偏差2刚好通过），以及偏差3大于容差的拒绝结果。

仅回传新SAFE统计和合成测试日志；不要传原商业Parquet/H5、数据库或真实价量额。真实测试通过之前PR保持Draft，不自行批准生产转换。
