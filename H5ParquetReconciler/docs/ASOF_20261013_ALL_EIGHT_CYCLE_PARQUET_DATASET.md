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
## 2026-11-10 Windows 真实物理数据集验收：PASS

用户 Windows 运行仓库版本 46f2b9c，来源目录/版本绑定/构建器 **7+12+17=36 项合成测试全部 OK**。新增合成中的 `python.exe -m unittest ... error: Unopenable synthetic Arrow fragment` 是预期模拟失败门禁，整个测试进程最终 OK，不是实际源损坏。

全部 1990—2010 私有历史日线21年的真实 `READONLY_PRIVATE_H5_YEAR_PASS`、唯一键/Arrow/H5源stat和SHA最终成功，3,682,327条独立历史候选存续，原631,281条非候选代码完整隔离。最终 **8 个实际 PyArrow Dataset 全部成功打开**；物理文件数 1min=28、5min=28、15min=250、30min=250、60min=250、day=26、week=24、month=24，合计880个实体文件引用。没有改写或复制原付费行情、没有H5镜像或生产指针。统一实际物理数据集SHA256：

`a4987bba0ce3a1f6da05242f64cc21b94b070b193b5590ddb7bbd7f9197f5b01`

manifest= `work/unified_parquet/datasets/eight_cycle_asof_20261013_a4987bba0ce3a1f6/manifest.json`。版本只读保留，不需要再次执行21年全值历史审计或重建880个物理引用。

## 下一步代码：真实八周期物理行数总账（Windows 待运行）

新增 `tools/audit-asof20261013-eight-cycle-parquet-physical-rows-readonly.py`、9项临时PyArrow真实页脚测试和 `run-audit-asof20261013-eight-cycle-physical-parquet-rows-readonly.ps1`：读取**上面已经成功生成的不可变数据集**，逐一检查全部实际原购买/私有Parquet片段的物理行组计数、时间上界和来源SHA；不读取OHLCVA行、不新建行情文件、不重新执行1990—2010年逐行历史审计。逐周期统计真实物理行数、源类别与文件数，仅输出合计。

既有实测原购买页脚各周期行数（不是股票日唯一键）加已核对候选行数预测审计目标：1min=3,452,748,739；5min=687,688,817；15min=229,229,608；30min=114,614,804；60min=57,307,404；day=14,137,981；week=2,996,956；month=711,331，总计4,559,435,640个**物理Parquet行**，另有3,682,327个独立未认证历史研究候选。前两期1/5min H5四天按22,191股票日×240/48推导，15/30/60min按×16/8/4，必须以用户本机实际footer结果为准，不能提前声称完全一致。

此门禁是每周期**总物理行数与来源结构**验证，仍不是按(symbol,ts)精确去重、交易所交易日或完整分时格证明；原vendor全文件SHA、价格量额/复权语义尚有独立未完成认证。验证后下一步转向按年份/月份的真实键集合差异，区分已购源相同股票日、私有H5 only、部分分钟格和无真实可用源，不再回头查询2026-10-14～31。

## 2026-11-10 八周期物理行数总账：Windows 9项合成测试发现并修复历史字段夹具问题

用户在提交 e0f5944 的 Windows 执行中，首次新审计的9个合成测试有7个通过、2个错误，均发生在测试用单周期模拟来源（只有1min）上：`audit()` 过去无条件索引 `payload["historical_1990_2010_day"]["historical_files"]`，触发 KeyError。这次测试停止在启动真实 `D:\\stock` 页脚扫描之前，**不能因此判定已存在880份源Parquet和先前验收的数据集有问题**。真实物理Parquet Dataset 构建成功仍由此前的 SHA `a4987bba0ce3a1f6da05242f64cc21b94b070b193b5590ddb7bbd7f9197f5b01` 标识。

修复后：仅在 `periods==D.PERIODS` 的完整八周期路径加载并预检21年历史层，保证必需历史记录不存在时立即显式拒绝；指定单周期/子集统计不触碰历史，返回 `separate_historical_1990_2010_unverified_rows=0` 仅表示该*子集*没有被统计历史，并不表示原历史分区缺失。另增加完整八周期缺历史来源/空历史列表、子集忽略不必要历史注册三项回归，累计12项合成测试。Windows新版测试与实源全行数核对尚待首次验收，未产生新行情、索引、数据集指针或镜像。

## 2026-11-10 按用户要求立即调整优先级：Parquet→完整原生H5，不再做连续物理总账/重复键扫描

用户最新明确要求尽快利用已完成的统一 Parquet 补齐 H5；停止把重复的页脚统计、2026-10-14～31空来源查询、继续构建购买分钟全量索引当主线。真正需要的是只生成 Hikyuu 支持的 day/1min/5min 原生整数 TABLE、验证后安全切换；15/30/60min与week/month属于购买 Parquet 所有的独立周期，不能假装旧H5有同等物理结构。

**不重算的实绩：** 2011—2026年购买优先14,137,981条日线已曾反向写入 `work/h5_mirror/full_day_3dc5044a4122/` 三份独立Hikyuu day H5；全量整数读回通过，SAFE `reports/full-2011-2026-native-h5-day-3dc5044a4122.json`。分钟已有9月28～30购买数据+10月13 H5补缺合计6,427,013条、6份独立原生H5 `work/h5_mirror/minute_union_660389198d64/`，SAFE `reports/mixed-purchased-h5-native-minute-4days-660389198d64.json`。这些均不是D:\stock\HikyuuData生产原件，禁止假报原H5已补齐。其后2026年的更多已验分钟私有Parquet可直接用于后续分批镜像，但2011—2026分钟全量3.4B+0.69B条仍需实际生成H5，不可仅凭Arrow dataset可打开就说已完成。

**立即可执行的首个真实H5动作：** 工具 `tools/merge-existing-native-day-h5-original-history-and-2011-2026-parquet-mirror.py`、6项真实PyTables合成测试及入口 `run-complete-day-h5-from-existing-original-and-parquet-native-mirror.ps1`。此入口先验证已写好的16年现代 H5 来源SHA，再把 `D:\stock\HikyuuData/{sh,sz,bj}_day.h5` 三个原生文件复制到新的 `work/h5_mirror/complete_day_<run_id>/`，**不再读取14,137,981条原始Parquet价量额**；在复制文件中，仅针对已有购买优先镜像的SH/SZ/BJ股票表做原生整数K线逐日并集，保留1990—2010原生记录、2011+只在原H5而不在购买镜像的原始记录和所有不在现代镜像中的原证券表。对重合日线键用Parquet镜像整数覆盖原H5，不改原市场文件、非/data元数据和非镜像股票表。每股新TABLE整数完整读回、现代镜像原SHA和原H5原字节SHA前后校验，最终三份独立原生H5 SHA写安全SAFE。这是原生H5日线实做，不是再次研究；首次实机待验证。新H5仍属隔离输出，未取得全市场Hikyuu C++驱动读回、量额量化业务接受和备份切换校验前不能直接替换生产原H5。

**随后的最主要工作**是利用已验收的八周期文件清单直接对购买1min、5min原件做有界流式本地批量H5镜像，按证券+原生时间键与旧H5并集，恢复已有6,427,013条镜像成果并继续2025—2026，逐年持久化checkpoint；原购买数据至少3,447,422,899条1min和686,623,649条5min，体量很大，必须利用源本身而非把所有数十亿条OHLCVA装内存。当前尚未完成全分钟H5，不得声称已经激活。已有现代日线H5阶段不重复生成。

## 2026-11-11 继续下一步：首批 REAL purchased 1m/5m Parquet→Hikyuu 原生 H5

本机用户真实回执：上一轮三市场日线 H5 真实隔离合并已 PASS，`work/h5_mirror/complete_day_cd7633cd99cb/`，包含现代购买优先 14,137,981 日线、在相关股票表中保留的原H5 1990—2010 日线 3,811,239 和现代原 H5 独有的 118,084 条；SAFE `reports/complete-day-original-plus-parquet-native-cd7633cd99cb.json`。本轮禁止再次转换日线及复制已完成的全部早期日线来源。

**新增实际分钟回写实现**：`tools/mirror-asof20261013-purchased-minute-parquet-into-copied-native-h5.py`，5项购买Parquet+PyTables真格式合成回归；Windows一次入口：`run-first-real-purchased-minute-parquet-to-native-h5-copy.ps1`。从已实测八周期物理数据集SHA `a4987bba0ce3a1f6da05242f64cc21b94b070b193b5590ddb7bbd7f9197f5b01` 读购买1min/5min原件，仅检查 Parquet 页脚有可能覆盖所选日期的 rowgroup，批次迭代投影8列，按原供应商时间键转换为 Hikyuu 40-byte整数记录；借用此前真实6,427,013条已通过的候选数值倍率、1min结束时标及5min+5映射，不重新读取日线/原6.4m镜像，不宣称供应商已认证。所有新增日期 `(period,canonical symbol,native datetime)` 写进**磁盘SQLite**，防止一次性加载百万到数十亿行并拒绝重复购买键。

先实写 `2026-09-24` 单交易日（之前已物化Parquet，但从未纳入已成功的四日分钟 H5 镜像），再滚动扩大。创建 `work/h5_mirror/minute_purchased_wave_<id>/`，只有第一次复制6份原H5到私有目录，保留全部 `/data` 中未变证券及其它元数据；按购买 key 替换复制H5里同键行，原H5独有键全部保留，并逐证券严格整数回读后写 SHA SAFE。源 Parquet 仍采用 size+mtime 及旧清单身份验证（未计算商业文件完整字节 SHA），输入 H5 初始/完成 stat 验证，禁止直接向 `D:\stock` 写入或覆盖。6份原H5副本可能较大，写入前检查剩余磁盘空间，空间不足即拒绝，勿绕过。

此交付是**首批真实分钟回填和H5副本完整整数字段验收**，不是2025—2026或2011—2026全历史4.1B条全部H5同步。每次独立生成6份全源副本适于验证首波，不应对全部历史按日重复拷贝6份大H5。实机首波成功后应**把此隔离版本当持续写入的工作基线**，研发按月分组读取/持久增量checkpoint/源版本检验后继续更新同一候选H5，不再重复整个H5复制。最后做Hikyuu C++原生读取、键/值与被接受量化规则核对，再给用户明确批准的生产原H5备份和切换机制。

### 2026-11-11 增量修正：首波必须复用已完成的642.7万条分钟原生镜像

为了让这次真实回填结果累积而非重建另一套不完整分钟H5，首波同时绑定已在2026-11-02实测通过的四日完整原生H5镜像：`work/h5_mirror/minute_union_660389198d64/`，SAFE `reports/mixed-purchased-h5-native-minute-4days-660389198d64.json`。新工具 `prior_native_files` 将两周期1min=5,358,629、5min=1,068,384，合计6,427,013条与六文件SHA/日期约束校验。输出时先从原H5复制6个完整文件，合入9月24日购买Parquet当日时间键（优先），再把已有四日原生H5整数字节按同股时间键合入副本；两批在时间上不重叠。逐股票验证输出的40字节TABLE整数字节相同，源旧H5只读不改。新增2个集成真PyTables回归（既有5项→7项）涵盖复用前一镜像、源SHA篡改拒绝和原H5其他证券/时间键保留；Windows新7项尚未实测。

这仍是首次验证下一波实际Parquet→H5写入，接下来应基于**该首次成功H5候选库**增量写剩余年度窗口，不能每次复制整个原H5六文件。源vendor价量额量纲/5min时标映射为现有候选规则，原生Hikyuu C++全市场分钟驱动和商业数值等价尚未完成认证，禁止直接替换生产H5。

## 2026-11-11：真实9月24日分钟H5已验收，转连续续写（不再每天复制六份H5）

用户 Windows 已实测先前分支 b9013e0：7个实写模拟测试OK。真实2026-09-24购买Parquet1min=1,341,888条（涉及39行组）、5min=267,264条（47行组），合计1,609,152条，均转换为Hikyuu原生整数并在六份私有H5副本回读；此前已验原生四日镜像1min=5,358,629，5min=1,068,384合计6,427,013条也复用成功。被处理的来源数之和8,036,165，不等于H5净新增唯一键数。真实SAFE：reports/purchased-minute-native-h5-copy-20260924-22dc038f17a2.json；已验收候选H5：work/h5_mirror/minute_purchased_wave_22dc038f17a2/。原D:/stock及日线H5均未更改。

新工具 tools/resume-purchased-minute-parquet-into-private-native-h5.py、新8项PyTables/SQLite合成测试与一键 run-resume-purchased-minute-parquet-into-private-native-h5.ps1：第一次从刚刚验收的22dc六份H5及各自SHA复制一套持续私有工作库 work/h5_mirror/minute_resumable_22dc038f17a2；此后**不再每天复制六个完整原生H5**。对截至2026-09-23且早于首批基线的购买1min/5min按1到3自然日键扫描到有界SQLite文件，每证券用H5新表__next/备份表__undo与SQLite已提交状态事务逐股更新。脚本意外终止时会自动回退尚未提交证券、校验并跳过已完成证券，恢复后继续；跨成功批次六个H5整体SHA绑定及OS单写者锁。仅私有连续候选写入，原H5/购买Parquet依然只读，未经认证的分钟量额和Hikyuu全市场C++消费不视为生产完成。

首次真实连续批次选择2026-09-23（此前9月24日已验，避免重复）。首轮预期八项合成通过并输出PASS_RESUMABLE_PURCHASED_PARQUET_TO_NATIVE_MINUTE_H5，持续H5不再单日重新全复制；首轮Windows执行仍待用户新回执。之后按三天或单日窗口向2025、2011逐步推进，当前不处理2026-10-14至10-31，也不重复已完成的day H5。
