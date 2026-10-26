# 2026五分钟H5/Parquet时间边界确认与两段主线实键对账

更新：2026-10-26。用户Windows本机上传 `dual-source-5min-2026-date-envelopes.json`。只保存时间范围和计数，不公开付费OHLCV。

## 一、本次真实元数据探针

| 检查 | 本地结果 |
|---|---:|
| H5满足A股候选代码的证券dataset | 5,579 |
| 其中2026年度至少有记录的dataset | 5,579 |
| H5全部候选dataset最新记录的全局日期 | **2026-10-13 15:00** |
| H5 2026年度最早记录时间 | 2026-01-05 09:35 |
| 最后记录落在2026-10的dataset数 | **5,562** |
| 最后记录落在2026-04/05/06/07的dataset数 | 分别3 / 2 / 10 / 2，合计17 |
| Parquet 2026五分钟年度分月文件数 | **9**，2026-01至2026-09 |
| Parquet行组总数 / 有效时间页脚行组数 | **407 / 407** |
| Parquet页脚候选五分钟终点最新时间 | **2026-09-30 15:00** |
| Parquet页脚候选五分钟终点最早时间 | 2026-01-05 09:35 |
| 建议的最新可能重叠窗口 | **2026-09-24 — 2026-09-30** |
| 对源行情写入 / 读取Parquet量价行 | **均无** |

这比上一轮2026-10-19至10-23的双源空窗口更加明确：H5在现有文件里最新停留于10月13日，而Parquet页脚最晚到9月30日。因此10月19日至23日双方都是0条完全符合该边界结果。H5 5,562只候选证券dataset的最新时刻属于2026年10月，但不能由其得出10月每一天都有完整48根，也不能简单声称H5比Parquet多了某个确定数量的有效K线。

**两段数据可能互补**：2026年9月底两源时间包络交叠，2026年10月1日至13日属于H5包络晚于Parquet元数据的阶段。时间页脚不是精确双源键覆盖、不是上市证券主数据、不是复权或时间口径认证。自动并集仍然禁止。

## 二、本轮增量代码更新

对`tools/inspect-h5-parquet-coverage-bounds.py`添加`suggested_h5_newer_window`建议，不需要通过用户自选时段猜测H5尾部：采用Parquet可靠页脚最后一个日期之后、H5最新年度记录日期之前的**最多7自然日**作为最小扫描窗口。示例：当前真实包络输入应给出`2026-10-07`至`2026-10-13`。与原`suggested_bounded_window`（最新可能重叠，9/24—9/30）相互独立。

新字段`proves_h5_only_keys=false`，因为这仍然只是源时间包络，不能取代原对账器的逐证券逐五分钟键核验；市场H5文件缺失、证券dataset元数据无效、Parquet未具有完整ts footer或无2026文件时拒绝给出“后缘”。新增3项纯合成测试：真实形状2026/9/30→10/13，H5不晚于PQ时不给窗口，缺失footer及源错误时拒绝并保护窗口上限。真实Windows验收须本机确认。

**注意：这份旧探针报告已经包含选窗所需的一切证据，不需要为了取得第二个建议字段再跑一遍H5 dataset边界探测。** 直接使用下面两段原双源核对命令更快。

## 三、下一步一口气执行两次真正的双源实键对比

仓库根目录执行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

测试成功后，先做**2026年9月最后一个可能重叠周**：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2026 --periods 5min --from-date 2026-09-24 --to-date 2026-09-30 --universe a-share-candidate --batch-size 8192 --read-only --out "reports\h5-parquet-5min-2026-09-24-30-overlap.json"
```

然后做**Parquet页脚截止日期以后H5可能有数据的最新窗口**：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2026 --periods 5min --from-date 2026-10-07 --to-date 2026-10-13 --universe a-share-candidate --batch-size 8192 --read-only --out "reports\h5-parquet-5min-2026-10-07-13-h5-newer.json"
```

全部报告JSON和Markdown只在`H5ParquetReconciler/reports/`，临时SQLite在模块`work/`并及时清理。不得覆盖已有报告；如果文件名已经被本地使用，请改成尚未用过的新文件名。源根目录`D:\stock`保持只读。把以上两份JSON一并上传后，就能量化：H5与购买Parquet在重叠期是否仍保持约60%量价差异；尾部H5实际新增多少键、按证券日和前缀如何分布、是否存在PQ末尾部分记录缺失；以及哪些冲突根源需要先确认。

如果当前只方便跑一次，优先重叠窗口`2026-09-24至30`，因为它同时含双源、可直接检验两源匹配规则。完成后继续H5独有尾部。在真实精确时间键/量价冲突确认前，不自动构建H5/Parquet合并副本。
