# 截至 2026-10-13：统一八周期实际 Parquet Dataset

用户已明确 2026-10-14—10-31 没有行情，**本项目本轮一律不检查、不回填、不标记这段日期**。截止日固定 2026-10-13（包含）。

## 数据结构与真实落盘

本阶段不是再作单股样例查询，也不重新拷贝数十亿条购买行情。通过 pyarrow.dataset 将已经存在的物理 Parquet 文件按八周期组织为统一零购买复制的数据集；生成一份 SHA 版本化私有元数据 manifest，八周期各自是可以直接打开的实际 Arrow Dataset。

- 购买源：复用 2011—2026 八周期目录SHA 7f4a84f07d519e317d6b51049004d937acd8cba4cf561a3312fe457c5bed68df 已真实验收的192份原购买 Parquet 文件。除了day之外的七周期直接引用来源，并再次核对全部来源的stat/footer、物理Arrow类型和文件数量；不更改源值或重复压缩。
- 日线：使用已物理存储且SHA和唯一股票日验收的 2011—2026 全16年版本 bd64abcd0580cbed404c31bc2db3a05f9b2411880fa24d6bf3b14ecabcdb0c05，读取 reports/private-2011-2026-all16-sha-bound-version-15fb74d42d0b.json、16个manifest和SQLite及所有购买+H5实际Parquet分区。总计14,137,981条，其中购买14,115,707、H5-only候选22,274；**禁止再重复追加22,274条造成日线重复**。
- 1/5分钟：引用已验收的四个交易日8份H5-only分钟私有Parquet和其SHA；原购买日优先，购买文件原位。
- 15/30/60分钟：引用已有所有实测SHA验收的四日私有分区，总计621,348根高周期候选；不重复合成。
- 1990—2010：已有3,682,327条保守A股代码候选的21份日线私有Parquet；本次默认重新做21年完整来源/物理SHA/键审计，作为**独立历史研究级物理Parquet层**加入同一版本manifest，但不混入正式标准日线，因为历史价格、成交量、成交额的物理单位、证券身份、复权仍未认证。原始H5的631,281条其他代码记录仍保持隔离，不会丢弃。

所有源数据均维持原始路径。仅在模块私有 work/unified_parquet/datasets/eight_cycle_asof_20261013_<SHA前16>/manifest.json 创建一个不可变JSON来源清单，重复运行同内容幂等复用，不生成行情Parquet、H5或生产指针。对每个物理源文件读取Arrow footer/字段；在完成来源SHA校验后，**真实创建8个 pyarrow.dataset 对象**核对物理fragment存在。每周期共同可读取字段为 ts:int64、symbol:string 和 open/high/low/close/volume/amount:float64；原购买源股票代码拼写、周月时间语义未擅自修改。

## 读取方式

Python模块 tools/build-asof20261013-unified-eight-cycle-parquet-dataset.py 提供 open_eight_cycle_dataset_bundle(manifest_path,root,expected_sha=...,allow_research_unverified_units=True)，一次源审计后返回八个真实Arrow Dataset；scan_period_asof(...) 提供严格的2026-10-13北京时间上限流式查询。历史研究层使用 open_historical_1990_2010_research_day_dataset(...,allow_historical_unverified=True)，不自动混入普通day。

Windows脚本 run-build-asof20261013-unified-eight-cycle-parquet-dataset.ps1 执行既有来源回归和15项新合成测试、已有全部SHA来源核查、21年历史审计，再发布物理Dataset manifest；成功标志 PASS_ASOF_20261013_ALL_EIGHT_CYCLE_REAL_PARQUET_DATASETS。

## 不可误称已完成的部分

该版本是已存在Parquet碎片组成的**研究可用物理多文件数据集**，不是重新建立全量复制的单目录数据库，不表示2011—2026所有股票/时间网格的缺键认证完成，也不表示历史量纲、复权、交易日历、供应商字段、量价单位已认证。继续做逐周期真实键差集并明确缺口与异常；随后单独安全发布、镜像H5。新增代码还需用户本机Windows首次运行，不能提前算通过。

## 2026-11-10 Windows 首次预检失败与修复

Windows 提交 9c0507f 首次运行：既有7项来源目录测试、12项八周期SHA查询测试均通过；新增15项中14项通过，唯一报错 test_source_catalog_change_prevents_manifest_use 的模拟payload漏写 modern_16year_day_physical_version_sha256，导致 load_manifest 在虚构测试数据上 KeyError。**真实数据集构建并未开始**，不能把此错误解释成原购买Parquet损坏。

修复在当前开发分支完成：模拟payload补齐现代DAY版本SHA、历史层空列表和固定10-14后界；load_manifest 在实际重核前主动检查全部必需SHA与截止日字段，对缺失/畸形manifest明确拒绝而不是KeyError；加入源身份不完整与8个真实Arrow Dataset打不开就不能发布manifest的回归。新增测试数现为17，**待用户下一次Windows验收**。并已调整先打开全部8个实际Arrow Dataset、最后才写不可变成功manifest，防止失败后留下伪成功版本。原行情不重新物化，截止2026-10-13不变。