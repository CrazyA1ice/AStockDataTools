# 2026-10-30：原H5/购买Parquet/已知TDX均截至10月13日，查找通达信实际盘后落点

## 本机真实验收（PR #167）

用户Windows `test_intake_tdx_native_day_to_private_postclose_json.py` **11/11 OK（0.446秒）**，真实`D:\\software\\TDX\\vipdoc\\sh\\lday\\sh600000.day`已由仓库原生完整32字节探测器只读逐行验证，SAFE `reports/tdx-native-day-intake-readonly-95551cbe6206.json`：

- `source_first_date=1999-11-10`；`source_last_date=2026-10-13`；`source_total_records=6404`。
- `requested_date=2026-10-29`；`native_candidate_stockday_rows=0`，状态`native_tdx_stockday_not_present`。没有创建新的真实行情副本、没有启用任何私有指针或更改原TDX/H5/购买Parquet/生产查询。
- 已确认指定的三股票原H5尾部为2026-10-13；购买2026`day` Parquet 9文件17页脚行组的**全股票**时间戳候选上界2026-09-30（不是指定股票真正最后交易日）。
- **三个已检查来源均未提供10月14日以后新日线；还没有调查其他TDX实例或下载存储目录。** 不应伪造行情、将过期来源用于自动合并、或无真实源证据运行整日H5补缺。

## 本轮功能：仅对明确指定路径做有界native TDX `vipdoc` 检查

新`tools/inventory-tdx-vipdoc-day-update-landing-readonly.py`仅在用户明确给出的最多4个目录内探测：

- 如果目录名就是`vipdoc`，直接查该目录。
- 否则检查`root/vipdoc`及**最多下一层**`root/<child>/vipdoc`，不递归整盘，单根目录直接枚举最多512项，全部候选`vipdoc`最多64处。
- 只读取明确给出的1～10只候选A股对应`vipdoc/sh/lday/shXXXXXX.day`、`vipdoc/sz/lday/szXXXXXX.day`等；以32字节原生记录的**最后8条**（或不足8条的全部）检查日期升序、有效日期/价格结构，并在源文件前后核验大小和mtime。
- 只输出每个根目录的序号、相对`vipdoc`位置、请求股票的序号（而非股票代码）、记录行数和**最后物理位置的日线日期**。仅将尾部实际日期晚于`--reference-last-day`（目前`2026-10-13`）的标为`newer_native_tail_candidates`。
- **尾部采样只是一条来源线索，不是源文件完整性审核。** 可能有更早位置坏记录、不同客户端目录、增量下载文件未合并到`.day`、来源修改时间导致元数据变化等；不能以此运行生产自动入库。如果发现新目录和更晚日期，后续对该**准确文件**用已验收的`probe-tdx-native-readonly.py`进行完整原生校验，再走已有显式隔离的盘后候选。
- 仅生成新脱敏`H5ParquetReconciler/reports/` JSON，**不含原始OHLCVA、股票代码或绝对路径**，不会创建任何私有Parquet/原生H5/TDX副本，不访问生产/私有活动指针。既有付费数据及其他源都完全不改。
- 如果所有给定根目录都无更新，工具只证明**这些明确的路径**里没有新记录尾部；此时下一步才应从客户端菜单或配置检查`盘后数据下载`是否已执行、登录交易终端实际使用哪个数据目录，不要尝试无授权重新下载。

## Windows单行受限验收（先13项合成测试，后仅只读源目录）

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/tdx-vipdoc-update-landing-inventory-20261030; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/tdx-vipdoc-update-landing-inventory-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_inventory_tdx_vipdoc_day_update_landing_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "13项合成测试失败，不查真实通达信路径" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\tdx-vipdoc-landing-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\inventory-tdx-vipdoc-day-update-landing-readonly.py --roots "D:\software\TDX" "D:\stock" --symbols SH600000 SZ000001 SH600519 --reference-last-day 2026-10-13 --out $out --read-only-explicit-roots; if ($LASTEXITCODE -ne 0) { throw "TDX真实数据落点核查失败" }; Write-Host "脱敏SAFE：$out"
```

如果有其他**已知确切TDX安装目录**，可替换或追加到`--roots`中（最多4个），避免无界整盘扫描。若某个显式目录不存在，脚本会拒绝，用户需要核对自己的实际目录，而不是自动退化到不可信全盘爬取。

**13项纯虚构TDX本机临时二进制测试尚未Windows执行，PR仍为Draft。** 仅分享终端结果和脱敏SAFE，不上传通达信二进制`.day`、付费Parquet/原H5或原价量额。

## 后续决策

如果存在晚于2026-10-13的TDX真实候选，先独立`probe-tdx-native-readonly.py`全文件顺序/32字节验证，再用`intake-tdx-native-day-to-private-postclose-json.py`明确对应交易日进行**默认仅SAFE验证**；真实有价量额且用户明确允许私有拷贝后才进入既有`work/tdx_postclose_native_intake/`。此时还须与购买Parquet优先规则、日线口径和分钟汇总数据对账，**不能直接将通达信日线写入主库或生产H5**。

如果所有根目录的可见原`.day`仍停在10/13，建议查通达信盘后下载是否正常、同机不同安装实例、终端数据目录重定向。未经新的真实来源供给，不再创建重复的历史源核对工具。
