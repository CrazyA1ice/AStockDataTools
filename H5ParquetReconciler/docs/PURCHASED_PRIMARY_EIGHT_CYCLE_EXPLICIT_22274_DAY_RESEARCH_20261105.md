# 22,274条日线H5候选 → 购买Parquet八周期研究查询：显式只读接入

2026-11-05（仅开发分支，尚未本机Windows验收）

## 真正的主线目标
现有受控版本有 **22,191条whole-date** 和 **83条mixed-stockday** H5日线候选，
合计 **22,274条**，覆盖2016及2026来源。2026-07-16的5条异常候选
继续隔离，不能自动写回或当作有效补缺。研究路径遵守“购买Parquet
优先；只有确证购买来源缺失的股票日才读SHA注册的私有H5补缺”，
所有生产数据与指针保持原样。

## 为什么不再重新实现日线融合
已有工具：
- `tools/register-private-combined-day-22274-version.py` 对已有22,274候选
  的证明文件、私有合成物和来源stat生成**不可变内容SHA版本**；版本不激活生产。
- `tools/query-private-combined-day-22274-readonly.py` 每次请求都重新
  执行原始H5/购买Parquet来源与候选SHA/键核对，并将购买/whole/mixed
  三种记录按股票日合并；发生重叠、源漂移或版本不一致即拒绝。
  这是研究查询，不会更改市场文件；会在模块 `reports/` 下新增
  **两份仅含安全统计的JSON验收回执**（不能覆盖旧回执）。
  
本轮是在 `tools/query-purchased-primary-all-eight-cycles-readonly.py` 中新增
**默认关闭**的 `private_day_evidence` 参数；只对2016/2026、单年份、
`period="day"` 支持显式传入已注册版本SHA及下列七项证据路径：
`version_sha256`, `live_safe`, `private_keys`, `history_ledger`,
`source_2016`, `source_2026`, `mixed_plan`。

- 提供对应CLI `--allow-registered-private-day --private-day-config <path>`，
  二者必须同时提供；配置必须是`H5ParquetReconciler/work/unified_parquet/`
  内已有的、不超过8KiB的JSON文件，字段不能重复或缺少。
- 接入后再次核对返回的三类来源计数与逐条`value_source`、
  完整版本SHA和安全字段；异常立即中止，不能返回看似正确的部分结果。
- 任何常规`day`、`week`、`month`、15/30/60分钟、1/5分钟
  默认查询方式未改；分钟专属私有H5模式不能与日线模式混用。
- 八周期仍是研究接口，不代表复权因子、量价单位、证券时点身份、
  完整交易日历或生产启用已完成认证。

## 避免无谓重扫的首轮检查
新增 `tools/inspect-registered-private-day-22274-readiness-readonly.py`：
只读取 `work/unified_parquet/combined_day_versions` 中的注册版本
SHA文件，并重核其引用SAFE文件字节指纹。**不启动H5/Parquet行情扫描、
不生成任何新文件，也不会激活生产**。没有版本返回
`no_registered_22274_private_day_versions`，不应假装已有可调用版本。
如果有多个版本，均列出SHA但不自动选择以免误用过期候选。

Windows单入口：
`H5ParquetReconciler/run-purchased-primary-private-22274-day-mainline-readiness.ps1`。
先运行现有八周期、既有日线融合、显式路由、版本库存的合成测试，
再检查本机已注册版本。**本轮新工具/测试尚待用户Windows实机验收**。

### 后续安全门禁
如果本机有已经注册且SHA一致的版本，确认各项来源路径后，
在 `work/unified_parquet/` 内配置七字段的本地私有证据JSON，
仅选一个单证券、单年份且不超过31天的日线查询，执行现成
22,274版本的**完整现场来源复核**。其耗时可能较高，绝不以静态
版本库存等同于完整实时验收。确认过真实单证券日线查询后才讨论
批量研究和生产上线；本轮不物化H5、不开启H5镜像也不修改原始数据。

## 独立待办
- 2025 `SZ302132` 的特殊供应商历史代码映射已有26个变更前日线键
  的5分钟来源证据；2025-02-17 OHLCVA命中多个物理RowGroup累计
  3,194,908条，超225万专项读取上限。保留单独的性能问题，**不
  以提高读取预算阻塞或替代日线补缺主线**。
- 独立交易所日历、2011年前约1990起的H5日线范围、复权因子
  均需要独立认证，不允许由22,274候选推断这些历史范围已补齐。
