# 开发路线与本轮交付记录

更新：2026-10-29　仓库：CrazyA1ice/AStockDataTools

## 方向调整

不再延续对旧GLSSTKGM随机抽样查缺的小轮迭代。这里直接以**全量覆盖报告和可追溯并集构建**为目标。当前属于Phase 1初版，先用本地大数据验证差集和冲突报告是否可靠，再启动格式互转。H5是手动下载的，早期缺小周期、尾部可能新增盘后数据；Parquet购买包整体覆盖时间长但截止2026-09。两者互补是需要实测而非预设永远成立。

## ★ 已定位已有Hikyuu 2.8.1 / Python311，核对原生H5读数比例（2026-10-29）

- [x] 用户本机修复后**12/12测试通过（1.592秒）**；Python 3.11 `D:\\software\\Python311\\python.exe` 中`pip show hikyuu`确认为**2.8.1**，无需在项目.venv中安装Hikyuu。Python 3.15及Anaconda base的`pip show`未找到；Conda另有`hikyuuQ`环境待核对。
- [x] 实际读取上游**2.8.1标签**`H5KDataDriver.cpp`确认原生H5日线`/data/SH600000`、`/data/SZ000001`，H5整数到`KRecord`的驱动缩放为OHLC ×0.001，`transAmount` ×0.1，`transCount` ×1。这是Hikyuu HDF5读取编码规则，**不是购买Parquet与H5的真实单位映射证明**；原始数据保持只读。
- [x] 代码已支持`--python-exe`由隔离子进程使用外部已有Python；下一步使用`D:\\software\\Python311\\python.exe`运行SAFE运行时预检，确认安装wheel的实际绑定接口。完整命令与后续原生驱动方案见[Hikyuu 2.8.1源码及隔离验收依据](2026_HIKYUU_281_NATIVE_DRIVER_SOURCE_EVIDENCE.md)。
- [ ] 用户尚未运行Python311真实SAFE子进程预检，也**未**通过原生C++数据驱动读出3根虚构K线；不得把现有HDF5结构及PyTables往返测试当成原生驱动认证。

## ★ 修复Windows Path解释器校验造成12项预检1项失败（2026-10-29）

- [x] 用户Windows新12项测试：`Ran 12 tests in 1.446s`，11项`ok`、1项`ERROR`（`test_explicit_alternate_python_path_without_installing_packages`）。错误发生在`_explicit_python`使用`type(exe) not in (str, Path)`进行精确类型比较；argparse或测试传入`WindowsPath`，该具体类型不等于抽象`Path`，导致合法绝对路径尚未进入subprocess就被拒绝。
- [x] 将校验改为`isinstance(exe,(str,Path))`，仍保留绝对路径、非软链接、真实文件、`python.exe`名称与无shell/不初始化StockManager等防护。不改动H5市场数据、22,191条私有stage、原已生成的合成H5或安全报告。
- [x] 原失败测试扩展支持WindowsPath/PosixPath对象及str(path)，修复后用户Windows完整12项`OK`（1.592秒）；实际Python311运行时导入测试仍未运行，见上方。
- [ ] 测试通过后再检查已有Python解释器是否安装Hikyuu（先`py -0p`、`where.exe python`、候选Anaconda`pip show hikyuu`）。只有确认指定解释器路径存在才进行隔离`--python-exe`预检；不能因为此类型校验通过就认证Hikyuu原生H5驱动。

## ★ Hikyuu隔离预检8/8通过；当前项目\.venv未安装Hikyuu（2026-10-29）

- [x] 用户Windows隔离运行时测试`Ran 8 tests in 0.851s`、`OK`；SAFE回传双股合成文件SHA复核`true`，`hikyuu_runtime_status=hikyuu_not_installed_in_this_interpreter`，`installed_hikyuu_version=null`，API清单为空。此结果只代表执行探针的项目Python解释器缺少包，不代表HDF5镜像结构失败或电脑所有Python都未安装。
- [x] 既有运行时预检增加`--python-exe <ABSOLUTE_PATH_TO_python.exe>`：仅在用户明确指定时由隔离子进程选择其他已存在环境，仍在原项目venv验原canary SHA，保持`-I`、独立HOME/APPDATA/TMP、剥离Hikyuu/Python/Conda环境标记、无任何StockManager初始化或原生H5读取；SAFE不记录用户外部Python路径。
- [x] 新增4项合成测试，原隔离探针测试总数**12项，尚待用户本机运行**。对应操作：[已有Hikyuu Python解释器安全定位与替代隔离预检](2026_HIKYUU_ALTERNATE_PYTHON_PREFLIGHT.md)；候选`D:\\software\\anaconda\\python.exe`仅基于过往运行环境日志，必须用`Test-Path`和`pip show hikyuu`核对。
- [ ] 取得真实可用的Hikyuu版本及Python API信息后，开发真正独立H5驱动读取合成3条K线的安全试点，不污染项目venv、不修改HikyuuData、商业Parquet及私有版本。若任何既有环境都无Hikyuu，再讨论独立新测试环境安装。
- [ ] 当前仍**不允许**生产日线合并、真实H5镜像批量生成或直接切换用户正式hikyuu配置。

## ★ PyTables合成金丝雀7/7通过，Hikyuu原生驱动隔离环境预检（2026-10-29）

- [x] Windows真实合成金丝雀构造7项测试`Ran 7 tests in 0.716s`、`OK`，用户上传SAFE报告：SH600000、SZ000001各3根虚构K线，40字节记录，PyTables+h5py整数数值往返完全一致，合计6根；两份输出SHA均记录、真实源未读未写、私有版本未激活，Hikyuu原生驱动`hikyuu_native_driver_tested=false`。
- [x] 新增隔离运行时能力探针`probe-hikyuu-native-driver-runtime-isolated.py`：先复核合成文件SHA，再通过`-I`独立子进程和私有HOME/APPDATA/TMP只`import hikyuu`与收集安装版本、固定公开API存在性。绝不调用默认`hikyuu_init`、导入`hikyuu.interactive`或初始化证券管理器，避免用户正式StockManager/config与真实数据库进入实验。
- [x] 新增8项模拟/离线测试覆盖Hikyuu存在/缺失、文件变化、报告非法路径、超时/崩溃、子进程伪造原生执行状态；无原始市场数据输入。生成结果仍强制`native_h5_driver_read_executed=false`，不会因Python包可导入就认证HDF5驱动兼容。
- [x] 用户Windows8项测试全部通过，SAFE确认当前项目解释器缺Hikyuu；转为可指定已有解释器的隔离预检，下一步详见本页顶部。
- [ ] Hikyuu真实native KData驱动读取三根虚构数据并精确校验日期和缩放，之后继续Parquet→原生H5实际价量映射及增量同步。当前生产切换/历史原件覆盖仍关闭。

## ★ Hikyuu真实H5两股40字节字段布局核对，构建纯合成镜像金丝雀（2026-10-29）

- [x] 用户SAFE真实探查：SH600000 H5历史6404条、SZ000001为8468条，2026-09-30～10-13两股窗口各5条；文件PyTables CLASS=TABLE、gzip与chunked结构正常。真正落盘字段按`closePrice:uint32@0`、`datetime:uint64@4`、`highPrice:uint32@12`、`lowPrice:uint32@16`、`openPrice:uint32@20`、`transAmount:uint64@24`、`transCount:uint64@32`共40字节。报告均`structural_h5record_candidate=true`，**真实Hikyuu驱动读取尚未验证**。
- [x] 上次7项只读合成测试粘贴末尾只有`Ran 7 tests in 0.719s`，缺少完整`OK`；不得误记为7/7通过。
- [x] 新增`build-hikyuu-native-h5-synthetic-canary.py`：仅以SAFE结构报告为schema证据，在`work/h5_mirror/<新目录>/`使用PyTables生成两只股票各3根**完全虚构**的独立原生日线H5，再使用h5py/PyTables核验40字节类型/偏移/CLASS/压缩及合成整数往返一致；无任何原始H5或购买Parquet读取，不动市场文件，不切换生产。
- [x] 新增7项合成回归和SAFE新报告，所有工具/测试/文档集中在H5ParquetReconciler模块内；测试及真实合成canary待用户Windows运行。详见[合成H5金丝雀验收](2026_HIKYUU_SYNTHETIC_H5_CANARY.md)。
- [x] 用户Windows7项合成canary测试完整OK（0.716秒），上传SAFE报告确认两份合成H5数值往返6根一致，详情见本页顶部；下一阶段先收集其Hikyuu运行时接口证据，再做原生驱动隔离加载。

## ★ 私有指针只读消费14/14通过，开始原生Hikyuu H5格式验真（2026-10-29）

- [x] Windows最新批量查询合成测试 **`Ran 14 tests in 6.643s`、`OK`**；包含显式SHA不读active、测试临时目录的active指针读取、锁/非法内容/中途切换。用户实际active仍未激活，原22,191条私有版本及所有市场来源不变。
- [x] 核对Hikyuu历史`H5Record`公开结构：日线`datetime:uint64`、四个OHLC价格`uint32`、`transAmount/transCount:uint64`，旧PyTables常用`/data/<SYMBOL>`。既有合成H5测试使用有符号int32价格且字段顺序与历史H5Record可能不同，**不应凭字段名就声称兼容原生Hikyuu**。
- [x] 新增严格只读`probe-hikyuu-native-day-h5-readonly.py`：1～10只股票/同年31天窗口，记录真实H5的源文件stats、数据集字段类型/偏移/顺序、PyTables标记和区间记录计数；只写模块reports/下新安全JSON，不读原商业OHLCVA或购买Parquet、不创建镜像。
- [x] 双股票真实结构报告已回传：共40字节，字段偏移和uint类型符合现场schema候选，两股各窗口5根；最新日志未包含只读7项测试最终`OK`，且Hikyuu原生驱动尚未验证，具体见上方合成金丝雀工作。
- [ ] 结构验收后再做隔离小样本原生H5及实际Hikyuu驱动读取，合格后推进完整镜像、通达信盘后增量同步；不回到无关分钟线差异机理研究。

## ★ 双股票真实批量查询通过，推进可控私有版本只读消费（2026-10-29）

- [x] 修复后Windows批量测试`Ran 8 tests in 3.334s`、`OK`；真实双股票SH600000、SZ000001在2026-09-30～10-13各返回购买1根+私有4根，共**10根**；私有prepared SHA `46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03`，一次四日现场H5/PQ复核确认H5=22,191、PQ=0，生产路由/源文件/活动指针未改。
- [x] 双股实测批次总**57.327676秒**（现场**55.981965秒**、版本核验0.754033秒、购买双股0.270772秒、私有stage解码0.2901秒）；相比单股v3的55.653345秒，第二只股票共享审计并只增加少量时间。此为两次实测，不能推广成稳定吞吐或生产低延迟保证。
- [x] 研究版批量读取增加**双重显式选择**私有活动指针的可控读取模式：`--use-private-active --confirm-private-active-read`与既有`--version-sha256`互斥，版本manifest完整校验及一次现场复核照常执行。指针缺失/非法、已知修改锁、查询期间指针SHA改变均fail-closed；无隐式激活、不动正式源和活动指针。
- [x] 活动指针读取机制新增6项后累计14项，用户Windows合成测试已完整通过14/14（6.643秒），真实private active仍未激活。后续Hikyuu只读格式审计见本页顶部。
- [ ] 验收后开始**Hikyuu原生H5镜像**的格式与读写隔离验证；购买Parquet仍为主源，不将普通HDF5列存表误判为Hikyuu可读取日线。历史分钟差异机理研究继续暂停。

## ★ 修复批量查询小写证券代码未提前拒绝的测试阻塞（2026-10-29）

- [x] 用户Windows首轮新增批量查询8项合成测试：7项`ok`、1项`FAIL`，仅`test_invalid_duplicate_and_noncanonical_symbol_rejected_before_live_scan`中输入`['sh600000']`未被拒绝，触发模拟禁止调用现场复核的`AssertionError: must not scan`；本次仅有测试数据，不代表真实批量查询通过或数据库损坏。
- [x] 批量接口与验收契约对齐：`query-parquet-primary-day-overlay-batch-readonly.py`在版本SHA核验/任何现场扫描之前拒绝非字符串、非大写规范代码及首尾空格，按批量契约仅允许`SH600000`等输入；**不改变旧单股接口大小写兼容、市场文件、私有日线版本和安全复核**。
- [x] 扩展原8项测试文件的输入异常子用例，包括小写、混合大小写、结尾空格及非字符串，添加“非法输入不能进入私有版本验真”的断言。
- [x] Windows修复后8项批量测试完整`OK`，实际双股票SH600000+SZ000001安全查询购买2根+私有8根=10根，只执行一次有界缺口复核，详情见本页顶部。私有指针仍未启用。

## ★ Windows 33/33通过、v3真实速度提升，推进批量多股票只读查询（2026-10-29）

- [x] 用户Windows三组完整`OK`：日线暂存10/10、版本prepare/activate/rollback 12/12、显式只读查询11/11，合计33/33；真实v3 SH600000购买Parquet 1条+私有overlay 4条=5条，四日仍现场核对，购买Parquet/H5原件不变、active指针未切换。
- [x] 实测批量现场审计从四次降至一次：v2总249.920308秒、现场247.758501秒；v3总**55.653345秒**、现场**54.447011秒**，本次约减少77.7%总时间。尚需解决多股票每次重复进行55秒校验。
- [x] 新建`query-parquet-primary-day-overlay-batch-readonly.py`：一个批次最多10股，同日窗、不超过31天、显式已准备版本SHA，版本stage全量重验一次、窗口内目标日H5/PQ实时有界复核**一次**、每个选定私有stage文件只解码一次，购买Parquet逐股票遵守既有优先级及总/逐股预算；不提供生产指针、不写付费K线到报告。
- [x] 新增8项合成测试已在Windows修复后通过8/8；真实SH600000+SZ000001双股票有界只读查询已通过，两个股票各5条且批量现场源审计1次。详见[已验证的批量只读查询试点](2026_PRIVATE_DAY_OVERLAY_BATCH_QUERY_PILOT.md)。
- [ ] 批量只读验证后沿主线推进可控版本消费、Hikyuu原生H5镜像与通达信盘后接入；不重复开展历史分钟线机理研究。

## ★ 私有日线现场审计4次全源扫描合并为1次（2026-10-29）

- [x] 用户Windows在新版10项合成回归中`Ran 10 tests in 7.219s`、`OK`；真实`v2`只读SH600000查询购买1条+补全4条=5条，完整总耗时**249.920308秒**，其中四日现场源复核**247.758501秒（约99.1%）**，证实阻塞在重复四次全源审计，不是Parquet本身查询（0.605372秒）。
- [x] 新增`verify_live_absence_dates`：一次31天以内、同一年、已审计目标日限定的有界`reconcile_section`，逐日核对原H5正整数数量、购买Parquet全日无键、无交集及双向差集，且源文件前后状态必须保持一致；替换私有query和prepare/activate四次重审计，保持原行情、原始stage和版本SHA不变。
- [x] 新增5项合成回归（3项stage验证、1项版本prepare、1项查询调用），测试文件总数将为10+12+11=33，**尚未经过用户Windows新版本实测**；合成测试覆盖第2个缺失日期后来出现购买Parquet键时的拒绝，以及单次源扫描保证。
- [x] 用户本机33项全部通过并回传`v3.json`，五根日线结果未变、现场一次扫描耗时54.447011秒，总耗时55.653345秒，详情见[批量现场审计操作说明](2026_BATCH_DAY_OVERLAY_LIVE_AUDIT_20261029.md)。
- [ ] 批量审计验收后沿主线开发可控私有统一Parquet消费路径、原生Hikyuu H5镜像、一次写入的通达信盘后增量；暂停无关的历史分钟差异机理研究。

## ★ SH600000真实5根日线拼接已验证，修正私有查询统计口径（2026-10-29）

- [x] 用户Windows新查询测试8项均逐项显示`ok`（`Ran 8 tests in 6.183s`，终端截取缺最终`OK`/退出码）；真实SAFE JSON：SH600000查询2026-09-30～10-13，购买Parquet返回1根、已准备私有stage返回4根，总计5根；四日现场缺失重核与全部私有stage SHA/键核验通过，原始源未修改、私有active未激活。
- [x] 发现报告把购买Parquet的`source_rows_read_per_returned_bar=28191.0`及`query_elapsed_seconds_this_invocation=0.568659`误放入组合查询摘要：该比值和时长只衡量购买Parquet阶段，并非完整统一查询成本。
- [x] 修正只读查询安全统计：分开购买Parquet源扫描、全部已准备stage的证券键校验、实际选定stage数据解码和现场来源复核计时；组合扫描比率明确标为最低已知解码量（真实此次至少28191+22191+22191=72573行级读取，不含H5/PQ重审计）；旧含混`source_rows_read_per_returned_bar`置`null`、完整查询总时间单独计算；新增两项合成回归。
- [x] 用户Windows10项测试全部通过，真实`v2`返回正确5根及完整计时，重审计耗时247.758501秒；因此下一步改为批量一次审计的v3验收，详见本页顶部。**源价格/单位策略与版本未修改**。
- [ ] 通过口径/时长审计后，研究从已准备四日stage建立受控只读消费接口，随后原生Hikyuu H5镜像、通达信盘后一次写入与镜像同步；不开展无关分钟差异机理研究。

## ★ 四日缺口22,191根真实私有版本已prepare，启动显式查询试点（2026-10-29）

- [x] 用户Windows回传10-09=5547、10-12=5549、10-13=5549三日`STAGED verified only`及各自SHA，加上此前10-08=5546，总计22,191根；四日`--action prepare`实际返回成功，`version_sha256=46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03`、`production_query_route_modified=false`。GitHub侧未重新读取商业Parquet实际内容；**版本尚未activate，非生产主库**。
- [x] 新增独立`query-parquet-primary-day-overlay-readonly.py`：显式选择已prepare的不可变SHA，逐stage SHA及来源关联验证；涉及私有日期时重跑真实整日缺失审计并核对源文件稳定性，旧购买Parquet基线优先，遇到新到货日期/重复键fail-closed；仅写模块`reports/`安全JSON。分钟与现有Parquet-only查询不变。
- [x] 新增8项合成查询回归在Windows逐项显示`ok`（末尾`Ran 8 tests in 6.183s`、未提供最终`OK`行）；SH600000/2026-09-30～10-13真实**只读**查询得到购买1根+私有4根、总5根，并发现扫描统计混淆，后续统计口径与新10项回归见本页顶部及[完整命令与证据](2026_PRIVATE_PARQUET_DAY_READONLY_QUERY_PILOT.md)。不启用指针，不自动补H5或接入生产。
- [ ] 读取试点完成后再设计独立的私有active消费策略、原生Hikyuu H5镜像以及实际存在的TDX盘后增量；不回到分钟机理细究主线。

## ★ 私有overlay日期契约修复：四日版本prepare阻塞消除（2026-10-29）

- [x] 修复 `daily_coverage` 的 `YYYYMMDD` 与已验收 stage `manifest.day` 的 `YYYY-MM-DD` 格式不一致，统一只在版本验收侧转成ISO日期；不触碰购买Parquet/H5、既有报告或暂存行情。
- [x] 修改原端到端测试的ISO预期，增加2项“紧凑报告日期→ISO暂存”和“非规范清单拒绝”回归；版本测试文件共11项。
- [x] **2026-10-29用户Windows实际测试已通过11/11**，`Ran 11 tests in 3.196s`、`OK`，含日期契约及版本准备/激活/回滚合成测试；另外日线暂存工具7/7（6.003秒）同样通过。
- [x] 用户Windows已独立暂存10-09、10-12、10-13并完成四日 `prepare`，合计22191根（私有版本SHA见本页顶部）；未启用私有指针、未完成生产补库。

## ★ 10月8日日线5546根真实隔离Parquet已完成，推进四日版本封装（2026-10-29）

- [x] 用户回传真实`manifest.json`：2026-10-08`staged_verified_not_promoted`，审计5546=实际5546；BJ339+SH2314+SZ2893=5546，Parquet及来源gate SHA-256齐备，原H5和购买Parquet未修改；上传manifest可校对计数，但云端无法直接重哈希本机实际day.parquet。
- [x] 新增`build-parquet-primary-day-overlay.py`：验证2026-09-01～10-28完整日线gate中**恰好4个**H5-only整日候选的隔离Parquet文件，逐个SHA/Schema/数量/日期/代码/市场分布及执行时源数据仍无键；生成不可变私有日线overlay版本，只有明确`--confirm-private-pointer`才会切换模块内活动指针，可回滚且不触碰外部正式行情路径。此前新增9项自造H5+Parquet集成测试，含本轮日期键修复后累计11项，**用户Windows已通过11/11**。
- [x] Windows实际独立暂存10-09=5547、10-12=5549、10-13=5549，加上10-08=5546后执行四日版本`prepare`成功，目标22191根已达到；活动私有指针尚未激活、**正式生产Parquet查询接口与H5镜像仍未建好**。见[命令与验收依据](2026_PRIVATE_PARQUET_DAY_OVERLAY_VERSIONING.md)。
- [ ] 下一阶段正式开发统一Parquet读取入口（购买原版优先、私有overlay只补空白天），然后通达信补到最新实有交易日、H5原生镜像；历史分钟线机理分析继续暂停。

## ★ 2026-09-01至10-28真实日线门槛验收并启动H5→Parquet安全暂存（2026-10-29）

- [x] `test_plan_parquet_primary_day_bootstrap_offline.py` 11项Windows实机逐项通过（Ran 11 tests in 0.023s、OK），纯离线日线gate`parquet-primary-day-bootstrap-plan-20260901-20261028-v1.json`源扫描完整、键守恒：H5=138641、PQ=116567、重叠=116450、OHLC价差0（原容差）、量/额冲突25183、H5-only22191、PQ-only117。
- [x] 2026年9月Parquet已包含所有H5候选股票的日线。H5-only 22191根全部集中于**10-08=5546、10-09=5547、10-12=5549、10-13=5549**四个Parquet全无日线的日期，混合日缺口0；**10-14～10-28的H5也未提供记录，禁止假称已覆盖最新**。
- [x] 开发**真实输出独立Parquet**的`stage-h5-only-day-to-parquet.py`：仅日线、仅已验收Parquet全日无键的H5完整源日；SHA关联gate与原扫描报告；执行时再次全日扫描核对Parquet确实没有键、H5数量吻合、源文件未发生变化；逐根数值及OHLC规则校验；仅写`work/unified_parquet/staging/<job>/day.parquet`，写后读回比对并生成独立manifest；绝不覆盖原始购买Parquet及原H5，不允许自动升为生产。7项自造行情集成测试，**用户Windows已通过7/7**（6.003秒）。
- [x] 7项暂存合成测试全部通过；真实10-08单日**5546根**暂存此前已回传私有manifest并验收计数与哈希字段（未云端重读实际Parquet内容）。[命令及正式工作协议](2026_H5_ONLY_DAY_PARQUET_STAGING.md)。
- [ ] 验收后分别暂存10-09、10-12、10-13，并设计只读baseline+独立overlay的统一Parquet active版本切换与回滚；再补真实存在的通达信盘后缺口、转换生成Hikyuu原生H5镜像。分钟数据差异机理调查保持暂停。

## ★ 最新开发主线调整：Parquet优先补齐/统一格式/通达信盘后更新（2026-10-29）

用户明确要求**停止继续研究H5与Parquet历史分钟线机理**，改为以购买Parquet主库覆盖完整历史、H5填补2026年9/10月真实空白、统一Parquet生成Hikyuu H5镜像、以后通达信盘后数据一次转换到Parquet再同步镜像。详见[正式实施协议](2026_PARQUET_PRIMARY_EXECUTION_PLAN.md)；以下旧的分钟研究记录仅为历史证据，不再作为下一步优先事项。

- [x] 2026-09-30真实重叠日线5550条OHLC在现有诊断容差内0冲突，成交量/额1241条不同；单日证据不能替代9—10月日线覆盖与更长重叠历史验证。
- [x] 首轮实现只读`plan-parquet-primary-day-bootstrap-offline.py`：从完整、仅day、2026年有界安全JSON得出逐日Parquet/H5交集、双向差集、OHLC验收、填补候选，验证逐日/全局守恒及来源哈希；混合日H5独有必须下一步逐**证券—交易日**查证，永不直接覆盖Parquet。新增11项纯合成测试，Windows待运行。
- [ ] 实机只运行2026-09-01至10-28 **day**双源只读核验及纯离线日线接受门槛，禁止自动写入；如有真实异常则先隔离。
- [ ] 实现并验收**新的独立Parquet临时分区导出**：只对明确Parquet不存在、H5数据完整且验证了字段单位/价格口径的证券日，先补2026年9—10月；原始购买文件保持只读，新增清单包含来源、哈希、批次、重复键/价格风险。
- [ ] 新统一Parquet→Hikyuu真正可读的day/5min/1min H5镜像；原始H5不能覆盖，交易日和证券键需要核对、模拟Hikyuu实际读取验收。
- [ ] TDX盘后源→统一Parquet一次更新→H5镜像增量同步，具有幂等、收盘边界和回滚；现有TDX private overlay只是JSON标准化暂存，不是原生二进制通达信导入器。

## ▶ Parquet原生241根1min可严格重构48根5min：来源内聚合已验证，进入跨日期覆盖主线（2026-10-29）

- [x] 用户上传`pq-20260930-top3-1min-5min-metadata-plan-v1.json`和`pq-20260930-top3-1min-to-5min-v1.json`；SH601579/SH688535/SH688123均有Parquet 241根1min（含09:30特殊开盘记录）、48根5min，2026-09-30的`five_start_minute_end_plus_opening_0930`候选每只**48/48根、六字段严格一致**（合计144/144），无重复键、OHLC几何异常及非有限值。忽略09:30时每只仅47/48严格一致，唯一冲突为09:30首根5min；错误的分钟开始标签整体为0/47，不能从一天样本外推全部历史。
- [x] H5原生240根1min用结束时间标记重构各自H5 5min三只股票48/48（现有诊断容差，不声称严格同值）；但H5 1min→Parquet 5min仅16/17/20根OHLC全字段、×100候选成交量9/14/15根、金额11/15/18根匹配。**两套来源的原生分钟数据各自内部可聚合，却存在显著跨来源内容差异，不能据此判断任何供应商真值。**
- [x] Parquet 5min元数据计划候选47组/5685792行/143128330未压缩字节；1min 17组/2034466行/45088212字节，与实际读取一致；合计仅选择144根5min和723根1min。只读不更改源；30M每周期候选上限未触发。
- [ ] 用户仅提供`Ran 18 tests in 2.804s`而无完整`OK`/退出码：不能标记Windows 18项测试最终整体通过；真实报告已生成并通过统计核验，未提供单独最终测试验收。
- [ ] 下一步停止反复测试2026-09-30三只股票，运行**2026-08-24单日day+5min**有界全A股候选证券交集/双向差集主核对及纯离线×100残余精确计数，用第二日期判断SZ零残余、SH/BJ残余集中和单位候选是否可复现。若扫描不完整或网格不同则如实记录，不自动修正。详见[严格重构与跨日验证协议](2026_PQ_1M5M_STRICT_48OF48_AND_CROSSDAY_NEXT.md)。
- [ ] 历史证券类型、来源真实性、单位映射、时间边界及自动生产并集依旧未认证；禁止生成或覆盖原始行情。

## ▶ H5 1min→H5 5min三股真实48/48重组通过，下一步Parquet自身1m→5m真值独立检查（2026-10-29）

- [x] 用户回传`h5-1min-vs-h5-pq-5min-20260930-focus3-x100-v1.json`：SH601579、SH688535、SH688123 H5各有完整240根1min且无重复，按分钟结束标记重组各48根5min，OHLC四字段、Volume、Amount在既有诊断容差内全部48/48匹配。改用一分钟开始标签仅有46个完整窗口且H5 OHLC全字段0/46匹配；H5结束时标得到强支持。
- [x] 同一H5 1min→购买Parquet 5min：OHLC全四项匹配16/17/20根、原成交量0/0/0、×100候选9/14/15、金额11/15/18。日成交量总比100.0但五分钟分配差异强；**不能因此宣称H5上游交易真值正确或Parquet错误**。
- [x] 发现既有`validate-parquet-1min-to-5min.py`可执行Parquet自身1min→5min五种开盘与时间标签候选（含独立09:30记录），但真实读取可能涉及上千万源行。本轮在原工具加`--plan-only`：先通过1min、5min各自Parquet footer元数据统计候选RowGroup、源行/字节上界和30M预算，无需解码市场数据，缺任一周期原件时明确标记不可验证。
- [x] 增加2项合成元数据预检回归测试，现有`test_validate_parquet_1min_to_5min.py`总18项；**用户Windows执行结果尚未提供**。[三股证据与预检命令](2026_H5_ENDLABEL_AND_PQ_1M5M_PREFLIGHT.md)。
- [ ] Windows先运行18项测试与`pq-20260930-top3-1min-5min-metadata-plan-v1.json`预检。若两周期来源文件都存在且每周期候选源行≤30M，再运行Parquet自身聚合只读验证；超预算不建议强行放宽源行上限。
- [ ] 证据回传后转向另一个历史单日（建议2026-08-24）day+5min全候选证券有界覆盖核对；避免基于9月30日三股票过拟合一分钟标签与供应商口径。

## ▶ 高冲突三股票分时核验通过：由H5原生1min重聚合进一步检测边界（2026-10-29）

- [x] 用户Windows的`test_analyze_5min_x100_focused_sessions.py`八项测试逐项显示`ok`（0.060秒）；回传元数据读取计划及真实三股五分钟分时SAFE报告。SH601579/SH688535/SH688123三股各48根5min，×100候选后成交量不一致分别39/34/33根；当日和上午/下午成交量总计均显示0%净差，毛差/H5日量分别0.615161%/1.121456%/0.784236%，相邻差值滞后一阶相关为-0.378591/-0.629266/-0.475990，只支持分配差异假说，不证明原因。
- [x] 读取计划表明为筛3只股票144根目标K线，仍需读取47个9月RowGroup，候选源行5,685,792、未压缩字节上界143,128,330，证券min-max未跳过RowGroup；这不是实际运行耗时。下一次跨日期执行前优先研究使用已完成、来源验证的现有覆盖索引。
- [x] 复用既有`validate-5min-against-h5-1min.py`增加**并行实验性**`Parquet_5min_H5_1min_volume_x100_candidate`，与不变的原始H5/PQ比较及两种一分钟时标假说同时输出，仅完整5分钟窗口比较，绝不改变原件或原容差。新增3个合成回归，原测试共11项（待Windows实测）。
- [ ] Windows运行11项合成测试及**三股票、单日的H5原生1min→H5/PQ 5min重聚合审计**；先检查一分钟文件可用性/完整窗口，再比较两种标签假设中OHLC与量额逐条匹配，不能从同一个H5来源文件多周期一致就宣称独立权威数据验证。
- [ ] 若H5原生1min不存在或窗口不足，按`not_verifiable`保留；主线转为另一个历史单日day+5min全市场有界核对，避免围绕这一个交易日过度拟合。研究说明见[真实五分钟分时和一分钟交叉检验方案](2026_FOCUSED_X100_SESSION_REAGG_1MIN_NEXT.md)。

## ▶ 2026-09-30两来源内部day↔5min成交量守恒实测：进入高残余股票分时结构核验（2026-10-28）

- [x] 用户回传`h5-internal-day5min-volume-20260930-v1.json`：H5共5550个day+48根5min完整股票日，原始同倍率字段day和5min汇总在0.1%容差内全部通过，5497组严格值相同；报告中的`baseline_day_minute_volume_agree_0_1pct=0`专指与`H5 day transCount*100`目标比较的**未换算分钟汇总**，并不是H5自身不守恒。来源×100跨供应商假设仍待认证。
- [x] 用户回传`pq-internal-day5min-volume-20260930-v1.json`：Parquet日/5分钟同时完整5560组，其中5556组原始成交量守恒，4个超0.1%容差均为BJ前缀（BJ920050/BJ920110/BJ920121/BJ920160）；另外11组只有完整48根5min而无day。未获官方上市状态、停复牌或数据商修订认证。
- [x] Parquet审计对SH601579、SH688123、SH688535确认：两来源各自day↔5min守恒，跨来源全天总量候选一致，但×100后原5min容差仍有39、33、34根冲突。这说明**日总量近似相等仍可能五分钟时间分布差异明显**；尚不能断言具体错误源或边界原因。
- [x] 找到并修正现有`analyze-5min-x100-focused-sessions.py`仅接受单`5min`报告的限制，现在也接受已完成的day+5min单日综合报告，严格核验day伴随分区一致性，新增3项纯合成测试（共8项，Windows待运行）。[真实证据及验收命令](2026_H5_PQ_INTERNAL_VOLUME_AND_FOCUSED_SESSIONS.md)。
- [ ] Windows先运行8项合成测试，再运行**元数据计划模式**查看3只重点股票的Parquet候选RowGroups；成本可控后再运行真实分时守恒核验，输出上午/下午净差、毛差、差额抵消和相邻区间差值诊断，不能直接当已证明分钟边界错位。
- [ ] 获得重点股票诊断后，主线转向其他月份的**有界day+5min覆盖核对**，检验SZ全匹配及BJ/SH集中冲突是否跨日期成立；自动数据合并及单位映射认证仍关闭。

## ▶ 五分钟×100真实精确残余报告已验收：后续改查来源内部日线守恒（2026-10-28）

- [x] 用户已上传`h5-pq-20260930-x100-residual-exact-v1.json`，由修正后的离线triage工具从既存`day/2026+5min/2026`双周期完整安全JSON生成：`separate_day_section_consistency_checked=true`，`exact_mask_evidence_present=true`，`source_report_scan_complete=true`，未读取或修改源OHLCVA。
- [x] 8类精确残余字段掩码重新核算：无冲突265708，仅volume29，仅amount3，仅price77，volume+amount257，volume+price22，amount+price1，三者均冲突303。合计266400；volume边际611、amount564、price403、任意冲突692，均守恒。
- [x] 进一步证实**本日残余692条只在BJ/SH代码前缀组**：BJ 184、SH_688_689 155、SH_other 353、SZ_300_301 0、SZ_other 0；这只是2026-09-30单日事实，不能外推全市场/其他月份，亦不是证券上市身份认证。
- [ ] 尚未收到**PR #99修正后10项合成测试**完整用户日志：新离线真实报告确实生成成功，但不替代全部测试验收。
- [ ] **优先主线**：让用户执行现有`inspect-h5-day-vs-5min-volume.py`及`inspect-parquet-day-vs-5min-volume.py`，验证各自日线/5min成交量口径；不再扩建重复的离线残余分析工具。
- [ ] 在两个独立来源内部报告收到后，再对另一个分散日期运行现有有界day+5min主核对，比较×100假说、SZ全匹配是否稳定、BJ/SH残余是否持续；原始数据与生产自动并集保持关闭。详细证据见[单日精确掩码验收记录](2026_H5_PQ_0930_EXACT_X100_RESIDUAL_MAINLINE.md)。

## ▶ 2026-09-30真实H5/Parquet单日day+5min全扫描通过；成交量×100假设成为主线（2026-10-28）

- [x] 用户回传`h5-pq-overlap-20260930-day5min-v1.json`和Markdown；两个分区均完整且无issues。day H5 5550/PQ 5560/匹配键5550/H5-only0/PQ-only10/量价冲突1241（价格0）；5min H5 266400/PQ 267408/交集266400/H5-only0/PQ-only1008/量价冲突265181，其中PQ-only来自21组全日48根的证券日，不能未经证券身份认证就当真实交易漏数。
- [x] 5min原始成交量冲突265181；H5 Volume×100**仅作为内存诊断候选**减少至611，解决264570、未破坏原已匹配，综合价格/金额/量残余692。真实完整JSON还包含按字段精确互斥掩码：none265708、volume29、amount3、price77、volume_amount257、volume_price22、amount_price1、volume_amount_price303。已用本轮上传JSON实际验证全局/前缀/日分组和边际统计守恒。
- [x] 修正`triage-5min-x100-residual-offline.py`：兼容真实完整day+5min合并报告且安全拒绝不同日期/年份不完整伴随分区；如精确8类字段掩码齐备则校验后输出精确类别，老报告无精确数据仍保留诚实的上下界；扩展10项纯合成回归，尚待Windows。
- [ ] Windows运行10项离线工具回归，并从已有双周期真实JSON生成`h5-pq-20260930-x100-residual-exact-v1.json`。无需重扫巨大的付费5min源文件。
- [ ] 复用现有`inspect-h5-day-vs-5min-volume.py`和`inspect-parquet-day-vs-5min-volume.py`对同日分别核验来源内部成交量守恒，不能把×100假设直接写入统一查询或格式互转。
- [ ] 最终按有界日期窗/不同月份扩大样本，再单独核对1min含09:30特殊条，研究21只完整PQ-only股票日的正式证券身份及实际覆盖理由；未经独立证据不能自动补库。

## ▶ 字段级跨报告判定已实机成功，恢复双源覆盖差集与冲突实证主线（2026-10-28）

- [x] 用户Windows新一轮11个`test_evaluate_tdx_parquet_case_evidence_readonly.py`测试逐项显示ok（0.620s；粘贴末尾缺完整OK行）。已实际上传SH600000/2026-07-16和SH600519/2026-06-30两份字段级SAFE输出：均保留各一根分钟High异常，5min跨源六字段通过，SH600519额外保留两个日线成交量冲突。来源交叉核验通过，自动生产合并/原始改写仍关闭。
- [x] 已审查既有`reconcile-local-a-share-h5-parquet.py`主核对入口，确认支持有界日期单日窗口、day/5min分周期、A股候选集合、SQLite有界scratch、H5-only/Parquet-only/交集/量价冲突及5min完整/局部股票日缺失汇总；**无需再复制开发新的主核对程序**。
- [x] 新增[返回H5/Parquet覆盖主线的实机运行协议](2026_H5_PARQUET_RESUME_BOUNDED_OVERLAP.md)：先对2026-09-30单日的day和5min运行真实只读核对，并保留JSON/Markdown，仅模块内临时scratch。
- [ ] 用户Windows执行单日day/5min主核对，回传真实报告；先检查scan_complete、精确交集、H5-only、Parquet-only、数值冲突及5min stock-day缺失分类。若遇性能瓶颈，再据实定向改造，避免无界全年度扫描。
- [ ] 后续以同一天单独核验1min并显式保留Parquet 09:30特殊来源语义；待来源覆盖与单位问题被充分实证解决后才规划可追溯/可回滚的新库，不能自动覆盖H5或购买Parquet。

## ▶ 完成单分钟High峰值机制实测；落实保守的跨周期字段级准入诊断（2026-10-28）

- [x] 用户Windows实际执行`test_triage_tdx_parquet_isolated_high_readonly.py`：9项全部OK（0.303s）。两组真实机制报告证明SH600000/2026-07-16及SH600519/2026-06-30各仅1根1min High不同，这根分钟在两来源中都不是对应5分钟区间最高价，5分钟High未受影响；不能因此宣告1min一致。
- [x] 新增`evaluate-tdx-parquet-case-evidence-readonly.py`，只读三份现有SAFE报告（minute preview、High机制、TDX/Parquet day/5min跨源），交叉核验股日、TDX原件SHA、购买Parquet的stat-only清单及六字段匹配次数；将分钟High异常与Parquet日线成交量独立输出，任何结果仍不允许生产合并。
- [x] 开发容器用11个合成测试成功验收；并使用两只股票各三份**真实已上传安全JSON**离线实测：SH600000分钟孤立High/日线Volume一致，SH600519分钟孤立High/日线Volume双重冲突；没有读取或修改任何本机原始行情。详细研究见[字段级证据判定](2026_TDX_PARQUET_FIELD_EVIDENCE_DISPOSITION_V1.md)。
- [ ] 用户Windows执行新增11项测试及两组SAFE报告的字段级一致性判定；若来源指纹漂移则原样报告并拒绝复用证据，切勿修改行情凑通过。
- [ ] 此后停止重复研究单根High聚合，从H5和Parquet重叠覆盖/差集证据主线推进；日线Volume差异单独保留，未有新证据前不选择替代源或静默覆盖。
## ▶ 单High反例完成TDX/Parquet五分钟与日线三角验证：继续定位分钟极值机制（2026-10-28）

- [x] 用户上传SH600000/2026-07-16与SH600519/2026-06-30真实跨周期安全报告：两股TDX原生1min/5min/day内部各字段诊断一致，TDX5min vs购买Parquet5min六字段48/48匹配；但前述各一根1min High仍不同，不得因高周期吻合忽略分钟错误。
- [x] 发现贵州茅台`tdx_daily_vs_parquet_daily.volume` 0/1、最大相对差1.99456e-05；且`parquet_5min_aggregate_vs_parquet_daily.volume` 0/1、最大相对差2.52474e-05；五分钟跨源volume 48/48。这是日线成交量独立问题，需和单分钟High分开追踪，不可擅自断定数据源错误。
- [x] 新增`triage-tdx-parquet-isolated-high-readonly.py`，真实只读重新读取两来源分钟与五分钟，统计不匹配高价是否控制各自五分钟区间最高价，并同时复核TDX1m→5m、购买候选1m→5m与跨来源5m六字段，只输出安全聚合和来源指纹；新增9项合成测试待本机执行。
- [ ] Windows执行新增9项测试并对两股两个日期生成真实机制安全JSON；确认单分钟High差异是否被同组其它分钟High覆盖，或属于并列极值；不输出具体分钟标签/价格明细。
- [ ] 另行研究贵州茅台Parquet日线volume相对5分钟汇总不匹配的来源版本及量额口径。所有反例仍保持`eligible_for_automatic_production_union=false`，不给任何源文件或生产查询写入权限。

## ▶ 两个单High孤立反例证据已收齐，下一阶段跨周期三角校验（2026-10-28）

- [x] 用户回传两份只读安全详细报告：SH600000/2026-07-16与SH600519/2026-06-30的首根及购买Parquet5min全部六字段匹配；余下239根除High之外其他五字段全部239/239；High各238/239、完整240根High各239/240。最大High相对差分别0.0011299866与0.0000169735；成交量额全部238/239零偏差，失败仍必须原样保留。
- [x] 判定**不是开盘归并失败，也不是量额口径失配**；当前只证明两个具体股票日的普通交易一分钟High跨源不同，尚未定位到分钟时间、归因数据源、判定复权或供应商错误。
- [x] 新增[孤立High反例跨周期三角诊断](2026_TDX_PARQUET_ISOLATED_HIGH_CROSSCYCLE_TRIAGE.md)：复用既有`audit-tdx-vs-parquet-day5min-readonly.py`，要求TDX原生1min→5min→day自洽，并与购买Parquet原生5min/day做独立跨源比对；提供2条单行PowerShell，保留只读安全边界。
- [ ] 等待2份真实日/5min跨源安全JSON。若五分钟High吻合，孤立一分钟High错差仍不自动放行；若五分钟或TDX内部自身不一致，进一步核验来源及历史修订，不随意放宽容差或修正任何数据。
- [ ] PR #92修正的边界调查9项单测仍无用户Windows重新运行回执，不宣称全通过。

## ▶ 首批异常边界调查出现两组真实反例：转向逐字段定位（2026-10-28）

- [x] 用户回传`tdx-pq-minute-boundary-survey-20260716-20260630-v1.json`，共4组不同股票日：诊断匹配2、不匹配2、不支持0。SH600000/2026-07-16和SH600519/2026-06-30的失败门槛完全一致，仅`remaining_239_match_native`及`candidate_240_matches_native`；开盘首根与购买原生48根5min比较均未失败。SZ300750/2026-07-16、SZ000001/2026-06-30诊断通过；整批结论`anomaly_observed_do_not_apply_mapping`，保留失败样本，禁止自动标准化。
- [x] 形成[真实两组反例研究记录](2026_TDX_PARQUET_REAL_BOUNDARY_COUNTEREXAMPLES.md)；优先运行现有只读单股预演，对两组失败生成完整六字段统计，区分价格与量额失配、不匹配条数和最大相对误差，不额外引入新数据写入流程。
- [ ] 等待两份仅含安全统计的反例详细JSON；在证据明确前不得指称具体差异原因，更不得修改原始行情、放宽容差或删除09:30记录来人为制造匹配。
- [ ] PR #92修复了9项边界调查合成测试中的隐私字符串误报，但Windows修复后的测试结果尚未回传，不宣称已验收。源文件与生产查询全程未变。

## ▶ 已验收10组安全候选与原始审计交叉来源；启动异常规则边界调查（2026-10-28）

- [x] 用户Windows已经运行新增10组候选预演cohort合成测试8/8：Ran 8 tests, OK（0.445s）。
- [x] 用户上传tdx-pq-normalization-preview-cohort-ten-stockdays-v1.json：unique_stock_days=10、distinct_symbols=4、distinct_dates=4，原始开盘审计cohort交叉来源核验通过，all_supplied_previews_match=true，verdict=exploratory_preview_target_met_not_certified；来源仍Parquet stat-only，不获生产认证。
- [x] 新增survey-tdx-parquet-minute-rule-boundaries-readonly.py，实验规则ID固定experimental_tdx_end240_from_pq241_opening_fold_v1，支持显式最多12组SH/SZ股票日的真实只读预演，按通过/六字段不一致/缺失或不支持来源三类汇总，不输出异常原始消息、来源绝对路径或行情数值；新增9项纯合成单测（待Windows）。
- [ ] Windows先执行新9项合成测试；再挑选此前10组以外的历史股票日验证边界（建议2026-07-16、2026-06-30），无论异常还是成功均按安全JSON回传；不在报告里断言具体停牌/除权原因。
- [ ] 基于真实不支持/异常结果制定版本化准入策略；如无反例，继续按时间和板块扩样。未经用户授权不得落库、修改源文件或开启统一生产查询。
## ▶ 首轮标准化预演10/10真实通过；进入双批次来源交叉验证（2026-10-28）

- [x] 用户Windows已执行8项只读241→240内存预演合成测试：Ran 8 tests, OK。
- [x] 用户上传剩余9份真实候选预演安全JSON；与此前首份合计10个股票日、4只股票、4日期、2个月。全部四道六字段门槛匹配；无一导出行情、修改原始数据或启动生产并集。全240分钟最大价格字段相对差5.08e-08、成交量0、成交额1.07e-08。
- [x] 新增安全预演汇总脚本与合成测试：可以用已生成的10组原始开盘审计cohort做独立来源指纹与样本集合交叉核验，拒绝重复、伪造不一致安全标志、六字段统计与布尔结论矛盾、TDX SHA/购买Parquet stat-only指纹不一致。
- [ ] Windows运行8项新汇总合成测试，并实际执行新十组预演安全汇总交叉检查；不能将用户的既有预演8项成功误记为新汇总工具已经通过。
- [ ] 然后推进异常日期、停复牌、更多历史样本的显式拒绝条件和可审计映射策略版本；**生产自动材料化、私有overlay与源文件改写仍禁止**。
## ▶ 首份真实241→240分钟预演验收通过；扩大剩余九组（2026-10-28）

- [x] 用户回传`tdx-pq-sh600000-20260930-normalization-preview-v1.json`：原始Parquet241分钟→候选内存240条；首根与TDX(1/1×6)、后239与TDX(239/239×6)、完整240与TDX(240/240×6)、候选聚合与Parquet5min(48/48×6)均达诊断容差，量额全240最大相对误差为0，原始数据与生产查询未改。`diagnostic_candidate_matches_both_sources_not_production_certified`。
- [x] 更新[只读预演操作说明](2026_TDX_PARQUET_241_TO_240_READONLY_PREVIEW.md)：单行PowerShell批量运行其余9组已验证原始开盘证据的股票日，逐案输出私有安全报告；任何一案失败停止，不覆盖旧文件。
- [ ] 实际执行剩余9组候选预演，回传首个差异或完整安全结果；新8项合成测试暂未获Windows输出，不宣称通过。暂不材料化任何240候选序列。

## ▶ 新一阶段：241→240分钟只读内存候选视图与双源一致性门槛（2026-10-28）

- [x] 收到用户实际运行的10股票日安全汇总JSON，核对sample=10、symbols=4、dates=4、
all_supplied_stock_days_match=true，判定exploratory_sample_target_met_not_certified；
逐股日的首根聚合、余下239条和原生5分钟48条均匹配。
- [x] 新增tools/preview-tdx-parquet-1min-normalization-readonly.py：仅一次
有界读取/核验TDX和购买Parquet来源，严格目标日期时间网格，241条
Parquet原始记录全部在内存候选240 END条中参与一次；四类6字段指标独立验收，
对异常拒绝材料化且永不写原始行情或缓存，源追溯仅输出安全指纹和聚合统计。
- [x] 增加8项纯合成回归（成功、非零开盘、TDX首根不匹配、5min不匹配、
漏/重复分钟、坏OHLCVA、来源验收、安全CLI输出不能覆盖）。
- [ ] Windows执行新脚本测试并对SH600000/2026-09-30生成首份
只读候选预演JSON，确认映射语义和四道门槛成立；当前未获本机测试结果。
- [ ] 继续验证异常交易日和更长历史/板块/复权/停牌情况，再讨论需要显式
授权的版本化私有暂存、回滚演练与正式生产查询接入；本阶段绝不落库。
## ▶ 完成10组真实股票日跨行业、跨月份证据复核（2026-10-28）

- [x] 用户已验证并上传SH600000和SZ000001的2026-09-28/29/30六个股票日的完整安全分钟报告及六样本汇总（探索目标达成，生产认证关闭）。最新又上传SH600519贵州茅台和SZ300750宁德时代的2026-08-17与09-30共四份真实只读JSON。
- [x] 已独立核对最新四份报告：每股日TDX原生1min240、购买Parquet1min241/5min48；TDX09:31 vs Parquet09:30+09:31聚合六字段容差匹配；余下239条六字段逐根匹配；重建后240根六字段全匹配；Parquet额外09:30计入后48根五分钟六字段全匹配。累计**10组独立股票日、4只股票、4个日期、2个月、覆盖银行/白酒消费/新能源电池**。这些属于部分历史数据实证，不能直接外推到停牌复牌、除权、不同版本或全A股。
- [x] 新增[十组跨行业验证记录](2026_TDX_PARQUET_10_STOCKDAY_CROSS_SECTOR_EVIDENCE.md)与一次性汇总10份reports安全JSON的单行PowerShell命令。预期`exploratory_sample_target_met_not_certified`；**该10组汇总命令尚待Windows验收，不能把逐组报告等同于已执行的十组汇总。**
- [ ] 下阶段转向**严格只读的候选标准化预演**，明确`raw_241_opening_plus_end`→`candidate_tdx_240_end`仅内存规则：首09:30+09:31完整OHLCVA合并、余下239根保留，共同源记录可追溯，出错拒绝。不写付费Parquet/TDX/H5、不启用私人暂存/生产自动覆盖。
- [ ] 继续捕获异常日期、停牌复牌、不同年份和其他行业反例，之后再讨论用户明确许可的版本化私有暂存、原始回溯与回滚控制。

## ▶ 单个真实股票日TDX首根09:31合并完全吻合；推进跨样本复核（2026-10-28）

- [x] 用户回传`tdx-vs-pq-sh600000-20260930-first-minute-merge-v2.json`：TDX09:31 vs Parquet09:31直接比较，开盘价、成交量/额不匹配；TDX09:31 vs Parquet09:30+09:31聚合后六字段1/1容差通过、量额误差为0；其余239根六字段239/239全部通过；重建全240根六字段240/240全部通过、量额误差为0。**真实数据支持一个股票日的首分钟聚合规则，但没有证明全市场通用。**
- [x] 新增`summarize-tdx-parquet-minute-evidence-readonly.py`证据汇总：读取已有安全JSON（<=12个），复核原生全源SHA、购买Parquet stat-only来源指纹、样本股日/分钟数/六字段匹配、自证安全边界；任何差异独立标记，不会静默宣称合并成功。探索性门槛为至少6个股票日、2只股票、3个日期，仅作后续研究范围提示，**绝非生产转换认证**；新增6项合成测试待Windows。
- [ ] 用已存在的SH600000/2026-09-30安全报告运行一次证据汇总，预期判定样本太少；再优先尝试2026-09-29和09-28等已收盘日期的只读分钟跨源审计；如TDX文件或Parquet该日数据/241根网格缺失，原样报告原因，不强行补齐。
- [ ] 增加其他股票同一/不同日期的来源抽样、处理特殊开盘成交和异常日期；再讨论用户显式授权、版本化私有增量暂存与可回滚对账。生产历史Parquet/H5/查询仍不更改。

## ▶ 真实241根开盘记录非零：进入TDX首根09:31是否合并的证据复验（2026-10-28）

- [x] 用户真实`tdx-vs-pq-sh600000-20260930-1min-opening-audit.json`：TDX240 vs Parquet241，high/low/close各240/240，open/volume/amount各239/240；Parquet额外09:30有非零volume/amount、不同开盘价，纳入第一根5min后Parquet聚合48根六字段全吻合，不纳入则第一根开盘价及量额不匹配（首五分钟成交量相对误差约4.1046%）。这只证实该股票日的开盘记录归属差异。
- [x] 扩展既有分钟只读工具：同时计算`TDX09:31 vs Parquet09:31`、`TDX09:31 vs Parquet09:30+09:31聚合`、剩余239根、按合并假说重建240根的六字段比较。只输出容差匹配数/误差/比例；不会自动修改、丢弃或补造任何行情数据，仍禁用自动并集；新增2项正反两面的回归测试（共10项）。
- [ ] Windows执行10项合成回归和真实同日单股安全复验，回传`reports/tdx-vs-pq-sh600000-20260930-first-minute-merge-v2.json`，判断原生首根是否确实含额外开盘记录，**不能把一日假说外推全股票/历史**。
- [ ] 下一阶段抽取不同日期和股票做定向核验、验证独立日期下特殊开盘量额及复权/停牌等边界，再决定正式可审计标准化规则与用户显式授权的隔离版本暂存/回滚。统一生产查询暂不接入。

## ▶ 用户真实跨来源day/5min一致；进入TDX240 vs Parquet241开盘分钟条核验（2026-10-28）

- [x] 已收到用户`tdx-vs-pq-sh600000-20260930-day5min.json`真实安全JSON：SH600000在2026-09-30的TDX日线/Parquet日线各1、五分钟各48根；逐5min四个价格字段48/48匹配、最大相对差约4.83e-08；volume每根严格相同；amount最大相对差1.048e-07；日线OHLC完全相同、volume相对差1.356e-07；Parquet 5min→日线自身六字段均匹配。**两个独立源在这个股票日具有高度一致性，尚未认证多日多股。**
- [x] 增加`audit-tdx-vs-parquet-1min-opening-readonly.py`，读取TDX原生`.lc1`单股单日240结束标签和Parquet同日1min（241条、单独09:30开盘条）及5min（48条起点），对240共享结束标签逐根量价对账；另外验证Parquet第一根5min**含/不含09:30条**两种聚合假说，输出字段容差匹配数、误差和量额倍率及开盘额/量是否零，绝不静默删补09:30或修改任何源数据。报告仅安全统计、SHA和stat来源摘要，`eligible_for_automatic_production_union=false`。新增8项合成测试待Windows。详见[运行指南](2026_TDX_PARQUET_1MIN_OPENING_READONLY_AUDIT.md)。
- [ ] 用户执行Windows`py_compile`、8项新测试及真实SH600000/2026-09-30只读分钟开盘对账，将reports安全JSON回传，以判定是否存在可解释的额外09:30记录贡献。
- [ ] 在确定241特殊记录语义及多只股票多日泛化证据后才进入明确源优先级、可回滚的**用户显式授权的私有增量暂存**；不启动生产Parquet/H5自动覆盖。

## ▶ 正式跨来源实证：TDX vs 购买Parquet 48个5分钟区间和日线（2026-10-28）

- [x] 用户新上传`tdx-native-sh600000-three-period-20260930-audit.json`：SH600000/2026-09-30的TDX日线1、1min240、5min48，1min→5min 48组OHLC/volume完全吻合；amount最大相对差约1.048e-07；5min与1min分别对TDX日线所有六字段容差通过，volume比约1.00000014。**TDX内部三周期数值守恒已在一个真实股票日上验证**；不代表TDX与Parquet/H5等外部源一致。
- [x] 新增`audit-tdx-vs-parquet-day5min-readonly.py`：一只股票一天、TDX三周期重新全文件读+SHA、Parquet只有day/5min的内存查询、每来源读取有上限；Parquet原5分钟开始标签+5m才与TDX结束标签配对。强制48:48与1:1，全六字段相对误差/容差匹配数、量额比例及Parquet内部5min→day守恒；输出只有安全统计、Parquet源清单stat-only指纹，额外复验真实文件stat未变化，绝不把TDX240根冒充Parquet241根、不自动跨源换算或补值。新增8项合成测试待Windows。详见[跨来源协议](2026_TDX_PARQUET_DAY5MIN_SOURCE_PARITY_READONLY.md)。
- [ ] 用户在Windows上对`D:\software\TDX\vipdoc\sh\...`与`D:\stock\AllCycleAStockData`执行同日2026-09-30的**实际跨供应商对账**，只回传reports安全JSON。若差异存在，按OHLC、volume、amount分开定位，禁止将单日一致性扩展为全历史认证。
- [ ] 只有在实测跨源价格、量额单位与时间约定后，才计划受人工批准的TDX私有版本化增量候选接入；Parquet 241条特殊09:30仍单独保留待验证，**目前不接入自动融合/覆盖**。

## ▶ TDX真实240/48终点标记已验；三周期OHLCVA只读守恒核验进入主线（2026-10-28）

- [x] 用户Windows真实原生`SH600000`、2026-09-30：`sh600000.lc1`为**240根，1min_end_240**、5/11至10/13共25,200根；`sh600000.lc5`为**48根，5min_end_48**、同期5,040根。两源的source content SHA、顺序、稳定读取证明就绪。日线真实源1999-11-10至10/13可读，`2026-09-30`这一天是否有数据将由新三周期工具实际核验。
- [x] 新增`audit-tdx-native-three-period-readonly.py`，三文件一股一天，有限64MiB/源且内容双读SHA检查，**只接受原生1min_end_240与5min_end_48**，逐5根与1根5min对齐，执行1min→5min(48组)、5min→day(1组)、1min→day(1组)的OHLCVA守恒及系统性量额倍率诊断。安全报告仅相对误差/比例/源hash，不含价量额/个人绝对路径；不写工作区、不碰Parquet/H5/TDX原件、不入生产查询、不自动把Parquet 241根补凑TDX 240根。
- [x] 7项纯合成测试在开发容器以模拟现有原生probe接口执行`OK`：完全一致、100倍成交量差、价格单格错误、241根/缺根拒绝、错周期、源SHA跨扫描改变、报告只新建且无价量额。**Windows真实probe联动与完整test*.py尚未核验**；见[验收步骤](2026_TDX_NATIVE_THREE_PERIOD_READONLY_NUMERIC_AUDIT.md)。
- [ ] 用户本机对2026-09-30三个真实TDX原生文件运行新只读对账并回传模块`reports/`中安全JSON或确切错误，确认收盘价、量额比例，判断单位/口径/精度而不自作换算。
- [ ] 若三周期一致性或差异可解释，再设计TDX原生文件→受控标准化私人暂存层的单日显式写入流程及回滚，**正式Parquet历史/H5核验回退/TDX增量统一查询仍未实现**。

## ▶ TDX本机原生日线的2004日期边界误拒绝：已修复（2026-10-28）

- [x] 用户Windows真文件`D:\software\TDX\vipdoc\sh\lday\sh600000.day`出现`Native TDX source calendar is outside 2004..2100`。因单文件探测扫描所有历史，原版错误地把分钟线的2004压缩日期纪元用于**YYYYMMDD日线**，早期日线被误判越界。
- [x] 代码现按周期分离年份：`.day`1990～2100，`.lc1/.lc5`2004～2100；保留合法日期、全文件顺序、OHLCVA的严格验证，新增错行序号+年份定位和1999～2026跨年合成测试及越界年负测试。详见[修复背景及验收](2026_TDX_NATIVE_READONLY_PROBE_V1.md)。
- [ ] 用户本机拉取后先`py_compile`、TDX新测试，再用**相同真实日线文件**只读重跑。只需回传reports安全JSON/错误文本，不上传真实行情原文件；若仍报错，依据真实索引+日期分析后继续，不盲目降低价量校验。
- [ ] 待真实日线验收，再验证分钟线布局与标签、来源单位/复权，并推进独立暂存接入；**不自动接入生产历史Parquet/H5**。

## ▶ 原生TDX .day/.lc5/.lc1只读适配首步（2026-10-28）

- [x] 新增`tools/probe-tdx-native-readonly.py`：仅显式单文件/单股票/单日期的常见32字节小端通达信原生`.day/.lc5/.lc1`二进制，只读按序扫描最多64MiB并计算完整内容SHA；严格源格式/日历/时间键递增/OHLCVA，按day 1、5min 48-start/end、1min 240-start/end或241-opening-plus-end识别**候选时间标签网格**。安全JSON不输出任何bar及分钟键、不生成标准化数据或自动合并、不进入生产查询；9项合成测试需用户Windows验收。参见[原生探测协议](2026_TDX_NATIVE_READONLY_PROBE_V1.md)。
- [ ] 验证Windows完整合成测试通过，再对**用户已合法拥有的**本地TDX原生文件执行一次有界只读探测；输出只传模块reports/安全JSON、无需上传真实二进制价量额。用户若无TDX本地文件，不能声称已接入真实TDX。
- [ ] 在明确真实供应商的日线/1min/5min时间网格与量额单位后，才能做只读跨周期守恒和**单股票/单日**适配器，并将标准化协议升级至支持与真源一致的时间标签；入独立暂存必须用户显式选择且能回滚；不得无证据自动覆盖历史Parquet/H5。
- [x] 前轮Windows`test_tdx_postclose_private_overlay.py`最初8项7过1项测试断言文字不匹配；PR #78已修正该项并合并，但**尚未收到用户新8项或全套Windows OK日志**，新一轮仍需回传。

## ▶ 主线推进：私有TDX盘后单股票日暂存v1及来源回滚（2026-10-28）

- [x] 用户新`pq-202609-three-symbol-month-shared-5min-offline-audit.json`实测：90证券日组合，3,024五分钟键，63个完整48键日、每股21日/1,008键，9个共同零键日，9/30逐组基线比对`single_day_reference_exact_membership_verified=true`，源未访问/未改动。**09-25零键是2026年中秋节休市**，沪深交易所2026-09-17正式公告09-25至09-27休市、09-28恢复交易。消除该日期疑点，不再为了其运行完整源扫描。
- [x] 决定停止持续扩张尚未证明生产收益的月度完整索引；正式转向**Parquet历史优先、H5仅作核实缺口候选、TDX盘后增量单独暂存与回滚**。
- [x] 新`tools/tdx-postclose-private-overlay.py`：仅支持**显式用户标准化JSON（非TDX原生二进制）**；严格校验指定单证券日day/5min/1min完整时标、OHLCVA及出处；`validate`零写入；`stage --allow-private-copy`仅向`work/`创建不可变真值版本+源字节/记录内容SHA和活动指针；`rollback`回到上一活动版本或停用，所有旧版本保留。并发锁/防目录逃逸/写入报告独占，安全元数据仅存`reports/`，绝不自动接入默认查询或碰付费历史源。新增8项合成测试、独立协议文档；本机用户Windows尚未验收。
- [ ] Windows先跑新测试和全仓测试（此前WinError32单测完整OK尚缺明确日志），如无TDX本地**已规范化**样本则暂不执行真实stage。后续需要用户提供TDX真实盘后来源格式信息**但不必上传有版权的真值文件**，设计只读TDX .day/.lc1/.lc5 adapter，验证标签、量额单位、复权和交易所日期。
- [ ] Stage还不是入主库：下轮先做用户本机的day/1min/5min三周期候选守恒和来源冲突审批，再增加**可选的生产查询overlay优先级**及稳定回滚。禁止将未经认证的TDX新值自动覆盖Parquet历史记录；所有新写入只可在独立库、不能修改购买源/H5原件。

## ▶ 2026-09整月多股票单次键扫描已实证；先离线核验而非立刻建设生产索引（2026-10-28）

- [x] 实测用户`pq-202609-three-symbol-month-shared-5min-keys.json`：SH600000/SZ000001/SZ300750各21有键日期、均48条键；总3,024键/90股票日；另9个共同零键日期(09-05/06/12/13/19/20/25/26/27)。9月25日零键需独立交易日历核对，暂不判定缺失/休市。9/30三股精确行组18/19/17及每组键数均与单日真实JSON一致。
- [x] 全月共享47组/5,685,792源键行只扫一次；键列2.357598s、完整规划3.900790s；相对按股票各扫一次的17,057,376源键行理论避免11,371,584，但**这不是物理IO/同次A/B省时量**。每只股票跨月都有键的RowGroup并集均达47/47：**整月扫描的按证券行组剪枝收益可能为零**；精确locator适用日或小窗口。
- [x] 新增零源I/O`audit-parquet-month-shared-key-report.py`，验证2～8股完整日期笛卡尔积、键数/分组/源行预算守恒、原安全标志、统计签名，并可选将9/30每股完整定位列表与旧单日报告逐项比较，生成不含个别时间戳/OHLCVA的紧凑安全摘要。新增5项合成测试待实测。详见[真实月度结果](2026_09_MONTH_KEY_SCAN_REAL_EVIDENCE_AND_OFFLINE_AUDIT.md)。
- [ ] 先完成用户Windows完整单测（先前Win32句柄修复还缺终端OK证据）+离线月度安全报告审计；只回传新JSON/终端结果，不再重跑5.7M键列。
- [ ] 在明确多证券短窗口冷查询的真实应用频率之前**暂停未经签名的持久月索引自动剪枝**。优先推进Parquet历史主源、H5对照和通达信盘后独立可回滚增量层；对9/25零键进行交易日历单点核验即可。

## ▶ 已实证3股票单日共享完整键扫描，推进单月多日期有界预览（2026-10-28）

- [x] Windows`pq-20260930-three-symbol-shared-5min-keys.json`：SH600000/SZ000001/SZ300750同日均48键（共144），精确非空组分别18/19/17，三者非空组并集38。原各自Footers均47组/5,685,792行，合计独立上限17,057,376行；实际共享仅47组、5,685,792键行扫一次、总3.113772s（键列2.104793s），源stat稳定、所有Reader显式关闭。**理论行预算减少11,371,584（66.7%），并非磁盘IO/真实多次运行计时对照**。旧SH600000单股18组48键与本轮相同。
- [x] 新增`plan-parquet-5min-multiday-shared-keys.py`：2～8只股票×同自然月1～31个日历日，统一Footer候选并集和完整源行预算、**只读取一次`ts/symbol`，按每股票/日期输出精确键行组清单**。只读源，严格总键/每证券日/行组/源行上限及源stat、跨组重复时间、Win32资源生命周期；**不构建持久生产索引、不读取H5或OHLCVA、不修改默认查询**。新增7项合成测试待Windows。详见[单月多日试点](2026_ONE_MONTH_MULTIDAY_SHARED_5MIN_KEYSCAN_PLAN.md)。
- [ ] 先确认前轮Win32 334项基础测试通过，再跑新7项/全套。对2026-09完整月三股票一次只读两列扫描，上传安全JSON，确认9月30每股48键且行组及逐组计数和同日实测一致，分析其他日期包括周末0键；**不要凭整月预览直接推断全市场历史可靠**。
- [ ] 若真实单次整月成本可控且跨日完整性验证通过，再考虑完整可审计、可失效、可回滚的只索引键持久层；不把用户可编辑的JSON直接升级生产剪枝。之后优先推进Parquet历史主库+TDX盘后独立增量层，避免无限支线性能调优。

## ▶ 从单证券定位走向多证券共用键扫描：先做2～8只同日试点（2026-10-28）

- [x] 新增`plan-parquet-5min-multisymbol-day-keyscan.py`，只读同日2～8只A股的5min源：先用全部source Footer建立**多股票候选RowGroup并集**并预检原始候选源行与行组完整上限，再只扫描一次`ts/symbol`键列，按股票输出真实非空组、键数及与分别建单股票索引相比的理论源行上限节省。不产生可复用生产索引、不读取价量额、不触碰H5/Parquet原件/2025V3索引/正式查询，自动显式关闭全部读取器。新增7项合成测试（含与旧单股票`plan()`输出严格比较和Win32资源释放）；待Windows验收。
- [ ] 优先跑全部合成测试，阻止既有`WinError 32`的遗留问题。随后在`SH600000,SZ000001,SZ300750`同日2026-09-30上做一次共享键扫描，回传安全JSON。应核对SH600000仍48键/18组、源stat一致；统计多股票共享`whole_planning_seconds`而非把组行上限错当物理IO节省。详见[多股票共享键试点文档](2026_5MIN_SHARED_MULTISYMBOL_SINGLE_DAY_KEYSCAN_PILOT.md)。
- [ ] 依据共享/独立真实成本决定是否值得为2026-09设计持久月度证券日索引；届时先实现可验证完整性、失效重建、回源一致性及回滚，**不以可编辑的未签名JSON作为生产可信剪枝依据**。下一大方向仍是Parquet历史主源+通达信盘后独立可回滚增量层，不因单日性能小实验长期阻塞主线。

## ▶ Windows 332项测试仅余Parquet临时文件WinError32：修复句柄生命周期（2026-10-28）

- [x] 用户日志：`Ran 332 tests in 16.841s / FAILED (errors=1)`，唯一`test_explicit_fast_path_skips_full_query_but_counts_check`在`TemporaryDirectory.cleanup()`删除合成`2026-09.parquet`时触发Windows `WinError 32`。没有行情结果不一致证据。
- [x] 根因代码审查：实验`query-parquet-exact-locator-preview.py`复用`prepared_context`中的`ParquetFile`，但未显式关闭；Mock可能延长引用。新增`finally`对共享Reader按对象去重关闭，无论成功或异常；追加2项合成测试验证生命周期和失败路径。正式查询、缓存、旧索引、原始源均不变。详见[修复记录](2026_WINDOWS_PARQUET_HANDLE_RELEASE_FIX.md)。
- [ ] Windows先针对`test_query_parquet_exact_locator_preview.py`回归，再全套`test*.py`。预期332+2项但以实测为准，不得预报已通过。通过后再推进之前single-preflight性能报告与月度索引评估。

## ▶ 定位查询端到端开销优化：避免同请求重复Footer预检（2026-10-28）

- [x] 最新真实回传：SH600000/2026-09-30/5min默认全量校验模式总**5.763604s**（缩组Arrow1.573799s，full Arrow复核2.136311s）；实验快路径总**1.641963s**（缩组Arrow0.646492s），两者均48根、源stat一致、仅18组数据读。快路径**当次无full等值校验**，未签名locator不能生产自动剪枝。
- [x] 检查现有源代码发现同一请求的locator先做一次`prepare_query`、`arrow_filtered_query`又做一次（默认加full复查做3次），新实现引入安全的**内部预检上下文复用**，同请求只做一次全量Footer和预算预检；重复调用的完整源行预算依然校验，不改变正式主查询、缓存、2025 V3及原始行情。新增2项合成测试，**尚待Windows实机验证**。
- [ ] Windows跑完整合成测试及默认严格对账/显式快路径各1次，核查`full_footer_preflight_executions_this_invocation=1`、48根与full Arrow一致、阶段耗时。**与旧版仅对比总调用耗时，不把“新Arrow只含scan的耗时”错当同口径加速**。详见[单预检性能研究](2026_PARQUET_LOCATOR_SINGLE_PREFLIGHT_EXPERIMENT.md)。
- [ ] 未来在2026-09等小范围试做月度多证券键索引前，先评估真实跨证券日重复读源需求及全部成本；不为了单日0.5秒数据列扫描的局部收益无端扩建不完整索引。

## ▶ 双顺序精确locator复用已实测胜出；向月度多证券索引演进（2026-10-28）

- [x] 两份本机`rg-reuse-{full,restricted}-first`安全报告：SH600000/2026-09-30/5min均48根、OHLCVA/时标/来源与完整Arrow和原默认引擎均一致。full-first从2.580526s降0.479882s（5.377×），restricted-first从1.000471s降0.528956s（1.891×）；仍受系统缓存影响。Footer候选47组→18组，行数上限5,685,792→2,213,909，但磁盘/物理解码未知。
- [x] 源stat清单相同；一次locator构建2.361006s，按观测每次节省2.100644s或0.471515s，简单情景回本需2～6次；这是单股票日估计，已有0.05s私有OHLCVA热缓存适用场景不同。
- [x] 新增`audit-parquet-exact-rowgroup-ab.py`进行两份真实安全摘要离线复核；新增`query-parquet-exact-locator-preview.py`复用已有locator进行实际本地查询。默认强制full Arrow逐根复核；显式`--fast-stat-only`只查18组并检查源stat/组内计数，但定位文件可编辑、未签名、缺内容SHA，**只作有人监管的本地实验**。两工具新增12项合成测试，尚待Windows实际验收；不触碰生产主接口。
- [ ] 本机运行新增全量单测，离线双顺序汇总、默认全量验证与显式快速路径的安全摘要，观察整个快速路径调用耗时（包含Footer/源stat校验）。
- [ ] 如继续验证后证明需求足够，再开发**2026年9月受限单月一次建全证券日`ts/symbol`索引**（而非对每只股票日重复完整扫描），具备源指纹、完整性/来源校验、失效重建及回滚。不改尚未完成的2025 V3索引。

## ✅ 全47组键列扫描实证18组成员；开始验证重复查询可复用定位（2026-10-28）

- [x] 用户上传真实`pq-SH600000-20260930-5min-exact-rowgroups.json`：全47候选组、5,685,792行仅键列精确覆盖，含键18组、不含键29组、SH600000/2026-09-30/5min实际48键；本次完整定位成本2.361006秒、stat清单9文件一致，且未读取OHLCVA。**并非已实现净查询加速。**
- [x] 新增同引擎`benchmark-parquet-exact-rowgroup-reuse.py`：在原全量候选源行预算下，读取已经存在的完整键定位报告，核对真实Footer候选全体、stat签名、成员分布、键数量及只读保护。full Arrow与仅含键行组Arrow**无条件逐根对账**，并支持反向执行顺序和额外与默认RowGroup的交叉核验；仅新`reports/`统计JSON，不改默认查询与2025 V3。配套7项合成测试，**待Windows验收**。
- [ ] 本机先跑全量合成测试，再运行两种执行顺序的full/restricted A/B，回传两份安全报告；判定是否确实减少**实际解码的六列行组**和改善**单次复用查询延时**，同时将2.361秒索引构建成本与后续复用次数单独核算。
- [ ] 此处是实验查询，并非可直接用于生产剪枝的持久索引。如果后续证明收益且信任链、重建/失效与异常恢复机制可靠，再考虑把精确证券日locator做成可显式开启的模块内本地只读索引。

## ▶ 最新真实预览反转：改攻精准RowGroup成员关系（2026-10-28）

- [x] 用户最新安全报告 `pq-primary-arrow-preview-SH600000-20260930-verified.json`：同一个SH600000/2026-09-30/5min的Arrow preview逐根与旧RowGroup一致（48根、源stat一致、原数据只读），但Arrow**2.972944秒**、旧引擎**1.791278秒**，Arrow耗时约**1.66倍**。此前两轮快于旧引擎，表明仅凭两轮A/B不能承诺生产加速；保留旧默认，无自动切换。
- [x] 确认47组Footer候选中的**18组**在过滤后输出48根数据，另外29组当前查询没有输出；不等于物理解码47→18，也不能跨证券日期复用结论。
- [x] 增加只读`plan-parquet-5min-exact-rowgroups.py`：完整扫描**全部**候选组的`ts,symbol`两列以精确建立单股票日成员分布，严格源stat、预算、每组行数与重复时间键检查；仅形成模块`reports/`安全聚合JSON，**不产生持久locator、不修改旧查询和2025 V3**。新增6项合成测试待Windows验收，见[精确组定位计划及本次真实回归](2026_PARQUET_ARROW_PREVIEW_REGRESSION_AND_EXACT_ROWGROUP_PLAN.md)。
- [ ] Windows完成新单测与一次完整键列计划，核对47候选、实际含键组数、源行守恒和建索引耗时；之后评估可选、stat绑定、可回滚的行组定位缓存对**多次查询**的净收益，再决定是否实现实际剪枝。

## ✅ 首次Arrow两种执行顺序真实胜出；显式可选预览阶段（2026-10-27）

- [x] 旧Windows PyArrow本地Fragment文件系统问题已修复，**298项合成测试/16.243秒/OK**，不再阻塞真实Parquet验证。
- [x] 用户上传两份原始安全A/B和反序审计JSON：SH600000/2026-09-30/5min均返回48根、六字段OHLCVA+时标+RowGroup来源完全相同，源stat摘要一致；`rowgroup-first`：基线4.579644秒、Arrow1.425189秒（3.213×）；`arrow-first`：基线1.925149秒、Arrow1.383294秒（1.392×）。两种顺序Arrow都更快，不能外推为全体股票/全部日期。Arrow仅过滤后向Python交付48行，实际物理解码行/磁盘IO未知，候选47组/5,685,792条RowGroup上限未变。
- [x] 新增独立`query-parquet-arrow-preview-readonly.py`：显式调用才使用实验Arrow，复用实测扫描路径，不碰`query-parquet-primary-readonly.py`正式引擎和本地私有缓存；可指定`--verify-rowgroup`严格对账六字段/时标/源行组，同时只输出无付费数值的模块`reports/`摘要。新增7项全合成测试，**尚待Windows实机验证**。详见[真实A/B与预览验收](2026_PARQUET_REAL_ARROW_AB_RESULT_AND_PREVIEW.md)。
- [ ] Windows运行新增完整单测、Arrow预览5min/day/1min三条有限真实对照，提供汇总JSON。验证全部通过后，再扩展**其它股票/历史月份**的小样本，决定是否将Arrow变成主接口`--engine`可选参数（**暂不能改默认值**）。
- [ ] 历史H5/Parquet数据源只读，待跨源回归和缺口证据充分后进入TDX盘后独立增量层、来源优先级与回滚；不把单样本性能优化误称为H5/PQ全历史可信并集。

## ✅ 真实Parquet重复查询约70倍加速；首次读取Arrow A/B实验工具已开发（2026-10-27）

- [x] 用户本机上传同一SH600000/2026-09-30/Parquet5min的缓存冷/热两份**真实安全JSON**：首次48根、`query_delivery=parquet_source_scan`、耗时**3.515286s**、源行情记录**5,685,792**；第二次48根、`query_delivery=local_private_cache_hit`、**0.050318s**、本次源行**0**、Footer**0**，重复查询约**69.86倍快**、耗时下降约**98.57%**。该实测成功验证缓存机制，但不代表各股票/日期总性能，也不改变缓存仅stat文件清单判定（非内容SHA256）和私有付费行情不能上传的约束。
- [x] 新增独立`tools/benchmark-parquet-arrow-filter-cold.py`：在相同查询/源RowGroup预算、禁用缓存下比较默认`ParquetFile.iter_batches`与`pyarrow.dataset.ParquetFileFormat.make_fragment(row_groups=[...]).to_batches(filter=...)`，严格对照每根OHLCVA、时间、来源行组，不相同就拒绝生成性能结论；仅安全汇总JSON，区别RowGroup源行**上限**、旧查询行数、Arrow**过滤输出**根数，后者不是底层实际解码源行。可反转引擎顺序监控OS页缓存偏差；新增7项无版权Arrow测试，预计全仓**283**项待Windows实测。
- [ ] Windows分别跑`--order rowgroup-first`及`--order arrow-first`，上传两个汇总JSON判断新引擎是否**双顺序都稳定提高首次查询速度、48根价量额和来源严格一样**；未跑之前不将Arrow路径接入默认查询，也不宣称首次569万源行已减少。
- [ ] 若Arrow测试确有真实改进且跨周期/历史日期对账通过，再设为可选读取引擎；若无改进，考虑有限的股票日小索引或分区缓存。主任务随后进入**TDX盘后完整交易日独立可回滚新增数据层**，H5/Parquet源保持只读。

## 用户V2真实报告验收后：按需私有行情缓存降低重复查询成本（2026-10-27）

- [x] V2购买Parquet真实查询`pq-primary-query-SH600000-5min-2026-09-30-v2.json`：目标单股票/五分钟/单日返回**48根**，原时标09:30～14:55，证实月文件规划安全裁掉8份但9份Footer都打开；原`candidate_row_groups=47`、`source_rows_scanned=5,685,792`毫无减少，扫描放大118,454×。**这是cold query真实性能瓶颈，不能把元数据剪枝等同数据列减读。**
- [x] 新增`tools/private-parquet-query-cache.py`，为本地`query_bars(...,local_cache=True)`及CLI`--local-cache`提供**明确启用**的私有选中K线缓存。仅本模块`work/primary_query_cache`保存**真实OHLCVA原值，.gitignore保护但不是授权外传**。默认关闭；热命中之前先基于文件相对路径+大小+mtime重新验源清单，源stat变化/文件新增删除/参数差异均回源；不覆写购买文件、不接入TDX/H5、原严苛结果数和RowGroup源行上限不因缓存参数不同而绕过。新增安全元数据本次读取源行数/耗时，可验证冷→热；5项合成Arrow测试待Windows端。
- [ ] 用户实际执行冷/热两次同样SH600000查询，上传**两份不含OHLCVA的安全报告**。冷查询源行数估计仍5,685,792；热查询若源文件stat未变则应`source_rows_scanned_this_invocation=0`与`source_file_footers_opened_this_invocation=0`，真实耗时以实测JSON为准。缓存本身有付费行情，**绝不能上传`work/primary_query_cache/*.json`**。
- [ ] 下一步继续降低**首次新股票日**RowGroup内读取放大：做PyArrow/DuckDB过滤/列选择基准与源布局分析，仅在明确有性能收益时实施更复杂的轻量索引。历史Parquet作为只读主源；通达信盘后逐完整证券日写入独立可回滚新增层。

## ✅ 首次真实Parquet主源查询成功；性能瓶颈是47行组/569万源行（2026-10-27）

- [x] 用户上传`pq-primary-query-SH600000-5min-2026-09-30.json`：请求单日单证券`SH600000`的购买Parquet 5min，返回**48根**，原源标签09:30至14:55，符合此前内部5min时间规则；不读取H5、不做100倍量换算、不修改来源、不输出原始付费行情。**原版读取9份月度Footer、47候选RowGroup/5,685,792源行**才能找出48根，扫描放大约118,454×。该安全报告不足以重新验证实际OHLCVA。
- [x] 新增月度文件Footer保守剪枝：`YYYY-MM.parquet`与请求日期区间无交集时，仍先打开并实际检查所有RowGroup时间统计**确实全部不相交**，才能排除；源码错月或无可信统计则保留。原全年Parquet与嵌套命名不被错误按月过滤。新增区分Footer打开/月份跳过/行组匹配及源行放大因子的安全字段，4项合成Arrow测试待用户Windows确认；详见[真实查询性能诊断](2026_PARQUET_FIRST_REAL_QUERY_AND_MONTH_FOOTER_OPTIMIZATION.md)。
- [ ] 运行`pq-primary-query-SH600000-5min-2026-09-30-v2.json`验证查询仍48根且输出meta状态一致；**不承诺569万实际源行读取降低**，因为数据布局可能使所有同月行组都包含目标时间范围。
- [ ] 下一核心性能任务：实测PyArrow Dataset过滤/行组布局、考虑只在有实际必要时增量建立按证券日索引或小范围缓存，缓存/工作文件只在本模块`work/`，附指纹过期失效机制、读取上限、不复制50GiB源库。优化后再推进TDX盘后新增/回滚层。

## 2026年2月和8月时间键异常已定位：仅深市B股；Parquet A股查询接口首版（2026-10-27）

- [x] 用户真实上传2026-02与2026-08两月`universe=all` Parquet key-only报告，2月77,772个供应商证券日中仅**2026-02-24 SZ200706**缺标准网格（1min 81、5min 17），8月118,064个中仅**2026-08-03 SZ200019/SZ200045/SZ200869**三只缺标准网格（各1min 80、5min 16）。两月合计195,836个证券日，195,832组完整，**4组均为深市200xxx B股**，无重复时间键或非正常时段键；没有观察到A股候选证券日的时间键缺失。原因不能推断为交易所/供应商错误，不自动补K线；不意味着2011—2026所有股票均完整。
- [x] 新增`tools/query-parquet-primary-readonly.py` **直接购买Parquet历史查询首版**：day/1min/5min A股候选证券代码、最多31天、RowGroup剪枝/读取预算及选中数量上限、原始OHLCVA、原始北京时间时标及源文件/行组溯源。Python接口本机返回完整请求值，CLI默认仅生成不带付费价量额的汇总元数据，显式`--show-first-bars`才本机打印有限个bars；代码不读取H5、不写行情、不作货币单位换算或除权。新增9项合成/Arrow单测待Windows；详见[异常结论与真实Parquet查询说明](2026_PARQUET_B_SHARE_KEY_ANOMALIES_AND_PRIMARY_QUERY.md)。
- [ ] 在Windows对SH600000 2026-09-30 `--period 5min`试运行查询，核验返回行数是否48、源时标9:30至14:55及原Parquet来源；继续抽2011/2016/2022年份少量存在证券数据，不能凭文件Footer假设股票上市年份。
- [ ] 累积真实查询报告后设计TDX盘后最新完整证券日的**独立可追溯增量层和回滚能力**，购买Parquet/H5保持原始只读；B股短记录独立存疑，不阻塞普通A股主查询。

## ✅ 2011—2026购买Parquet全目录Footer检查完成；新增2026年2月/8月key-only异常定位（2026-10-27）

- [x] 用户本机成功上传`parquet-primary-footer-inventory-2011-2026.json`：2011—2025年day/1min/5min每年各有年度文件，2026年1—9月每周期9份月度文件；总计**72个文件、约50.47GiB、4,148,162,255条Footer记录**。三个周期所有非空RowGroup均有可信时间范围，时间边界与文件名年份没有冲突，没有缺年命名或被跳过符号链接；最早候选2011-01-04、最新候选2026-09-30。**这证明文件级候选覆盖，不代表实际交易日或证券完整。**
- [x] 2011—2025年每年的1min和5min记录数分别恰好是同一整数的241与48倍；2026年2月单月`1min=18,742,892=77,771×241+81`，`5min=3,733,025=77,771×48+17`；8月`1min=28,452,941=118,062×241−1`，`5min=5,666,976=118,062×48`。这只是**聚合记录数异常信号**，不是逐证券/日期定位或市场真值。
- [x] 新增`tools/audit-parquet-month-minute-keys.py`：按用户指定的2026年2月/8月扫描购买Parquet的**ts/symbol两个键列**，不读价量额；按单证券日的241/48个预期时间键位图、缺口、重复及不规范时段统计，保留最多60个异常股票日示例，源行预算保护、无源写入。新增8项纯合成/Arrow测试待用户Windows跑，详见[Footer实测与两月精确定位](2026_PARQUET_FOOTER_INVENTORY_AND_KEY_ONLY_ANOMALY_TARGETS.md)。
- [ ] Windows优先运行2月`pq-key-only-2026-02.json`，根据真实异常股票和时间再决定8月`pq-key-only-2026-08.json`；若非A股代码造成异常，使用`--universe a-share-candidate`复验。下一步只读Parquet查询、可回滚TDX盘后新增层；**不扫描全部历史41亿条键，也不按Footer倍数自动填充缺失K线。**

## 主源覆盖盘点阶段：5组样本级证据成功登记，开始2011～2026只读footer扫描（2026-10-27）

- [x] 用户实测`parquet-primary-sampled-evidence-2026-08-24-09-30.json`：2日期5证券日均`candidate_parquet_primary_in_this_sample_only`，原样保留`verified_full_history_coverage=false`、`eligible_for_unattended_import=false`，没有发生任何市场源改动或数据导入。已满足“小规模跨沪深来源内部一致性验证”这一阶段目标，但不代表购买历史全盘都已验收。
- [x] 新增`tools/inventory-parquet-primary-footers.py`：按2011～2026年份/周期列出`AllCycleAStockData/{day,1min,5min}`中可由文件名唯一识别年份的Parquet，**只读File/RowGroup footer**时间范围、文件数、源行数、源容量、没有时间统计的行组、文件时间错年异常、元数据指纹；脚本不读取源ts/symbol值或OHLCVA，不建索引、不作自动补全。对文件名无法判年/冲突或文件ts缺统计时输出谨慎标志；`footer_envelope_complete_for_nonempty_row_groups`不代表“证券日完整”。新增10项生成Arrow合成测试待本机；研究说明见[历史Parquet footer覆盖计划](2026_PARQUET_PRIMARY_FOOTER_ONLY_COVERAGE_PLAN.md)。
- [ ] 先运行本机2011～2026 day/1min/5min footer盘点，上传安全JSON，分析每年不同周期的可用时间**候选范围**及真实疑点。无需扫描数亿分钟行情即可先确定需要少量抽查的年份。
- [ ] 之后从实际footer缺失/年份过渡日期、北交所及历史早期时间抽最少必要的证券日，采用key-only方法做精准覆盖验证，然后开发带来源ID/源stat指纹的购买Parquet只读主查询接口；盘后通达信数据进入独立可回滚新增层，原购买Parquet/H5不改写。

## 主源建设路径更新：两日5组日线-分钟样本全OHLC严格、量额原容差通过，开始只读证据登记（2026-10-27）

- [x] 2026-09-30 Parquet三周期真数据：SH600000、SZ000001各241×1min/48×5min，按经核实09:30特殊开盘规则每股5min六字段**48/48严格一致**，day↔两分钟OHLC、volume均严格一致；日成交额与分钟汇总差分别0.005/0.049 ppm（来自JSON9位小数比率），均落在旧容差下。两股原`raw_all_three_periods_strict_agree=false`保持不变。两周期源无重复、无无效时间戳或非有限行。
- [x] 用户上传8月24日的离线验收报告，三股均属`strict_OHLC_and_minute_aggregation_small_daily_quantity_gap_review`，量额最大相对差各0.025/0.033/7.157 ppm。**两日合计5组股票日线OHLC严格吻合、量额原容差通过**；三个测试日期共8组1min→5min样本384/384严格重建，不能宣传为全库认证。
- [x] 新增`tools/plan-parquet-primary-evidence-ledger.py`，接受多份原始三周期或离线验收安全JSON，检查标志及重复证券日，给样本级Parquet首选源候选生成**零行情扫描的证据登记**，状态`candidate_parquet_primary_in_this_sample_only`不可当作全历史认证；所有项目`eligible_for_unattended_import=false`，不进行任何实际同步。新增9项合成测试待用户Windows执行，研究记录见[主源样本证据台账](2026_PARQUET_PRIMARY_SAMPLED_EVIDENCE_LEDGER.md)。
- [ ] 下一阶段转入实际主数据读取路径：按Parquet元数据确认2011～2026.09真实周期/股票范围（不做全年盲扫）；设计只读历史主查询接口、完整证券日来源记录和可回滚的独立通达信盘后新增数据层。H5仅作为确认缺口后的后备，不覆盖购买Parquet原件。少量早期年份/北交所特殊情形再抽检。
- [ ] 不因本次≤10ppm研究分类而允许直接自动合并；历史时间标签/成交量单位/复权机制仍需跨年代验收。

## 最新节点：真实Parquet日线OHLC与分钟一致，但成交量额存在0.018—7.157ppm微差（2026-10-27）

- [x] 用户完成2026-08-24 Parquet`day`/1min/5min本机真实数据审计：SH600000、SZ000001、SZ300750都有合法日线+241根1min+48根5min，三股分钟→五分48/48六字段严格，日线OHLC vs两个分钟汇总**全严格一致**；成交量SH600000/SZ000001严格一致，SZ300750日线量对分钟汇总比例0.999992843（约7.157ppm）；日线额三股比例0.999999975/0.999999967/0.999999982（约0.025/0.033/0.018ppm）。按旧容差检查**三股六字段均通过**，但原始六字段严格`raw_all_three_periods_strict_agree=false`都必须保留。源读取三周期未见重复/非法时标/非有限数值。无证据证明偏差来源是取整还是盘后修订，不能自动改数据。
- [x] 新增`tools/audit-parquet-day-minute-report-offline.py`可**仅凭已生成JSON**检查源报告自洽、输出严格字段差异、旧容差差异、比率导出的相对ppm与审查分级；默认10ppm阈值**仅用于研究小偏差，不是质量认证标准或自动入库许可**。保存新的轻量安全报告，零Parquet/H5行情读取，8项合成测试待本地通过。详见[8月24日真实三周期对账与误差分析](2026_08_24_PARQUET_DAILY_TINY_QUANTITY_DIFFERENCES_REAL_REPORT.md)。
- [ ] 用户验收本轮离线解释工具的完整单测，随后选择2026-09-30三周期对账以及少数早期年份/北交所抽样；确认日线成交量额字段的单位、精度与不同历史阶段口径后，再设计Parquet历史优先、H5缺口后备、通达信盘后新数据的独立可回滚标准化主库。
- [ ] 继续避免无益的年度大扫描，不覆盖购买源、不按看似相同的单位自动转换或宣布全量正确。

## 最新实证：Parquet 8组沪深股票日样本384/384严格一致；日线守恒工具开发完成待本机验证（2026-10-27）

- [x] 用户上传两份真实Parquet-only JSON：8/24沪市主板SH600000、深市主板SZ000001、创业板SZ300750三股各48/48六字段严格聚合通过；9/30 SH600000和SZ000001两股各48/48。叠加9/28三股144/144，三日期**8个证券交易日384/384根5分钟**由同源1分钟严格重建，统一五分开始、一分结束、09:30额外一分仅首根使用。所选样本均无重复键/非有限值/时间网格异常、量额比率p10/median/p90/max均1.0。**仅2026年小样本，非全历史认证，北交所和日线仍未验收。**
- [x] 新增`tools/validate-parquet-day-to-minute.py`只读day、1min、5min，检查完整241+48分钟时间网格与09:30额外分钟、同源1→5严格重建、两套分钟对日线OHLC/量额原始严格一致及单位×1/×100/×0.01候选；日线缺失/异常、不同量纲不予批准自动并集。复用按证券/日期保守RowGroup剪枝及每周期30M候选源行预算。对读取辅助器仅将Parquet day时间戳归一到YYYYMMDD0000，不变动分钟对齐。新增8项合成测试（含临时Arrow日线读取）待用户本机；见[研究与操作说明](2026_PARQUET_CROSSMARKET_384_OF_384_AND_DAILY_AUDIT.md)。
- [ ] 用户运行新`pq-day-vs-minute-2026-08-24.json`，核验日线的复权/量额单位及交易日内部OHLC/量额是否与一分钟/五分钟守恒；若适用再抽9/30、其他年份及北交所。**即使日线较分钟有100倍差异，也需先核官方量纲和时间对齐，不自动转换。**
- [ ] 日线内部抽样合格后进入独立标准化历史主库设计：Parquet作为历史首选源、保留H5对照和缺口备选、通达信盘后逐证券完整交易日新增与回滚，始终不改原始购买数据。

## ✅ 验收更新：真实Parquet开盘特殊分钟得到证实，1min→5min 144/144严格一致（2026-10-27）

- [x] 用户上传`pq-only-2026-09-28-1min-to-5min-opening0930.json`。SH688629、SH688017、SH688172每股票241根1min和48根5min；在`five_start_minute_end_plus_opening_0930`候选下，一分结束标签T+1..T+5合成五分开始标签T，**仅首根T=09:30额外包含09:30的独立分钟**。六字段OHLC/量/额每股票48/48严格一致，**合计144/144**（上午72/72、下午72/72）、成交量额总倍率×1，报告`internal_5min_all_bars_tolerance_match=true`。
- [x] 旧常规5根/窗口聚合三股各47/48，在09:30首根均存在open/volume/amount三个实际超容差字段；加入额外分钟后3只均无剩余异常窗，源重复键/非有限数值/非法时间键均0，`source_market_files_modified=false`。实测严格数值准则为`abs_tol=1e-6,rel_tol=1e-10`，**不宣传二进制位级完全相等**。
- [x] 实测结果完整记录于[真实Parquet 144/144严格重建](2026_09_28_PARQUET_144_OF_144_REAL_DATA_CONFIRMED.md)。已明确允许**将Parquet列为历史主库首选候选**，不是全A股/2011～2026年认证，也不改变`safe_to_automatically_union=false`。
- [ ] 下一步最小样本扩展：2026-08-24沪深创业板、2026-09-10及09-30不同证券交易日，北交所从真实索引选有当日数据的样本，随后少量早期年份样本；避免一日重复全市场扫描，单次仍源行预算限制。
- [ ] **优先开发Parquet `day`↔1min/5min OHLC及量额单日守恒审计**，识别日线复权、成交量金额单位、缺失分钟及跨日期数据条件；然后再设计独立标准化Parquet主库和通达信盘后逐周期新增完整交易日的数据导入、来源版本与回滚。H5保持原始只读对照。

## 最新节点：Parquet独立1min→5min真实核验141/144严格一致，验证09:30额外开盘分钟（2026-10-27）

- [x] 用户2026-09-28的真实Parquet-only报告显示SH688629、SH688017、SH688172各有241根一分钟及48根五分钟，两周期所选源记录无重复键/无非有限值/无非法时间标签，最优普通窗口均为`five_start_minute_end`：五分钟起始标签T，对应一分钟结束标签T+1..T+5。各股票完整48/48，严格OHLC+量+额**47/48**，合计141/144严格通过；每只仅**上午一根**开盘、量、额不符，其他OHLC及下午三股各24/24根、合计72/72根六字段严格吻合。
- [x] 3股统一多出一分钟记录(241 vs常规240)，且唯一异常字段结构相同；09:30的独立开盘/集合竞价一分钟单独归属首根五分钟，是有力但尚未验证的候选解释。工具新增第五种假说`five_start_minute_end_plus_opening_0930`，仅第一根使用额外09:30分钟，保留其余47根普通规则；输出具体未对齐5min时间标签、异常字段与09:30一分钟存在性。新增3项合成测试，旧13项保留，共16项。详见[09:30特殊分钟验证](2026_09_28_PARQUET_OPENING_0930_SPECIAL_MINUTE_AUDIT.md)。
- [ ] 用户Windows运行更新后的独立Parquet报告`pq-only-2026-09-28-1min-to-5min-opening0930.json`和完整unittest，查看新假说是否真实恢复3只股票**144/144严格一致**；先前报告没有直接证明具体出错根是09:30，不得擅自把猜想写成已证实。
- [ ] 若第一日通过，再扩展不同日/交易所，严格检查日线/1min/5min交易日总额量、前后分钟衔接及不完整证券日，再考虑Parquet历史主源+通达信盘后增量同步。所有付费原始数据只读。

## 最新节点：用户倾向Parquet作历史主源，先核验Parquet自身1min→5min（2026-10-27）

- [x] 统一主库规划改为购买Parquet作历史主线（2011～2026-09），H5保留只读对照及源数据缺口候选，未来使用通达信盘后分别补录day/1min/5min。**不能把此前H5一分到五分144/144一致、H5/PQ重叠总一致率约99.677%误写成Parquet两个周期已认证**。
- [x] 新增`tools/validate-parquet-1min-to-5min.py`：只读Parquet 1min与5min同交易日、单股票区间；五分/一分起止标签共4个解释逐一验证，必须有完整5根一分钟才计算OHLC（开第一/高最高/低最低/收最后）与量额和；输出严格及原容差层次、成交量同源×1/×100/×0.01、上午/下午完整性、缺源/缺一分钟/重复键/异常时标和源读取成本。30M/周期上限默认保守，报告不含原始付费行情。新增13项合成测试待本机验收；详见[Parquet内部合成研究](2026_PARQUET_1MIN_5MIN_PRIMARY_SOURCE_AUDIT_20261027.md)。
- [ ] 用户先运行2026-09-28 Parquet三只股票核验，上传`pq-only-2026-09-28-1min-to-5min-top3.json`及测试结果。根据真实Parquet内部一致性，再决定是否追加2026-08-24、09-10、09-30的不同市场代表股票抽检。**本阶段不转换任何数据，也不默认Parquet中的1min和5min必然同单位或可信**。

## 用户目标更新：两源取可信主源+旧分钟补全，通达信盘后统一增量；同花顺人工核验（2026-10-27）

- [x] 用户明确数据事实：Parquet购买历史涵盖2011～2026-09；H5为自行下载，日线更长、可更新到2026-10，分钟线起点需逐股票/周期确认，未来计划通达信盘后统一补新日。**目标应改为主数据源选择+来源标记+按完整证券日的单源拼接**，不是为逼近100%逐根一致而持续增加昂贵全量比对。
- [x] 前轮真数据：2026-09-24/28/29/30两源匹配1,065,216根五分钟，H5×100候选后仍3,440有任一价量超容差（0.323%）；2026-09-28三证券95/144根有差，但H5自身1m→5m 144/144归并吻合。2026-09的Footer共47组全需解码，三组key-only探测共读297,849条索引键，0/46组有目标证券，23组无目标证券；样本仅用于评估索引成本。
- [x] 先给同花顺验证方案：SH688629、SH688017、SH688172的2026-09-28五分钟，统一不复权、量到股、额到元、按同一区间而非字面时间标签比较。新增`tools/prepare-5min-tonghuashun-spotcheck.py`：从实际对账母报告选真实前3股票，单日针对性读取两源并校验8mask，选择每股最多3根**实际冲突**五分钟，默认报告只含symbol/区间/超容差字段；可选终端私显两源OHLCV；新6项合成测试待本地，详见[主数据源同步及同花顺核验](2026_H5_PQ_TDX_PRIMARY_SOURCE_THS_SPOTCHECK_20261027.md)。
- [ ] 用户在同花顺人工核验若干实际冲突五分钟，并反馈哪边更相近、时标是否一致；决定H5或Parquet作为近端分钟主源，然后再规划历史日线/分钟补空及通达信盘后增量的**只读dry-run和可回滚的独立目标库**。仍须分周期验证末日完整性（此前五分钟H5最新快照是2026-10-13，10-19～23没有5min），不能以日线进度代替。
- [ ] 不强制继续大量Parquet索引实验。只有决定定向历史修复/多次查询需求后，才评估仅2026-09月完整定位或现有年度V3索引。源文件保留，单日不混用多源片段，正式自动并集等候独立校验及来源口径确认。

## 最新节点：2026-09月Footer预检实测47组全候选，先低开销key-only三组探测（2026-10-27）

- [x] 用户上传`pq-5min-2026-09-28-top3-footer-read-plan.json`，只读元数据：2026年度9个文件407组，360组被时间过滤，**9月文件47组全部仍是候选**；`symbol min/max`排除0组，候选待解码5,685,792行（与上次真实诊断一致），未压缩Footer列总量143,128,330字节。没有使用完整索引（`coverage_index.used=false`）。
- [x] 新增`probe-parquet-5min-rowgroup-membership.py`，按实际metadata候选组均匀取最多3组默认（47组固定索引0/23/46），只解码`ts/symbol`两列，逐组计数目标三只证券9月28日的真实存在性、48槽位及重复键。**未抽查的44组保持未知，样本报告严禁用于自动跳读**；新增6项合成测试、用户Windows验收待完成，见[3组键列探测](2026_09_28_PARQUET_3GROUP_KEY_MEMBERSHIP_PILOT_20261027.md)。
- [ ] 下一步只需上传`pq-5min-2026-09-28-top3-key-pilot-3groups.json`与unittest结果，再据每个抽样组的目标证券/交易日成员关系，决定是否为9月建立**完整、源指纹一致的月度V3定位索引**，而非立刻启动2026全年索引。严格维持`safe_to_automatically_union=false`。

## 最新节点：180项测试已通过，2026 Parquet 元数据读取成本规划与完整索引接入（2026-10-27）

- [x] 用户Windows实测`Ran 180 tests in 6.256s\nOK`，前一轮PR#46合成fixture共享字典问题彻底解决，可进入下一阶段。
- [x] 发现2026-09-28三只股票H5/PQ的定向诊断从407个Parquet行组中需要读取47组/共5,685,792条源行（仅144根命中）；已有索引V3完成验证机制，但此前该聚焦脚本没有`--coverage-index`接入，用户2025年V3无法直接用于2026年。
- [x] 扩展`analyze-5min-x100-focused-sessions.py`：新增`--plan-only`读取2026 Parquet年度文件Footer、按日期和证券最小最大值保守过滤，预测实际必须解码的RowGroup行数（不加载任何源行情列）；新增可选`--coverage-index`，复用`validated_parquet_locator`现有完整性/源指纹安全校验，只有真实完成同年度索引时可跳过安全定位的行组。新增7项合成测试待Windows执行。详见[2026年Parquet Footer访问成本评估](2026_5MIN_PARQUET_FOOTER_COST_PLAN_INDEX_OPTION_20261027.md)。
- [ ] 用户只运行Footer-only预检，上传`pq-5min-2026-09-28-top3-footer-read-plan.json`；先观察47组/568万行是否由元数据解释清楚，再评估Arrow列谓词下推的A/B收益或完整2026索引的一次性构建成本。**现在不发起2026全年重新索引、数据源转换或自动并集**。

## 最新节点：H5一分钟结束标记聚合144/144通过；证据链离线守恒门槛（2026-10-27）

- [x] 用户上传`h5-1min-2026-09-28-top3-no-parquet.json`，SH688629、SH688017、SH688172各1min 240根、5min 48根、1min重复键0。**分钟结束标签**完整48/48，各H5自身OHLC、成交额、候选量×100在非零窗口均48/48一致（总计144/144）；**分钟开始标签**每只46个完整窗口、OHLC一致0个，三只合计成交额3/138、量×100 1/138。1min与5min同上游可能相关，官方时标及供应商真值仍未认证。
- [x] 前一步双源top3有95根量价候选冲突，其中72根V/A/P三者同差；而H5分钟跨周期内部144/144一致。这更支持**两来源五分钟聚合窗口及成交归属口径差异**假设，但仍需正式供应商文档/其他独立来源证明，不能直接声称PQ错误。此前分时净差0%来自**有限精度显示**，新工具不把它声称为精确整数相等。
- [x] 新增完全离线的`tools/audit-5min-source-evidence-chain-offline.py`：整合精确8mask、三证券H5/PQ 5min分时、H5 1min→5min报告，核对日期/来源/证券/字段边际、各午前午后24根、分钟量价窗口及缺窗状态，输出来源JSON SHA256、可信的候选证据等级。只读三份既有JSON，不碰付费源。新增8项合成测试待Windows全套执行；见[2026-09-28跨周期证据链](2026_09_28_H5_1MIN_EVIDENCE_CHAIN_20261027.md)。
- [ ] 用户只需运行离线JSON证据链并上传`h5-parquet-2026-09-28-provenance-chain.json`。然后优先解决**Parquet行组按证券+日期定位/IO优化**（前次仅3只股票仍解码568万行），或核对供应商K线起止时标。不要反复重扫已完成的双源窗口；正式并集仍保持关闭。

## 最新节点：前三证券×100分时守恒已实测，优先H5一分钟轻量交叉复核（2026-10-26）

- [x] 用户上传`h5-parquet-5min-x100-2026-09-28-top3-sessions.json`，SH688629/SH688017/SH688172各48根H5/PQ 5min，零缺失、零OHLC几何异常，精确冲突mask与前一次9月28日单日报告**逐证券完全重现**（33/32/30有冲突，三字段同差28/25/19）。
- [x] 更有证据力的归因：H5 5min成交量×100后，三只的**上午和下午各24根分别0%净差/1.0抵消率**，而全天量的逐根毛差分别0.928496%、0.561701%、0.717788%，邻差相关系数-0.482/-0.455/-0.446；成交额整日净差也极小（0.000017%、0.000023%、0.000189%）。支持**时段内部重新归属候选**但不能证明来源真值，不能自动合并。
- [x] 上次仅选144根PQ 5min，底层却读取47个行组、5,685,792条源行：进一步PQ读取效率低。已新增`tools/inspect-h5-1min-top3-no-parquet.py`，只读H5一/五分钟这三只股票指定日期，验证1min结束/开始两套标签、分钟成交量×1/×100两个候选及上午下午完整窗口，输出聚合统计/可用性；新增6项纯合成测试待Windows验收；详见[H5一分验证](2026_09_28_H5_1MIN_TOP3_NO_PQ_20261026.md)。
- [ ] 用户仅需运行新H5-only脚本上传`h5-1min-2026-09-28-top3-no-parquet.json`；按1min实际可用性及窗口完整性决定下一研究主线。不能因为H5 1min与5min同源一致就认证付费Parquet的正确性，也不能为了重复核验又扫百万级PQ行组。

## 最新节点：2026-09-28候选残余精确复核通过，进入SH三样本分时归因（2026-10-26）

- [x] 用户上传该日有界对账JSON、MD：`scan_complete=true, issues=[]`，两源重叠**266,256**、PQ独有**1,008**（21整证券日、无部分缺口），H5独有0。候选H5 5min volume×100后`none=265227`，有冲突`U=1029`：`V=47,A=2,P=117,V+A=392,V+P=37,A+P=0,V+A+P=434`，逐类别反算候选volume=910、amount=828、price=588，匹配离线日级统计。
- [x] 候选any差按前缀：SH_other535、BJ336、SH688/689 158、SZ两组0；仅价格差117里**BJ113**。前3个实际冲突最集中证券日为SH688629(33)、SH688017(32)、SH688172(30)，合计95根有差，其中三字段同差72根。**量价异常不意味着单位或数据商错误得到认证**。
- [x] 新增`analyze-5min-x100-focused-sessions.py`：从已验收单日精确mask报告自动选前3个真实证券，H5量候选×100不改源，以原量价容差再核验全8mask；逐证券比较上午与下午的量额净差/累计失衡、相邻交易根重分配假设和OHLC价格跨根连续性；数据读路径重用既有定向H5/Parquet按证券和时标过滤，新增5项合成测试待Windows跑。详见[前三证券分时验证](2026_09_28_TOP3_X100_SESSION_DIAGNOSTIC_20261026.md)。
- [ ] Windows只需提交`h5-parquet-5min-x100-2026-09-28-top3-sessions.json`，再根据量额差抵消程度决定是否调入H5 1min进行独立聚合核对。对于BJ的113根纯价格差，先获取具体验证股票名单再定向研究，避免盲扫。

## 新节点：从离线聚合下界转向9月28日逐K线精确8类mask（2026-10-26）

- [x] 用户上传`h5-parquet-5min-2026-09-24-30-residual-triage.json`：母报告1,065,216个重叠键、候选any 3,440（0.32294%）、V=3,097、A=2,812、P=1,893；严格证明U−V=343、V∩A∩P至少922，不能通过分组边际恢复精确交叉；SH其他V=1,742、BJ V=806、SH688/689 V=549、SZ两组V=0；09-28候选volume差910最多。
- [x] 在已成熟的5min双源SQL同键比较中新增8种互斥候选残余mask，按日/代码前缀统计；扫描结束校验mask总数=matched、非none总数=candidate任何量价差、各字段与原价/额/V边际一致，代码组与交易日合计均守恒；输出前16个实际异常证券—交易日聚合而不导出源OHLCV。原单位假设与严格容差仍未认证，不启动并集。新增4项合成测试待Windows执行。详见[精确字段mask单日验收](2026_5MIN_EXACT_RESIDUAL_FIELD_MASKS_20261026.md)。
- [ ] 下一步仅对**2026-09-28**运行一次有界2026/A股候选/5min审计，上传`h5-parquet-5min-2026-09-28-exact-residual-masks.json`。核对候选volume差910、amount差828、OHLC差588再分析7类排他掩码，随后决定是否需要定向1min核验。避免重复做全四日的昂贵扫描。

## 新节点：3,440条量价残余先建立可证明交叉下界，零行情I/O（2026-10-26）

- [x] 复用完整报告`h5-parquet-5min-2026-09-24-30-volume-x100-candidate.json`：已配准1,065,216根5min，H5成交量×100后量价残余U=**3,440**，其中候选成交量V=**3,097**、成交额A=**2,812**、OHLC任一价格P=**1,893**；严格能证明**仅非成交量的残余343条**、V∩A≥**2,469**、V∩P≥**1,550**、A∩P≥**1,265**、V∩A∩P≥**922**，但不能从边际推导真实交叉精确数。
- [x] 新增`tools/triage-5min-x100-residual-offline.py`，仅解析旧JSON，检查旧成交量差与×100差数守恒、代码前缀组/按日的V/A/P全部守恒、各组最低必需的非成交量增量不超过全局343，计算每组总残余上下界及优先级；新增7项合成测试，Windows待运行。详见[3440条冲突离线归因](2026_5MIN_X100_OFFLINE_RESIDUAL_TRIAGE_20261026.md)。
- [ ] 用户直接生成并上传`h5-parquet-5min-2026-09-24-30-residual-triage.json`，不再次读取D盘原始行情。之后若需要逐K线精确交叉分布，只按代码前缀/日窗口用现有诊断与覆盖索引执行有界核验，保留未认证单位及自动合并禁止规则。

## 新节点：四周期聚焦实测和H5绝对容差量纲一致性修正（2026-10-26）

- [x] 本机上传`pq-h5-bj-focused-2026-09-29.json`及`-v2.json`：两份**字节完全相同**，不再重复扫描。BJ920069和BJ920121均H5 5min×100 vs PQ 5min逐根**48/48**在原严格容差内，两者Parquet日线—五分钟和均超0.1%；BJ920069 H5 day×100 vs PQ day超0.1%，BJ920121 day跨源一致。
- [x] 对照上轮独立H5报告：BJ920121独立归一化日分审计超差，但旧聚焦`h5_day_vs_minute_raw_sum_agree_0_1pct`为True。原因已定位：旧聚焦直接原始H5分钟/日线比较，**绝对容差下限1手**，独立审计是在×100后应用**1股候选量纲**的绝对下限；相对容差虽同为0.1%，小差值可能被原始单位的宽松绝对阈值掩盖。增加`h5_day_vs_minute_normalized_sum_agree_0_1pct`调用独立审计相同方法，保留旧字段兼容；回归测试覆盖48对49量纲不一致情形。
- [x] PQ 2026-09-29日线缺口12组均5min 48根，名单：SH600293、SH600363、SH601059、SH601198、SH603400、SH688496、SZ000016、SZ002731、SZ002860、SZ300082、SZ300527、SZ301139。仅为源记录缺口、非认证漏数；跟跨源5min较H5多1,056根（22个完整证券日）两层覆盖概念不可混淆。详见[四周期实测与修复记录](2026_09_29_FOCUSED_4CYCLE_VOLUME_FINDINGS_20261026.md)。
- [ ] 后续直接开展3,440条剩余五分钟OHLC/amount/volume候选冲突分类及12个PQ缺day标的证券有效性核查。**不必为了重打一个聚焦报告再次扫描9月29日全Parquet rowgroup**；如确需新字段报告，则用新文件名并保护原JSON。不可自动并集。

## 最新实测2026-09-29：H5/PQ单位证据自洽，两个北交所异常与12组PQ日线缺口待归因

- [x] 用户本机上报`h5-day-vs-5min-volume-2026-09-29-anomaly-id.json`：H5完整证券日5,548，归一化后5,547组通过0.1%日—分量能守恒，**异常仅BJ920121@20260929**，`scan_complete=true`。
- [x] 用户上报`pq-day-vs-5min-volume-2026-09-29.json`：PQ日线证券键5,558、五分钟证券键267,360，共5,570候选证券日；完整5,558组中5,556组原单位day与5min量能0.1%守恒（99.964%），**异常BJ920121和BJ920069**；同日12组PQ分钟有而day无键，旧报告无具体代码；替代day或minute×100均0组通过，`scan_complete=true`。
- [x] 增加只读四周期聚焦校验`inspect-parquet-day-vs-5min-volume.py --focus-symbols BJ920121 BJ920069`及最多24个PQ仅分钟证券日身份列表，用同一有界单日扫描定位两个北交所异常是否存在两供应商共同量能口径偏差，保留换算后的严格逐五分钟差异计数与时标示例而不输出原始量额。新增2项合成测试，Windows执行待验收。见[2026北交所四周期异常归因](DUAL_SOURCE_2026_BJ_4CYCLE_EXCEPTION_AUDIT_20261026.md)。
- [ ] Windows主线仅执行**2026-09-29**聚焦两证券+12组PQ无日线的新版报告`pq-h5-bj-focused-2026-09-29.json`；验证共同异常是不是各自日线与共同分钟守恒差，而不是简单归咎某一供应商。仍不改原始D盘、不自动并集。

## 新节点：H5自身跨周期验证几乎完全支持100倍，Parquet独立验证接续

- [x] 用户上传2026-09-24、28、29、30日H5日线与5min总量报告：**22,192/22,192组符合完整48根候选时标**，并且day/5min都有记录，`scan_complete=true`；原五分钟量直接对比候选day量0组通过，H5分钟×100后**22,191组（99.9955%）**0.1%容差内、**22,021组**原始transCount和完全相等。171组不严格相等，170组容差内，**1组2026-09-29超差**。
- [x] 在H5已有工具中新增最多12个超差`symbol+day`的匿名量价示例，不公开原始值；新增只读Parquet day/5min跨周期守恒工具，仅读取指定窗口ts/symbol/volume三个字段及RG时标元数据，原量纲与两种100倍候选并排测试，严格48分钟结束时标与重复键校验。5项新的合成测试，Windows本机仍待执行。详见[H5守恒真实实测与PQ交叉核验](DUAL_SOURCE_2026_H5_CONSERVATION_CONFIRMED_PQ_NEXT_20261026.md)。
- [ ] 下一步只在**2026-09-29**重新跑H5异常证券ID探针、Parquet日/分钟成交量独立探针；结合两份新报告判断日线和分钟成交量的提供方单位规则。暂不开展昂贵年度全局扫描，不更改购买付费数据或未经审批的合并策略。

## 最新真实结果：五分钟H5×100将量价冲突降至0.323%，推进H5自身跨周期守恒

- [x] 用户`volume-x100-candidate.json`真实复测，覆盖2026-09-24/28/29/30的1,065,216个H5/Parquet重叠键。旧成交量冲突1,060,937，候选乘100后仅**3,097**，旧冲突消除**1,057,840（99.708%）**、新引入0；完整量价冲突仅**3,440/1,065,216=0.323%**。强烈支持H5分钟计量单位100倍假设，但源真值尚未认证。
- [x] 新增`inspect-h5-day-vs-5min-volume.py`：只读H5三个市场的day/5min时间+成交量有界数据，严格筛选48个标准候选结束时标的完整证券日，统计旧/候选归一化的日量—分钟量一致性、异常时标和缺源情况，不读取Parquet OHLCV、不更改源；新增6项纯合成测试，Windows待执行。见[H5跨周期成交量一致性核验](DUAL_SOURCE_2026_H5_DAY_5MIN_VOLUME_CONSERVATION_20261026.md)。
- [ ] 用户上传`h5-day-vs-5min-volume-2026-09-24-30.json`，核对完整48根通过率和未通过/不完整组数；然后对购买Parquet日线与5min日内和做来源内交叉核验，再处理3,440条剩余多字段冲突。仍禁止未经证券主数据和官方单位认证的自动并集。

## 当前最重要结论：五分钟成交量接近100倍单位口径

- [x] 用户上传五分钟量额聚合：同键1,065,216；`volume_only=1,058,125`，`amount_only=0`，两者皆差2,812。双侧volume非零1,060,935里，1,059,453（99.86%）的`Parquet/H5`落在100倍的1%邻域；金额双侧非零1,060,840里1,046,098（98.61%）接近1倍。现有H5 minute成交量不乘100，而day已乘100；强烈提示单位映射错误，但仍待官方文档和日线总量校核。
- [x] 保留旧统计不动，新增H5五分钟`transCount×100`只读平行候选，对同一重叠键原容差重算volume残余冲突、旧冲突解除、新增冲突与价格/金额保留时的完整K线残余不一致。按日/前缀分桶且严格守恒，不能自动用候选改写原始数据。新增3项纯合成测试待Windows跑。见[成交量100倍证据与并行候选](DUAL_SOURCE_2026_5MIN_VOLUME_X100_CANDIDATE_20261026.md)。
- [ ] 本机只重跑**2026-09-24—30**已有真实重叠窗口，上传`h5-parquet-5min-2026-09-24-30-volume-x100-candidate.json`。验证100倍是否按原严格容差消除几乎全部volume差异、是否引入异常；随后用同证券同交易日day总量与5min汇总及数据供应商规则对倍率作独立认证。保持`safe_to_automatically_union=false`。

## 2026年两份真实双源对账已完成，主线转为核实量额差异

- [x] 2026-09-24至30四个有行情日期实测：H5 1,065,216、Parquet 1,069,296、重叠1,065,216、PQ独有4,080（85个H5整证券日缺口候选，平均每组48根），H5独有0；**重叠量价差1,060,937（99.598%）、价格冲突仅1,893（0.178%）、量额冲突1,060,937**；两个数据源无重复键、issues=[]、源只读。不能把量额大面积超严容差误判为源行情一定错误。
- [x] 2026-10-07至13实际四个有K线交易日（8、9、12、13），H5独有**1,066,368**，22,216个Parquet整证券日缺口候选，平均每组48根，Parquet=0且407个RowGroup全因不在窗口被跳过；H5 13:00可疑标记25根待认证；不必再次重复该段扫描。
- [x] 有界5min重叠键新增成交量/成交额分别的冲突统计、零值/非零相对误差分段、候选Parquet/H5倍率直方图；保持按日/前缀分组和计数守恒，不导出原始OHLCV或自动修改单位。新增4项合成测试，Windows真实通过待核验。见[2026真实双源覆盖与量额差异归因](DUAL_SOURCE_2026_SEP_OCT_PRICE_QUANTITY_DIAGNOSTICS_20261026.md)。
- [ ] 对2026-09-24至30日重叠窗口只读复测一轮并保存新`quantity-diagnostic.json`：判定成交量还是成交额导致近100%重叠不一致；检查是否接近1倍（原容差过严）或明显接近100/1000等倍率；有证据后再与日线真值、数据商字段定义做交叉验证。10月尾部及2025旧窗口不再重复扫描，除非新假设需要。

## 2026年双源边界探针真实验收：H5更新到10月13日，Parquet页脚到9月30日

- [x] 用户上传`dual-source-5min-2026-date-envelopes.json`，源元数据仅查时间边界：H5 **5579**个候选股票dataset具有2026记录，**5562**个最近记录在10月，H5最后候选时间`2026-10-13 15:00`；Parquet 2026 9个文件/407 RowGroups、全部具有可用ts页脚，最后候选时间`2026-09-30 15:00`，源文件均未改。完整性、复权/单位、真实成交键仍未认证。
- [x] 后续自动选窗器新增`suggested_h5_newer_window`，在可靠元数据下独立建议最多7日的H5更新后缘；不把H5数据集时间包络当作真实可合并五分钟键。新增3项合成测试，Windows本机执行仍待验证。详情见[2026实际截止边界与双窗口主线](DUAL_SOURCE_2026_BOUNDARY_CONFIRMED_20261026.md)。
- [ ] 先执行**2026-09-24—30**的H5/PQ全A股候选双源重叠真实对账，再执行**2026-10-07—13**的H5较新尾段真实键覆盖检查；两个窗口分别使用不同JSON文件名，报告`h5_only`、`pq_only`、重叠量价冲突，之后才讨论并集规则。现有边界JSON够选窗，无须重复探针。

## 最新主线验收：2026-10-19至23日空窗口已确认

- [x] 用户提交2026-10-19至23日全候选股票五分钟双源报告：H5=0、Parquet=0、交集=0、两向独有=0、量价冲突=0，`issues=[]`。2026 Parquet有9个文件、407行组，全部因与所选时间不重叠跳过；不能推断H5/PQ真实截止日，也不能把0行称为数据源一致。
- [x] 增加双源边界定位`inspect-h5-parquet-coverage-bounds.py`：H5各股票dataset仅查时间边界，Parquet只查row group footer ts范围，输出2026实际两源包络与最近候选重叠日期（最多7天）；日期不可信、市场文件缺失、footer不完整一律不推荐，而不是继续试错扫描。新增4项纯合成测试，需本机Windows执行。详见[2026空窗口与时间边界探针](DUAL_SOURCE_2026_OCT_EMPTY_AND_COVERAGE_BOUNDS_20261026.md)。
- [ ] Windows全部测试通过后执行2026年仅metadata探针，上传`dual-source-5min-2026-date-envelopes.json`。若有可靠候选日期，再做对应有界2026 H5/PQ实键比较；并并行安排已知2025三日2,784根PQ独有键的整证券日/局部缺口归因。

## 本轮主线进展：双源覆盖与差异分类

- [x] 2025-09-26、29、30日真实双源全候选A股：H5 779,568、Parquet 782,352、交集779,568、H5独有0、Parquet独有2,784；重叠量价差461,937（59.26%），价格差227,715、量额差454,682，均无同源重复键，issues=[]。
- [x] 结合三日实测，新增证券日“整证券日无键”与“同证券日部分K线缺键”的精确归因；按未认证代码前缀分组重叠量价差异，JSON/Markdown同列，新增2项合成测试（待本机验收）。参见[实测与缺口分类](DUAL_SOURCE_2025_3DAY_GAP_CLASSIFICATION_20261026.md)。
- [ ] 下一轮优先运行2026-10-19至23日五分钟全候选证券双源核对，验证H5最近记录与Parquet覆盖差异；再对2025三日旧窗口进行有针对性的缺口分类复核；不继续无关的单源索引微优化、不自动构建并集。

## 当前主线优先：直接比较H5与Parquet

- [x] 2025-09-30全市场候选A股五分钟双源真实核对：H5 259,872、Parquet 260,832、同键交集259,872、Parquet独有960、量价差异151,099（58.14%）。这项实测既证明重叠覆盖较广，也证明不能未认证时标/单位直接拼接。
- [x] 用户最新2025 Parquet V3主索引已推进至67/522 RowGroup，累计候选源行8,237,762；但是`progress`唯一键/重复键未知。**主线不依赖522组索引完成才能进行有限日期的双源核对**，暂停无明确收益的SQLite微调。
- [x] 有界全市场双源工具增强：跨Arrow批次、跨RowGroup、跨Parquet文件的同键去重与重复异常标记；每个交易日输出H5/Parquet唯一键、交集、双向差集和价格/量额冲突的守恒摘要；新增2项合成测试（真实Windows回归待执行）。具体见[三日全市场对账主线](DUAL_SOURCE_2025_5MIN_MAINLINE_20261026.md)。
- [ ] 从2025-09-26至2025-09-30一次扫描2025年度Parquet文件（不逐日重扫522组），输出三个交易日的全候选A股同键覆盖、双向差集、量价冲突分布和安全问题；核对以前2025-09-30真实报告，定位跨日稳定/不稳定的冲突类型。
- [ ] 利用2025/2026现有日线证据及不同时间尺度，核对最新H5独有、早期Parquet独有、同源量额守恒和时标/复权问题；待规则认证后才考虑输出并集副本，原始D盘只读。

## Phase 1：全周期的双源覆盖对账（开发中）

**路径硬约束**：所有本工具生成的报告、SQLite中间索引、后续H5/Parquet并集与日志都只允许放在 `AStockDataTools/H5ParquetReconciler/` 内；当前CLI默认报告 `reports/`、临时文件 `work/`，均由Git忽略。原始源文件 `D:\stock` 依然完全只读。

- [x] 新建独立代码目录，迁移前一轮六项合成测试覆盖的全量核对脚本。
- [x] `day / 5min / 1min` 的股票/时间匹配、H5独有、Parquet独有、重叠记录字段差异、首尾范围与中文JSON/Markdown报告。
- [x] 本地只读、防覆盖、年度checkpoint/断点续跑、批量Arrow读取、SQLite临时键匹配、无H5记录年份footer候选快速统计。
- [ ] 在新仓库Windows项目环境上执行当前19项合成测试并保留通过记录。
- [x] 2025年全年度5min长时间无结果后，新增单日/同年日期区间H5限量索引与Parquet行组时间跳过、分阶段进度；整年分钟模式需显式选择。
- [x] 用户本机完成2025-09-30单日5min试跑，H5 259,872、Parquet 260,832、同键冲突151,099条，522个row groups无一跳过；先不扩大到一个月。
- [x] 用户完成5只股票的5min时间/量额候选诊断：Parquet时标+5分钟对齐192条，高/低差异各8条，开/收各80/86条，固定量额倍数不解释大多数差异。
- [x] 用户本机完成第二轮量价归因v2，验证5min开收差异有80/80与86/86的邻接价格规律，四只股票量额比值中位数均接近1；它尚不能决定正确来源。
- [x] 新增独立一分钟周期文件重建五分钟K线的只读V3工具及8项合成测试（不同1min时标、完整性、OHLC、量额、缺失显示）。
- [x] 用户本机完成H5 1min→5min交叉诊断，2025-09-30四只可比证券H5一分钟记录均为0，无法从H5 1min独立重建五分钟；同时五分钟全天量额总和Parquet/H5比值约为1。
- [x] 新增无需H5一分钟的五分钟交易时段量额守恒和相邻跨K线差异抵消诊断脚本，7项合成测试。
- [x] 用户完成2025-09-30五分钟守恒诊断：四只可比股票的量差抵消率99.57%—99.93%，相邻非零差额118/168对方向相反。
- [x] 实现五分钟单日证券级并集只读预检原型：H5独有/Parquet独有/完全相同/容差一致/量价冲突隔离，不写并集。
- [x] 2025-09-30的五分钟并集预检完成：H5 192、Parquet 240、交集192、H5独有0、Parquet独有48、容差内8、冲突184；自动合并继续禁止。
- [x] 新增Parquet年度五分钟证券/日期/时段键位图索引及行组定位，处理跨批次/跨行组/跨文件重复键，支持逐RowGroup checkpoint和源文件指纹验证。
- [x] 只读并集预检可选用已完成的行组索引，跳过与目标证券/日期无关的Parquet行组。
- [x] V1年度索引首次真实试跑2/522行组，处理247,806原始行、A股候选247,776唯一键、重复0、异常时标0；但定位关系已有122,277条，存在全年的SQLite膨胀风险。
- [x] 新增V2压缩行组位图索引，逐证券/日/源文件一条BLOB定位，保留原重复键判断；默认使用单独v2 SQLite路径，不覆盖V1。
- [x] V2两组真实索引通过63项Windows合成测试；有效唯一键与V1相同，但V2文件5.89 MiB超过V1的5.79 MiB，定位表实际存储未见收益。
- [x] 查明前2组只有1631个证券/日期出现在两个RowGroup；119015个只出现一次，V2高编号绝对位图存在稀疏零填充风险。
- [x] 开发独立V3升序LEB128变长RowGroup ID定位列表和合成测试，版本化默认输出避免修改V1/V2。
- [x] 用户本机已完成V3的前2组和累计10组检验，唯一键247776→1230687、重复0、时标异常0、SQLite约5.88→27.64MiB；仍未完成522组。
- [x] V3新增`--max-index-mib`软容量控制、SQLite主库/WAL使用统计及每轮速度指标，提供安全分批续建参数。
- [x] V3累计完成2025年20/522组，本轮10个行组耗时76.125秒；候选唯一键2459297、重复0，SQLite主库约47.93MiB而主库+WAL约96.14MiB，因软预算停止。
- [x] 在软预算触发且RowGroup事务已提交时先尝试安全的WAL截断检查点，回收暂存空间后再次检查预算；保留原V3数据库格式和断点。
- [x] 用户本机继续V3索引至30/522个RowGroup，累计唯一有效键3,687,846、重复0；本轮10个组耗时129.36秒、9次WAL截断、累加回收523,606,968字节，停因为组数上限而非容量。
- [x] 设计独立V3 SQLite快照下的WAL/DELETE同一后续5组对照工具，不改动用户既有30组索引并保留相同事务完整性约束。
- [x] 用户提交相同30组源快照WAL/DELETE各增5组的实测报告：数据统计完全一致，处理5组耗时分别51.796秒和51.219秒，仅约1.1%差异，暂不更换默认WAL事务模式。
- [x] 新增V3索引细分阶段耗时报告：Arrow读取及键聚合、SQLite RowGroup事务提交、软预算与WAL检查点，最多5组最慢项；不修改索引格式和源数据。
- [x] 用户本机完成2025年主V3索引35/522组并提交分段报告：新增5组53.078秒，其中SQLite事务28.486秒、Parquet读取与键聚合14.764秒、未归因9.828秒；累计唯一键4,302,144、重复0。
- [x] 新增可选按SQLite联合主键排序的UPSERT策略，保持原source顺序默认；每次报告显式标注write_order，并把最终SQLite全表摘要耗时单独统计。
- [x] 用户上传第36—40组相同起点SQLite主键排序A/B报告：两者累计唯一时间键4,918,521、重复0；pk-sorted总耗时50.922秒 vs source 55.484秒，SQL写入26.452秒 vs 30.969秒；仅一轮试验，默认顺序仍source。
- [x] 确认每轮`index_summary`全表扫描另耗约9.7—10.2秒，新增可选`--report-detail progress`：仅显示行组统计、异常和空间，把未审计的唯一/重复键置为null并清除过期缓存；全年完成时强制full核验。
- [x] 增加独立的 V3 SQLite 全量键统计只读审计命令：无需新增 Parquet RowGroup 即可重新扫描已完成的索引、比对源文件指纹和行组 footer、拒绝损坏的 checkpoint，保留不完全索引及自动并集阻断；7项离线测试已添加但仍待本机运行。参见 [V3 独立只读审计说明](PARQUET_5MIN_V3_READONLY_AUDIT_20261026.md)。
- [x] 用户本机在主V3索引35组时运行独立只读full审计：完整键4,302,144、重复0、耗时28.453秒，索引仍标记部分年度未完成；新增10组progress续建至45/522，候选源行累计5,534,876、异常时间0，SQLite主库+WAL约132.70MiB、192MiB软预算未触发。
- [x] 用户45组快报发现本轮总耗时1,318.813秒中旧分阶段计时未归因1,145.063秒（86.83%），另有第40号RowGroup SQLite提交79.235秒；新增SQLite checkpoint查询、Parquet footer、stdout和循环剩余墙钟分解及最慢整组时长诊断。详见 [45组异常墙钟诊断](PARQUET_5MIN_V3_WALL_GAP_PROFILE_20261026.md)；**目前仍不能确认慢因**。
- [x] 用户真实第46—47组复测已推进主V3至47/522，新增245,760源行16.687秒；`row_group_loop_other=0.0`、`unattributed_seconds=0.0`，先前45组的19分钟空档本轮未复现，不据此贸然调整SQLite写入策略。当前47组累计候选行5,780,603，但progress模式不提供精确唯一键/重复键数。
- [x] 新增可选`--max-run-seconds`单轮软墙钟预算，在完整RowGroup事务边界前后停止并可resume，避免异常停顿后继续处理大量组；默认行为不变，不中断事务。详见[47组复测与运行时间预算](PARQUET_5MIN_V3_SOFT_TIME_BUDGET_20261026.md)；新增3项离线合成测试，尚待本机核验。
- [x] 用户本地2025五分钟V3主索引已达52/522组，新增5组614,400行，耗时44.703秒（SQLite写入28.484秒、读取聚合16.203秒）；进程CPU30.469秒，未归因耗时和循环剩余耗时都为0。90秒时间软预算与192MiB磁盘软预算均未触发，停止原因`max_new_groups`；主库+WAL 141,204,728B。累计候选源行6,394,912，但`progress`报告没有完成新的唯一键/重复键审计。
- [x] 新增独立只读`compare-v3-write-order-ab.py`：两份V3索引分别完整full审计后，逐行对比`groups_done`、`daily_coverage`、`row_group_locator`三个逻辑表，验证同一源指纹、快照起点、处理范围及WAL模式，严格排除软预算提前停止，只有完全一致才允许计算性能差异；不会更改主索引与默认source顺序。8项合成测试已提交、尚待本机执行。详见[52组严格A/B说明](PARQUET_5MIN_V3_52GROUP_AB_CHECK_20261026.md)。
- [x] 用户在Windows Python3.11本机执行PR #25后的**109项**合成测试：5 failures、7 errors，集中在新增A/B测试。已查明`self.subTest`吞掉预期`ValueError`引发重复的5 FAIL+5 ERROR，另有两个`sqlite3.connect`测试句柄未关闭导致临时目录清理`WinError 32`；修复测试辅助函数和关闭连接、再新增1项防回归用例。详见[Windows A/B测试故障修复](PARQUET_5MIN_V3_AB_WINDOWS_TEST_FIX_20261026.md)，预计110项待本机复验。
- [ ] 先在主索引52组暂停并运行新的独立full只读审计（核对唯一键和重复键）；测试通过且磁盘有余量后，从同一52组V3快照建立两份**不同副本**，仅在第53—57组比较source与pk-sorted，随后运行严格A/B只读比较；不推进主索引，不自动下结论或生成并集。
- [x] 主V3索引52组独立只读full审计通过：有效唯一五分钟键6,394,912、候选源行6,394,912、重复键0、1,302,021个证券日分区、3,224,048条行组定位关系；没有新增RowGroup、修改SQLite或读取Parquet行情行。此结论只适用已处理52组。
- [x] 从同一52组快照建立source/pk-sorted两个副本，各新增第53—57组后运行严格A/B核验：两者57/522组，候选源键7,009,197=唯一键、重复0，逐行比对groups_done 57行、daily_coverage与row_group_locator各1,308,088行完全一致。source总耗时40.687秒/SQL写入25.156秒；pk-sorted总耗时40.859秒/写入26.233秒，第二轮排序并未加速（总耗时慢0.42%、写入慢4.28%）。第一轮排序快8.2%，第二轮未复现；继续保留source默认，主索引仍52组。
- [x] 针对写入占大部分耗时、但排序优化不稳定的证据，新增SQLite准备/daily UPSERT/locator UPSERT/groups_done写入/事务提交与余量的子阶段计时；只在成功提交后发布，保留已有`sqlite_group_commit`总计时，不对嵌套分项双重累加。新增3项离线合成测试，预计113项待本机核验，详见[第二轮A/B证据与SQL分项计时](PARQUET_5MIN_V3_AB_ROUND2_SQLITE_BREAKDOWN_20261026.md)。
- [x] 用户本机主V3索引已从52→57/522组，本轮新增5组614,400行、耗时40.828秒；SQLite写入25.923秒中`commit_and_other=15.156`秒（58.47%）、`row_group_locator_upsert=8.376`秒（32.31%）、`daily_coverage_upsert=2.047`秒（7.90%），计时子项守恒；主库+WAL约137.11MiB、无时间/容量预算触发。主库本轮progress未独立复核57组重复键，仍不得自动并集。
- [x] 为区分事务提交和其他开销，新增原SQLite连接`__enter__/__exit__`精确计时，汇总在`sqlite_transaction_boundary_seconds`，作为`commit_and_other`子项不重复计时；未修改SQL、WAL、`synchronous=FULL`、schema或事务行为。新增2项合成测试、调整既有断言，预计115项待本机验证。详见[57组主库与事务退出诊断](PARQUET_5MIN_V3_57GROUP_TRANSACTION_PROFILE_20261026.md)。
- [ ] Windows验证预计115项合成测试，从主库57组最多resume再增5组至62组（90秒/192MiB软预算、source/WAL/FULL），据真实`context_exit_seconds`占比决定后续严格隔离的持久化性能试验；不改变主库数据安全配置。
- [ ] 根据分段容量预算和吞吐率评估全年522个行组的落盘风险，确认磁盘空间可控后再完成年度索引与索引前后对账。
- [ ] 索引完成后记录全年跨RowGroup重复键及异常时标数量，明确源格式可信程度，随后推广其他年份与周期。
- [ ] 按真实年度索引运行结果检验跨Arrow批次及跨文件重复键（算法已开发、真实数据未验收），并验证其他周期的日期索引方案。
- [x] 完成最小只读五分钟并集候选计划；仅限少量股票单日，历史级与写入功能均未批准。
- [ ] 验证真实时间分区/证券分区的高性能核对方案，避免每天重复扫描6,408万行。
- [x] 用户本机提交2011—2026全品种日线报告及2025—2026股票候选日线报告（只读）；
- [ ] 对新修订后用户本地环境进行合成测试及更多分钟线实跑，确认时间归一化与金额/量单位后再完成2011—2026完整三周期。
- [ ] 重复键跨Arrow批次和多个Parquet分区去重、冲突双向检查；按唯一键重新计算覆盖数量。
- [ ] 为Parquet独有年份补充真实按证券/时间独立键数的核验，不把footer候选算作精确差集。
- [ ] 检查Parquet一年部分数据跨年、文件分区错误、数据源新增后resume缓存失效、临时盘容量不足等情况。
- [ ] 扩展15min/30min/60min/week/month周期及复权因子，明确没有对应H5源的单源状态。
- [ ] 大样本上验证历史代码映射/复权规则/交易所时钟与误差阈值。

## Phase 2：确认冲突规则并构建并集（未启动）

- [ ] 形成所有周期的成交量、成交额、价格缩放/复权/时间戳正规化映射表与测试矩阵。
- [ ] 设置清晰的来源优先级规则与禁止自动覆盖的异常类别；按证券/时间输出冲突裁决日志。
- [ ] 建立外部全量/分区索引或流式外排序，支持处理1GB+年度Parquet和大H5。
- [ ] 对互补且可信的独有K线形成转换后的并集副本，仅写 `H5ParquetReconciler/outputs/` 下的全新并集目录，严禁覆盖 `D:\stock`。
- [ ] 在模块 `outputs/` 目录输出H5和Parquet的可回读文件、完整索引、来源清单、文件哈希和回滚说明。
- [ ] 验收并集键数：`|H5 ∪ PQ| = |H5_only| + |PQ_only| + |intersection|`（前提是去重、归一化和元数据候选转真）；冲突每条有选取理由。

## Phase 3：增量数据维护与复用（未启动）

- [ ] 新增文件、年份和股票差异探测，执行增量更新并保存版本。
- [ ] 历史数据质量仪表盘（覆盖、缺失、异常分布和更新时间）。
- [ ] 读写H5/Parquet的独立库API，供A股研究、量化、模拟器复用。
- [ ] 自动化本地审计任务、回归测试、性能基准。

## 开发约束

1. 不上传付费原始行情到公开GitHub；只提交工具代码、合成测试与结果摘要（摘要如可能暴露授权数据，也应脱敏/留本地）。
2. 不要求付费Git LFS或GitHub Actions；测试先在本地Python3.11 venv执行。
3. 所有修改有PR和可追溯说明；本轮主目标是落地工具、明确需求，暂不直接生成并集。
4. 不将“程序没有匹配到”“Parquet文件年度footer总行数”“两源OHLC价格接近”误称为完整数据正确或V7可以使用。
