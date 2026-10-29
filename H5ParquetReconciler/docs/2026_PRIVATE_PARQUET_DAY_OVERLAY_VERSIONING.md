# 2026-10-29：H5补齐的私有Parquet日线版本合成与回滚

## 当前真实验收

用户回传`H5ParquetReconciler/work/unified_parquet/staging/day-20261008-v1/manifest.json`，其语义确认为
`AStockDataTools H5-only daily Parquet staging v1`、
`staged_verified_not_promoted`。
2026-10-08原验收H5-only 5,546根；私有日线Parquet暂存5,546根；市场：BJ 339、SH 2,314、SZ 2,893，合计恰好5,546；本地文件 SHA-256 `1aa1a34fc8a4710106424aae6bfc42cf9a518cee327f75797788611ea254a8f8`；gate和原始安全报告SHA绑定正确（本次只读取上传的清单，**未在云端重新获取并计算真实Parquet文件哈希**）。清单明确原市场数据未修改、未生产发布、H5镜像尚未生成。这不是“所有10月日线已补齐”的证明。

根据此前2026-09-01～10-28完整日线覆盖报告，H5补齐候选四日还包括
- 2026-10-09：5,547根；
- 2026-10-12：5,549根；
- 2026-10-13：5,549根。
共22,191根，其中10-08的5,546已完成**私有暂存**，其余16,645根尚待本机转换。10-14～28两来源均没有日线，未补齐，不能借此宣称当天最新。

## 本轮新增：统一Parquet的2026年日线私有overlay版本工具

`tools/build-parquet-primary-day-overlay.py`提供：
- `prepare`：仅接受原日线安全报告与SHA-linked日线gate、该gate中**全部**且仅有的Parquet全日无记录的H5-only日期暂存目录；拒绝缺天、重复天、非完整报告、含已存在Parquet数据的日期。
- 逐个检查每份私有暂存`manifest.json`、对应day.parquet SHA-256、Parquet schema/footer、全部`ts/symbol/source`键、市场分布和唯一性；会从原`D:\stock`购买Parquet和H5重新做逐日精确**只读**来源键审计，防止旧暂存期间源数据发生变化。
- 汇总为`H5ParquetReconciler/work/unified_parquet/versions/<sha256>.json`不可变版本；保留原Parquet作为优先只读基线。**准备版本不会自动设置活动指针**，不会动外部交易软件使用的数据库。
- `activate`：强制提供`--confirm-private-pointer`、指明已有SHA版本、再次校验暂存与来源的有效性，用模块内私有`active-day-overlay.json`原子替换启用该**私有指针**。目前没有下游查询代码自动读取这个指针，**绝不是已经更新正式主库或H5镜像**。
- `rollback`：通过`--confirm-private-pointer`将指针恢复前一私有版本（首次则关闭指针）；不可变版本和暂存Parquet保留。
- 当前只适用于`day`、已证实的2026-10-08、09、12、13，不新增分钟线单位假设、不写源文件、不允许生产自动合并。逐行OHLCVA隐私数据仅保留git忽略的模块`work`目录内。
- 新增9项合成集成测试，包含自造H5+Parquet、真实小样本Parquet写入与读回、准备/激活/回滚、文件与版本SHA损坏、额外购买日线到达、重复批次、外部路径和指针竞争的拒绝。**Windows结果待执行**。

## 本机下一步：先转剩余三天、测试版本工具

仓库根目录`D:\ChatGPT\AStockDataTools`，逐行执行：

```powershell
git pull --ff-only origin main
```

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_build_parquet_primary_day_overlay.py" -v
```

下列3条`stage`命令均**重新现场验证**Parquet该日无数据，不会写入原始来源；各输出独立新目录，不要改用已存在的目录名：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\stage-h5-only-day-to-parquet.py "D:\stock" --date 2026-10-09 --gate-report "H5ParquetReconciler\reports\parquet-primary-day-bootstrap-plan-20260901-20261028-v1.json" --source-report "H5ParquetReconciler\reports\day-coverage-20260901-20261028-v1.json" --stage-dir "work\unified_parquet\staging\day-20261009-v1" --read-only-sources
```

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\stage-h5-only-day-to-parquet.py "D:\stock" --date 2026-10-12 --gate-report "H5ParquetReconciler\reports\parquet-primary-day-bootstrap-plan-20260901-20261028-v1.json" --source-report "H5ParquetReconciler\reports\day-coverage-20260901-20261028-v1.json" --stage-dir "work\unified_parquet\staging\day-20261012-v1" --read-only-sources
```

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\stage-h5-only-day-to-parquet.py "D:\stock" --date 2026-10-13 --gate-report "H5ParquetReconciler\reports\parquet-primary-day-bootstrap-plan-20260901-20261028-v1.json" --source-report "H5ParquetReconciler\reports\day-coverage-20260901-20261028-v1.json" --stage-dir "work\unified_parquet\staging\day-20261013-v1" --read-only-sources
```

**只有测试成功且四个独立暂存目录全部具备校验成功的私有manifest后**，再运行下列命令准备版本：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\build-parquet-primary-day-overlay.py --action prepare --root "D:\stock" --gate-report "H5ParquetReconciler\reports\parquet-primary-day-bootstrap-plan-20260901-20261028-v1.json" --source-report "H5ParquetReconciler\reports\day-coverage-20260901-20261028-v1.json" --stage-dirs "work\unified_parquet\staging\day-20261008-v1" "work\unified_parquet\staging\day-20261009-v1" "work\unified_parquet\staging\day-20261012-v1" "work\unified_parquet\staging\day-20261013-v1"
```

最后一条成功会显示私有版本SHA-256及`private_rows:22191`，但**只做prepare，不启用指针、不切换生产数据**。请上传命令输出及四个`manifest.json`，不上传`day.parquet`等付费/自有行情。届时确认四天真实结果，再测试私有指针激活/回滚及开发查询消费接口。

## 风险/边界

本轮H5原生价格÷1000、日成交量×100、金额×1000仍属于与2026-09重叠报告比对一致的**格式映射候选**。因为2026-10-14～28完全没有日线记录，临时Parquet版本只补至10-13；后续通达信盘后数据需独立纳入。季度/分钟线、复权因子与真实证券主数据的完整性需在相应转换阶段验证；仅日线成功不能宣称所有周期已全覆盖。

不允许把私有`active-day-overlay.json`当作正式用户查询接口或擅自覆盖`D:\stock\AllCycleAStockData`。
