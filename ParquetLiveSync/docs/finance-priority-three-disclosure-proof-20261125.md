# 2026-11-25 financial priority-three: issuer disclosure / cache-hash cross-check

## Authority and limitations

This is an **offline, non-mutating evidence note** based on the owner's completed QMT read-only script output (2026-11-25 12:36 Beijing), exact SHA-256 hashes from that output, and public 2026-Q3 issuer announcements. It is **not a production clearance**, not a request to normalize source fields automatically, and not a replacement for the original cache records. The `finance_pending_audit_once.py` 53-stock run and `finance_priority_three_audit_once.py` 3-stock run left the ledger unchanged at SHA256 `4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1`.

All three symbols yielded `EXACT_SCOPED_CHANGE_REVIEW_REQUIRED`, unique old/current stable projections, exactly one old-only/new-only row, the same `endDate=20260930` and **unchanged other source fields in the matched pair**. Old and new full-row SHA256 are in the user's original QMT output, not reconstituted from these public strings.

### 002178.SZ — historic name matches issuer; spacing + type metadata changed

- Public quarter report reference: [延华智能 2026Q3 report reproduced by Sina Finance](https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12678209&stockid=002178), section II, top-10 holders, period ending 2026-09-30.
- Listed shareholder: `J.P.Morgan Securities PLC-自有资金` (shown as `境外法人` in the issuer's holder-nature column).
- Old QMT name `J.P.Morgan Securities PLC-自有资金` (30 Unicode code points), SHA256 UTF-8 `6f5502052dc88881981db2be07a676fc51cacbf2629923a58c796ee6cbbfb3a3`. **Matches the owner log's old SHA256 exactly.**
- Current QMT name `J.P.MorganSecurities PLC-自有资金` (29 code points), SHA256 `29e3154f8732d1b0603648d1dc87918fc2e24d053550458536120750dcce862c`. **Matches the owner log's new SHA256 exactly.** It differs only by a space after `Morgan`.
- QMT `type` changed `QFII机构` to `公司`; the issuer uses **境外法人**, which is not a proven one-to-one map to either QMT category. Preserve both type values and flag them for a provider taxonomy review.
- **Finding:** issuer-supported old name, deterministic whitespace-only difference, and a separate unverified category revision. No share-count difference in the paired row.

### 002310.SZ — a punctuation transcription, not holder rename

- Public source: [东方新能 2026Q3 issuer report (cninfo PDF)](https://static.cninfo.com.cn/finalpage/2026-10-30/1225641410.PDF), section II, page 5 top-10 holders. The relevant shareholder is `允能新开投资管理（天津）有限公司－天津允新远赢新能源股权投资合伙企业（有限合伙）`. The official document renders a connector dash, not ideographic Han `一`.
- Historic QMT 40-character transcription: `允能新开投资管理(天津)有限公司-天津允新远赢新能源股权投资合伙企业(有限合伙)` whose SHA256 UTF-8 is `ee1477b0b158cd0482a0e105eed893936d3b68b60edd2b307beb208285fffef3` — **exact match to owner's old name hash**.
- Current QMT 40-character transcription: `允能新开投资管理(天津)有限公司一天津允新远赢新能源股权投资合伙企业(有限合伙)` whose SHA256 is `e14ebf59a2359a032c152b480b841e1772a394971c6d31404b2f2c40de775151` — **exact match to owner's new name hash**.
- Only one character changes: ASCII hyphen-minus U+002D → ideograph `一` U+4E00. The current cache therefore has a visually similar but different *letter*, not a dash. These exact 40-character candidates were confirmed against BOTH owner-reported hashes; inference is not based on fuzzy similarity alone.
- **Finding:** owner hashes and issuer evidence support a single punctuation/transcription difference; old and current source versions must remain immutable. Do not globally replace Han `一` or auto-normalize all shareholder strings.

### 002328.SZ — original HolderNum figures corroborated by quarterly issuer disclosure

- Primary source: [新朋股份 2026Q3 issuer report (cninfo PDF)](https://static.cninfo.com.cn/finalpage/2026-10-29/1225633534.PDF), section II, page 4, says **period-end ordinary shareholders: 57,896** for 2026-09-30.
- Owner old QMT `HolderNum` record: `endDate=20260930`, `declareDate=20261029`, `shareholder=57896.0`, `shareholderA=57896.0`.
- Owner current QMT cache: same `endDate`, `declareDate=20261012`, `shareholder=57900.0`, `shareholderA=57900.0`; difference **+4** or **+0.00690894%** each.
- **Finding:** issuer explicitly corroborates old `shareholder` value, and the issuer report's 2026-10-29 announcement date corroborates old `declareDate` as the **quarter-report announcement**. The current 57,900 is numerically consistent with rounding to the nearest hundred but the evidence **does not establish that rounding occurred**; neither the number nor the `20261012` value is externally verified for this record. `shareholderA` is a provider-specific field; do not claim the issuer separately proves its precise semantics solely because the two QMT fields happen to agree here.
- Preserve older verified value as a supported reference; continue to classify the provider's new value as **unresolved discrepancy**. Do not amend original raw Parquet snapshots based on a report comparison alone; explicit versioned adjudication is still needed.

## Safe next implementation gate — no data writes

1. Keep **existing full source rows and snapshot metadata immutable**. Name transformations above are limited evidence for the two specific `(stock, table, endDate, row_sha256_old, row_sha256_new)` tuples, not global string normalization rules.
2. Add signed/pinned provenance manifest before authorizing a narrow, manually reviewed override. The manifest should contain exact old/new full-record hashes, original snapshot version, report key, issuer filing URL, issuer value, field scope, review state and explicit approval identity; it must not contain claims of unrestricted data validity.
3. A default strict importer must continue to quarantine these cases until a **separate** recoverable staged write path exists with backup, compare-and-swap ledger revision, immutable old+new versions, and post-write verification.
4. Provider `type` taxonomy for 002178 remains unsettled; no change to its business classification should be approved solely from its name spacing.
5. For 002328, prefer the issuer-verified `shareholder=57896` as the report-date reference but retain `57900` as the cache's latest raw observation, with explicit unverified-date flag. Never silently round, replace, or reinterpret the cached field.
6. PR #243 nightly 20:05 acceptance remains independent. No new QMT read is justified solely by these deterministic name-hash checks.

**Provenance proof is local hashing of the quoted public shareholder strings using SHA256(UTF-8).** It requires no access to the user's QMT data. See `tests/test_finance_priority_three_disclosure_proof.py` for regression assertions.
