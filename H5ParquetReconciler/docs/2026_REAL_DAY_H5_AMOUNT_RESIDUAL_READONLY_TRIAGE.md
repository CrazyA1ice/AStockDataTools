# 2026-10-30：只读定位真实日线Parquet→Hikyuu原生整数的成交额剩余偏差

## 已完成：用户Windows实测及已合并的PR #155

`test_audit_real_pq_to_native_h5_raw_exactness_readonly.py` **10/10 OK（6.874秒）**。真实报告：

`reports/real-pq-native-h5-raw-integer-exactness-20260930-6f7127713c96.json`

对于2026-09-30 SH600000、SZ000001，两股各一根：原Parquet扫描118208行/2行组、H5读取2根原始复合整数。OHLC四字段各2/2按价格×1000精确匹配真实原始H5整数，成交量按÷100为2/2，成交额按÷1000为**0/2**，两根都需要最短十进制整数刻度舍入。因此**旧10/10倍率容差匹配不能被升级为无损真实H5写入**。PR #155 已合并（`f6e7c0a`）。

已确认的合成Parquet→Hikyuu C++原生6/6通过只证明工具技术链；这次新诊断目标是已发现的**真实成交额局部阻碍**，不展开分钟残差研究。

## 新的金额残差，只读且不自动舍入

`tools/audit-real-pq-h5-amount-residual-readonly.py`

- 同时要求上轮经过Windows真实验收的**10股票日五SAFE汇总**及**同日原生整数精度SAFE**；检查固定两股票日、原始H5实读、OHLC/量精确2/2、成交额精确0/2及舍入2/2、前后只读与全市场不认证标志，并将两份证明原字节SHA放入新摘要。
- **只使用**先前验证过的Parquet`day/2026-09.parquet`有界只读Reader，针对2026-09-30两股共2根日线、八列读取，源行数最多150000/32行组；对原H5`sh_day.h5`/`sz_day.h5`分别仅二分查找目标日单根原始整数。全部源文件只读，size/mtime前后比较。不会写真实H5、原Parquet、SQLite、生产路由和私有overlay。
- 在Python内存中，候选原H5整数 = `Decimal(str(ParquetFloatAmount))/1000`；**分组计数**：偏差绝对值落在0、(0,0.01]、(0.01,0.1]、(0.1,0.5]、(0.5,1]、>1个原始H5整数刻度；按half-even最近整数、向下取整、向上取整分别与当前原H5整数是否相等；候选高/低于原始整数以及原先相对容差1e-5是否仍成立。**只生成字段计数，不输出价量额原值、时间戳、股代码、原H5整数或绝对源路径**。
- 读取后再计算当前真实六字段精确计数，必须与上一份SAFE逐字段完全一致，否则停止，防止用已变化的市场文件“解释”原先记录。两份输入SAFE哈希不变也必须检查。
- 即便候选最近整数2/2吻合，也不能推断供应商真实金额物理单位，更不能选择某个舍入策略；这是用于判定偏差分布和决定后续分母/小数来源调查的**描述性计数**。
- 所有`vendor_amount_physical_units_certified`、`lossless_native_h5_amount_conversion_certified`、`ready_for_full_market_mirror`均恒为false。

## Windows PowerShell：完整单行

先在虚构Arrow/H5数据上运行新增的**10项纯合成测试**，只有它们全部`OK`才进行**一次**小范围真实只读：

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/amount-raw-h5-residual-bounded-readonly-20261030; if ($LASTEXITCODE -ne 0) { throw "switch失败" }; git pull --ff-only origin feat/amount-raw-h5-residual-bounded-readonly-20261030; if ($LASTEXITCODE -ne 0) { throw "pull失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_real_pq_h5_amount_residual_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "合成测试失败，拒绝真实数据读取" }; $run=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\real-day-h5-amount-residual-20260930-$run.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-real-pq-h5-amount-residual-readonly.py --purchased-root "D:\stock\AllCycleAStockData" --h5-root "D:\stock\HikyuuData" --day 2026-09-30 --ten-safe "H5ParquetReconciler\reports\parquet-primary-day-crossyear-10-stockday-factor-evidence-v1.json" --exactness-safe "H5ParquetReconciler\reports\real-pq-native-h5-raw-integer-exactness-20260930-6f7127713c96.json" --out $out --read-only-amount-residual; if ($LASTEXITCODE -ne 0) { throw "真实只读金额残差验证失败" }; Write-Host "新SAFE：$out"
```

报告仅保存在模块`reports/`，生成独立随机文件名不覆盖历史。Windows实际新增测试/本轮真实读取**尚未执行**；不能预先填写结果。只需返回终端结果与SAFE JSON，不上传原始商业Parquet/H5或行情记录。

## 主线后续

若偏差在一半整数刻度内且原H5与某种候选取整一致，先确认供应商金额量纲和精度定义，不能将“刚好一致”作为全球性舍入认证；若偏差超过容差或原H5不等于最近整数，则维持阻断，调查历史H5整数生成规则和现有复权/量纲，必要时把此样本列为独立异常。

购买Parquet主源优先、H5只补全日线缺口、私有可回滚统一Parquet、Hikyuu原生镜像、通达信盘后增量的总体路径不变。
