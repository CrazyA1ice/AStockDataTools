# 2026-10-28：通达信盘后增量的本地私有暂存层（首版，默认不入主库）

## 为什么现在推进主数据接口

2026-09的三只真实股票（SH600000、SZ000001、SZ300750）已经完成
5min整月键列覆盖核验：各21天×48键、合计3,024键/63股票日；
9个共同0键日均处于周末或中秋节休市。上交所和深交所于2026-09-17
均公告**09-25（周五）至09-27（周日）休市，09-28恢复交易**：
- 上交所公告：https://www.sse.com.cn/disclosure/announcement/general/c/c_20260915_10832273.shtml
- 深交所公告：https://www.szse.cn/www/disclosure/notice/general/t20260917_622911.html

用户最新`pq-202609-three-symbol-month-shared-5min-offline-audit.json`证实
90股票日组合、3,024个键、合计1,289行组定位项；
月报与独立09-30单日报**全部逐组计数一致**。
离线审计不读取Parquet/H5且不能证明购买源内容SHA；
3.900790秒是以前的**真实整月键列规划**耗时，不是离线审计自身耗时。

这些证据**仅说明三股票9月5min的键覆盖**，没有实现多源可信拼接。
现在停止扩大重复索引实验，进入标准化历史源/后续盘后增量的数据接口。

## 本轮真实实现：标准化本地JSON -> 私有候选版本 -> 显式可回滚

新增`tools/tdx-postclose-private-overlay.py`，支持三个CLI动作：

- `validate`：读取用户显式选择的**本地标准化JSON**，只做
  完整单证券日网格、OHLC关系、成交量额有限非负、日期/代码/来源契约校验；
  **只输出模块`reports/`下不含价格的安全结果**，不写私有数据。
- `stage`：在以上验证通过后，用户必须显式加
  `--allow-private-copy`，才能把这份单证券日真实bars以不可变版本
  保存在`H5ParquetReconciler/work/tdx_postclose_overlay/`（根目录
  `.gitignore`保护，**本机未加密**）。
  保存完整源输入字节SHA256与每个版本的标准化内容SHA256及
  先前活动版本SHA，`active.json`作为唯一活动版本指针；
  同输入重复stage是幂等的，旧版本完整保留。
- `rollback`：要求用户明确证券/周期/日期，仅回退活动版本到前一
  个版本；若无前一版本，则关闭活动指针。**不删除/覆盖任何原始
  Parquet、H5、通达信源文件或不可变私有版本**。回退成功的安全摘要
  仅写模块reports/；此操作不会更新现有正式主查询。

stage和rollback使用独占lock，所有指针更新先写同目录临时文件、
`fsync`后`os.replace`原子提交；版本有内容SHA校验和范围/时间网格
检查，目标路径拒绝符号链接逃逸，报告文件使用独占新建不覆盖。

**边界特别重要：这是中间层，不是直接解析通达信 .day/.lc1/.lc5 格式，
也不是购买Parquet/H5和通达信源的自动优选器，更不是把数据写入
正式主库。** 真实原生文件解码器需要用户提供具体TDX盘后格式样本
或字段文档后另行实现验证，尤其要确认开盘09:30、一分钟时间标签、
价格和量额单位/精度以及复权。不得先假定供应商时标完全一致。

## 输入JSON格式（仅作合成示例；值是虚构数字）

顶层严格字段：`format`、`source`、`symbol`、`date`、
`period`、`time_label_policy`、`bars`。

```json
{
  "format": "AStockDataTools normalized local postclose stock-day v1",
  "source": "tdx_postclose_local",
  "symbol": "SH600000",
  "date": "2026-10-27",
  "period": "day",
  "time_label_policy": "daily_session_date",
  "bars": [
    {
      "time": "00:00",
      "open": 10.00,
      "high": 11.00,
      "low": 9.00,
      "close": 10.50,
      "volume": 100.0,
      "amount": 1025.0
    }
  ]
}
```

此示例仅供代码验证，不代表浦发银行当天行情，不可拿作实际交易数据。

支持三个周期（本首版全量验证，不接纳残缺日）：
- `day`：1根，`time=00:00`、`time_label_policy=daily_session_date`。
- `5min`：48根，`time_label_policy=five_minute_start_label`，
  09:30..11:25及13:00..14:55，间隔5分钟。
- `1min`：241根，`time_label_policy=one_minute_end_plus_opening_0930`，
  上午09:30..11:30（含独立09:30），下午13:01..15:00；
  这是此前**Parquet实际样本**验证的约定，不代表已证实通达信原生
  的实际标签，必须先在用户本机转换后的私有文件上确认！

所有价格必须为有限正数，`high`不低于open/low/close，
`low`不高于open/high/close；volume/amount有限非负；
不进行乘100、复权、单位换算、自动填零或盘后差异覆盖。
**日期仅检查规范格式，不用网络/交易所历法自动宣称真实开市**；
只对已有完整网格的候选日做暂存，缺口不自动修复。

单文件最大256KiB，要求UTF-8无重复JSON键，无NaN/Infinity。
暂存路径形态：
`work/tdx_postclose_overlay/<period>/<YYYY-MM>/<symbol>/<YYYY-MM-DD>/versions/<sha256>.json`
以及本地活动指针`active.json`。版本是**本机未加密的真实价量额**，
禁止上传或提交`work/`目录。仅上传`reports/`安全摘要。

## 2026-10-28 Windows导入语法错误修复

用户本机`unittest discover`报告`tdx-postclose-private-overlay.py:373`
`SyntaxError: invalid syntax`，在导入阶段停止，**8项测试未实际执行**。
检查发现`result=dict(summary, "format": "...", ...)`错误混用字典字面量
`"key": value`与`dict()`调用语法。已改为
`dict(summary, **{"format": "...", ...})`，保持安全报告字段与业务行为原样，
并在既有CLI合成测试中增加`format`和6个安全标志校验。
语法尾段已单独通过Python的`compile()`检查；**完整模块Windows回归
仍要以用户本机命令的测试输出为准**。本轮不涉及真实源/私有版本修改，
不需要生成任何新行情或上传原始付费数据。

## Windows命令（仓库根目录）

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_tdx_postclose_private_overlay.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

将你**自行转换并且确认不是原始通达信二进制格式**的标准化
单证券日JSON保留在本机（例如`D:\stock\tdx-local-normalized\SH600000-20261027-day.json`），
不要上传到GitHub：

**先纯校验（无私有数据写入）**

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\tdx-postclose-private-overlay.py --action validate --input "D:\stock\tdx-local-normalized\SH600000-20261027-day.json" --out "reports\tdx-local-day-validate.json"
```

**用户决定暂存后才显式开启私有拷贝**

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\tdx-postclose-private-overlay.py --action stage --input "D:\stock\tdx-local-normalized\SH600000-20261027-day.json" --allow-private-copy --out "reports\tdx-local-day-stage.json"
```

**回退，仅调整独立暂存层指针**

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\tdx-postclose-private-overlay.py --action rollback --symbol SH600000 --period day --date 2026-10-27 --out "reports\tdx-local-day-rollback.json"
```

`reports/`拒绝同名文件覆盖，重复运行需换新名称。
没有实际通达信标准化样例时，**本轮仅跑合成测试，不可直接拿购买的
Parquet交易K线充当TDX输入来宣称接入成功**。
输入源`source`字段是输入格式合约，不会因此自动判定真实性。

## 未实现及后续验收

- 未读取或反解码通达信原生二进制文件；需要针对真实用户提供的
  格式说明/样本做只读转换adapter，且不能将真实价量额上传仓库。
- 未验证交易所官方每日交易日历、复权口径、成交量单位、TDX时间戳
  及原始源版本元数据；主查询完全不接入暂存层，不能声称增量已入库。
- 未实现实际的Parquet优先/H5后备/TDX增量合并或跨周期守恒审计；
  下一步先做同一证券日的3周期校验、版本冲突安全策略和回滚演练，
  再设计经人工审核的查询覆盖层，不能默认自动union。
- GitHub提交不包含真实K线数据，本轮test采用**纯合成值**。
  Windows完整单测/真实通达信样本验证均须本机后续提供实证。
