# P9 — 002328 source vintage, 002310 issuer connector: historical read-only review

**No apply, no pending clear, no deduplication, no approval. All five HOLD_PENDING.** PR #253 was owner-run 37/37 tests OK. Its validated packet SHA256 a704a50174e143141cc91a668a0898fd8ca9d725ea27206aa780a0e80647b117 is the only P9 source-scope pin.

## 002328.SZ HolderNum: approximate early disclosure versus exact later issuer report

| Source / date | 2026-09-30 shareholder count | Provenance quality |
| --- | ---: | --- |
| Third-party repost of investor interaction, 2026-10-12 | **about 57,900** | Secondary report, not authenticated original IR API |
| CNINFO issuer Q3 report PDF dated 2026-10-29, page 4 | **57,896** | Primary issuer reported exact period-end ordinary holder count |
| Previous QMT current version, declareDate=20261012 | 57900 | Historical QMT user cache observation, NOT reread live |
| Previous QMT historical version, declareDate=20261029 | 57896 | Historical snapshot, NOT reread live |

Investor-interaction repost: https://stock.quote.stockstar.com/info/notice_002328.shtml (2026-10-12 entry, explicit **约57900户**). Independent republisher with a company-answer rendering: https://webf10.gw.com.cn/SZ/B1/SZ002328_B1.html (quote attributes the roughly 5.79万 figure to China Securities Depository and Clearing data). Original issuer PDF: https://static.cninfo.com.cn/finalpage/2026-10-29/1225633534.PDF (page 4 screenshot checked, precise 57896). Official QMT dictionary: https://dict.thinktrader.net/dictionary/stock.html (shareholder=股东总数, shareholderA=A股东户数).

**Supported:** The earlier approximate source and later exact quarter report are real public representations at distinct dates and match the two historical QMT declareDate values. **Not supported:** A direct QMT ingestion origin link, an independently verified original investor-interaction API response, proof that 57900 is an issuer-certified exact count, any provider rounding algorithm, or instance-level equivalence of shareholder and shareholderA. Therefore 57896 vs 57900 is a likely vintage/precision lineage *hypothesis*, not an approved error correction. Both original records stay intact.

## 002310.SZ Top10Holder: issuer fullwidth dash, target QMT row still unpaired

CNINFO Q3 official PDF https://static.cninfo.com.cn/finalpage/2026-10-30/1225641410.PDF on page 4 (0-based page 3) visually shows the issuer sample name 北京朝投发投资管理有限公司－北京市盈润汇民基金管理中心（有限合伙）. Text extraction yields a **U+FF0D FULLWIDTH HYPHEN-MINUS** at the connector.

The exact historically disputed QMT old/new holder-name hashes remain ee1477b0b158cd0482a0e105eed893936d3b68b60edd2b307beb208285fffef3 and e14ebf59a2359a032c152b480b841e1772a394971c6d31404b2f2c40de775151. Their documented one-character mutation is U+002D ASCII hyphen-minus -> U+4E00 HAN ideograph 一. **The issuer sample was NOT independently mapped to this target QMT hash pair.** U+FF0D, U+002D, and U+4E00 must not be treated as the same character or the same shareholder identity absent target-level source proof. No NFKC/global replacement.

## Scope and controls

finance-disclosure-vintage-codepoint-20261125.json: preserves the two focused observations, all five historic HOLD_PENDING cases, unknown exact lineage, all prior per-symbol SHA256 and no approval flags. Its source is public material read on 2026-11-25; **the validator will NOT refetch these web pages or hash their source PDF binary.**

finance_disclosure_vintage_provenance_once.py: revalidates P6+P7+P8 exact archived evidence, requires P8 SHA256 a704a50174e143141cc91a668a0898fd8ca9d725ea27206aa780a0e80647b117, rejects any altered public-data assertions or permission flags, and prints one HOLD receipt per stock only after all checks.

tests/test_finance_disclosure_vintage_provenance_once.py contains 38 offline regression methods (P9 runner not yet owner-executed). The pinned Git-only runner stages files into a temporary folder; it does not call QMT, touch Parquet, pending ledger, immutable snapshots, PR #243, scheduled task or GitHub Actions. No actual recovery approval has been granted.

Next evidence request is an original 2026-10-12 investor-interaction record with precise time and source provenance and an independently matched full QMT 002310 target holder row; until then all five stay HOLD_PENDING.
