# 2026-10-28：TDX↔购买Parquet开盘241→240规则边界只读调查 v1

## 基线：已完成的真实证据

- 用户Windows实际执行候选预演8项合成测试全部通过。
- 用户Windows实际执行新的预演汇总8项合成测试全部通过
  （Ran 8 tests in 0.445s, OK）。
- 已上传并核对真实十股票日候选预演汇总
  tdx-pq-normalization-preview-cohort-ten-stockdays-v1.json：
  10组、4只股票、4个日期；all_supplied_previews_match=true；
  original_audit_cohort_crosschecked=true；
  verdict=exploratory_preview_target_met_not_certified。
- 跨样本四价格字段最大相对误差5.08e-08，成交量最大相对误差0，
  成交额最大相对误差1.07e-08，均在诊断容差内。
  Parquet来源指纹仍为stat-only，不是文件内容校验。

## 为什么不直接入库

10组均为正常完整分钟资料。不能据此将候选规则扩展到
停复牌、除权复权、历史数据供应商不同版本、交易时段变化、
缺少或重复分钟等情况。当前唯一候选规则仅标为
experimental_tdx_end240_from_pq241_opening_fold_v1。
这一规则**未经生产批准**、不具有A股全市场适用认证。

## 新增：带安全异常分类的只读调查

工具：tools/survey-tdx-parquet-minute-rule-boundaries-readonly.py

只允许显式指定1..12个SH/SZ的股票+日期，调用**现有真正
已测试的标准化预演**，而不是根据安全报告复述结论。读取
真实的TDX分钟源及购买Parquet两个周期，限额扫描，禁用
私有缓存，不导出任何市场价、量、额、逐分钟时间或私有路径。
仅在H5ParquetReconciler/reports新建一份安全JSON。

结果可能为：

- diagnostic_match：该个股该日六字段/四道门槛全部通过，
  仍是实验性匹配，不是可入库。
- mismatch：四道门槛中至少一个不匹配，标记
  candidate_six_field_disagreement，拒绝转换。
- unsupported：源文件缺失、不安全路径、不完整240/241分钟网格、
  不合法K线几何关系、来源清单漂移或未能分类的源异常；
  不会将异常当作匹配。异常类别是保守诊断，不能据此
  推断停牌/除权等具体交易原因。

输出永不包含底层Python异常原文，因为异常消息有可能包含
私有绝对路径。即使有若干案例不通过，安全调查仍保留其他
通过的案例摘要；整批判定为anomaly_observed_do_not_apply_mapping。
任何情况都严禁生产合并、原始行情覆盖与候选材料化。

## Windows操作：每条命令均为单行

在 D:\ChatGPT\AStockDataTools 仓库根目录运行：

git pull --ff-only origin main

先运行新增9项合成回归（尚待你本机验证）：

.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_survey_tdx_parquet_minute_rule_boundaries_readonly.py" -v

再针对**尚未被这十组覆盖**的历史股票日进行真实只读调查：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\survey-tdx-parquet-minute-rule-boundaries-readonly.py --parquet-root "D:\stock" --tdx-vipdoc "D:\software\TDX\vipdoc" --case SH600000 2026-07-16 --case SZ300750 2026-07-16 --case SH600519 2026-06-30 --case SZ000001 2026-06-30 --read-only --out "reports\tdx-pq-minute-boundary-survey-20260716-20260630-v1.json"
```

这四组是扩大月份覆盖的**调查目标**，不是先验认定异常；
如果通达信文件缺失，报告将给出匿名类别，不补造市场数据。
该调查需要读取购买Parquet本机数据，请依据当前机器资源
与扫描预算运行；若慢，应停止后进一步优化查询窗口，而非
开启无界全量扫描。输出只能创建新的JSON；不能覆盖旧报告。

建议上传该调查JSON和9项合成测试输出。对任何未支持的日期
再研究真实来源差异和显式版本化政策，未授权前不考虑数据暂存。
