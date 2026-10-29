# Parquet 主库与 H5 镜像：正式实施路线（2026-10-29）

> 本文替代“持续追查H5与Parquet分钟K线差异机理”作为下一阶段开发主线。
> 目标是可恢复的统一数据体系，非建立两套永远独立维护且必须逐条相同的行情库。

## 1. 采用的原则和源优先级

1. 购买的历史 Parquet 是**基准来源**，原始 `D:\stock\AllCycleAStockData` 保持只读。
2. Hikyuu H5 (`D:\stock\HikyuuData`) **只补Parquet实际缺少的证券—交易日整段**：首先补其2026年9月、10月的近期空白，绝不按“整月”覆盖购买Parquet已有记录。
3. 重叠键优先保留Parquet原值；对价格异常、未知复权/成交量额口径、不同交易日缺口只留异常报告，不自动以H5替换Parquet。
4. 新统一Parquet在 `H5ParquetReconciler/work/unified_parquet/` 独立分区写入，逐文件事务化提交，保留来源与源文件哈希清单；通过验收后才可切换下游使用路径。不能直接修改原购买文件。
5. 统一Parquet随后转换为**Hikyuu可读的原生H5结构**，写入 `H5ParquetReconciler/work/h5_mirror/` 并独立用Hikyuu库/二进制字段校验。不允许把普通HDF5表误当成兼容Hikyuu H5。
6. 后续通达信盘后数据只接入**统一Parquet一次**，严格检查已收盘交易日、原生源格式、字段/量纲、重复导入、时间网格以及来源凭据；随后增量同步H5镜像，杜绝双头独立更新。
7. 原始H5/Parquet、通达信输入、完整商业OHLCVA不能提交GitHub。JSON安全审计摘要放`reports/`，SQLite和新库放`work/`，所有程序产物留在`H5ParquetReconciler`模块内。

## 2. 当前有据可查的日线结论

2026-09-30单日完整、只读双周期报告中，day/2026：
- H5 5,550唯一日线键，Parquet 5,560，交集5,550，H5独有0，PQ独有10。
- 交集价格OHLC按已有 **0.005元诊断容差**差异0；共有1,241条成交量和/或成交额差异，**不是六字段完全相等**，也不是经供应商验证的数值单位规则。
- 单日不能证明2026年全9、10月或2011年至今的日线全部一致。
- 历史五分钟不强制对齐。既有三股样例两来源的1分钟→5分钟聚合各自强自洽，但不能判断哪套数据是交易所真值；不再因此推迟填补真实缺口。

## 3. 分阶段交付与验收门槛

### 第一阶段：日线数据验收与真实缺口计划（当前）

复用`tools/reconcile-local-a-share-h5-parquet.py`只扫2026-09-01至10-28的**day**周期，限制候选A股前缀；可按月拆窗以节约实际I/O。报告必须状态`complete`，请求必须为真实明确日期窗口，且每个交易日的H5唯一键数与Parquet唯一键数/交集/差集严格守恒。

新工具`tools/plan-parquet-primary-day-bootstrap-offline.py`只从完整日线安全JSON读取，不读任何市场文件。输出逐日覆盖、日线价格验收、H5在Parquet全日无数据日期的候选行数、混合日期需要后续**逐证券—日精确键清单**的数量。SHA256绑定原安全报告。它**不是**最终补齐批准，失败及来源不完整直接拒绝；`ready_for_unattended_data_fill=false`、`safe_to_automatically_union=false`保留。

由于只扫day还不能判断股票某日的分钟数据是否完整，**决不能依据日线通过就自动填1min/5min**。

### 第二阶段：新统一Parquet的增量补齐（尚待实现）

- 对H5实际新于Parquet的日期，逐周期逐证券按来源校验与真实键清单确定可填段；已有的Parquet键永不被覆盖。
- 明确区分整股票日缺失、单日内部分钟缺失、未上市/停牌/异常；默认仅补完整股票日，分钟残缺隔离供复核。
- H5日线原生`datetime YYYYMMDD0000`、价格整数/1000、成交额整数×1000、成交量日线整数×100均为已观察到的**候选量纲**；必须先通过输出Schema/样例端到端验收，再将单位映射正式写入转换器，不得因多数样本相近就宣称认证。
- H5原生5min时间一般用结束标签，Parquet用开始标签；H5原生分钟量口径×100目前只有候选实证，**不能直接用于自动历史全量回填**。Parquet 1min 09:30单独记录的兼容策略要经分区测试，不得制造伪重复。
- 写统一Parquet采用分区暂存、哈希、清单、原子切换与失败回滚，旧版本保持可读。只在模块`work/`中构建新库。

### 第三阶段：H5镜像生成（尚待实现）

- 从新统一Parquet生成原生Hikyuu 3交易所×day/5min/1min格式。
- 验证字段宽度/u32/u64范围、缩放无溢出、分钟时标、同一证券同日唯一键与顺序、实际Hikyuu打开读取。
- **不能**在未成功全量重建/核验前覆盖`D:\stock\HikyuuData`。

### 第四阶段：通达信盘后增量（已有辅助adapter，正式生产未接入）

- 现有`tools/tdx-postclose-private-overlay.py`是本地标准化JSON单证券日实验暂存器，**不是通达信原生二进制解析器**，也不直接写Parquet/H5。应复用其来源凭据和回滚模型，开发原生盘后读取→统一Parquet追加→H5镜像同步。
- 每个日终批次需检查已收盘交易日与交易所日历、完整分钟数/异常早收或停复牌、幂等键、文件版本及数据变更；回滚只切版本指针，不删原始数据。

## 4. 当前Windows验收：仅日线、低成本

在 `D:\ChatGPT\AStockDataTools` 的PowerShell逐条执行：

```powershell
git pull --ff-only origin main
```

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_plan_parquet_primary_day_bootstrap_offline.py" -v
```

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2026 --periods day --from-date 2026-09-01 --to-date 2026-10-28 --universe a-share-candidate --read-only --out "reports\day-coverage-20260901-20261028-v1.json" --scratch "work\day-coverage-20260901-20261028-v1"
```

**仅当上一步状态`complete`**，执行纯离线验收，不再次扫描行情：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\plan-parquet-primary-day-bootstrap-offline.py --report "H5ParquetReconciler\reports\day-coverage-20260901-20261028-v1.json" --out "reports\parquet-primary-day-bootstrap-plan-20260901-20261028-v1.json"
```

如执行前目标文件已存在须更换新版本名，不覆盖旧JSON。如果Windows核验和上述安全报告通过，下一轮应**直接开发第二阶段独立Parquet staging**，不再额外开展分钟边界机理研究。

## 5. 后续历史校验

日线2026年近期窗口验收之后，再对较早历史分阶段跑`day`审计。若发现少量OHLC超出诊断容差，记录在价格异常表，仍保留Parquet主值，不把异源冲突当成源缺口。仅当真正构建了新统一Parquet和Hikyuu镜像，才将“数据已覆盖更新”“镜像已同步”标记为完成；生成离线计划不能替代实际写库验收。
