# 2025 purchased minute source-key month checkpoints (2026-11-05)

## Existing local evidence
- User-confirmed Windows run for 2025-01:
  - Synthetic tests: 6/6 PASS.
  - 1min: 96,965 observed purchased A-share stockdays; 23,368,565 exact source time keys, 241 per stockday.
  - 5min: 96,965 observed stockdays; 4,654,320 exact source time keys, 48 per stockday.
  - Both periods contain the same symbol set on each observed calendar date, zero detected weekend-source records.
  - Dates without purchased weekday rows: 2025-01-01 and 2025-01-28..31. This is **no source evidence**, NOT an independently checked exchange closure claim.
  - New key-only SQLite index created: 1, OHLCVA rows copied: 0.
- Existing separate 2025 source footer survey confirms original 2025 1min and 5min input envelopes span 2025-01-02..2025-12-31 but do **not** certify per-stockday completeness. The 2025 purchased 15/30/60 minute, day, week and month files have separately passed bounded read-only query samples.

## Resumable 2025 month runner
`tools/run-purchased-2025-minute-grid-checkpoint-batch.py` accepts `--root`, `--from-month`, `--through-month`, `--max-new-index-months N`, `--build-missing-private-index`. Default max new indexes=2; existing complete key indexes always take priority.

`run-purchased-2025-minute-grid-checkpoint-batch.ps1` runs both the existing six source-grid tests and the new six checkpoint tests, then processes months 2025-01..2025-12, creating at most 2 **new private source-key SQLite indexes** per invocation. Repeating the same command resumes from verified private month receipts and does not rescan already accepted months. This may require multiple invocations to finish the year.

New receipt path: `work/purchased_2025_minute_grid_batch/verified-purchased-source-grid-2025-MM.json`. This is aggregate source metadata/key counts only. Existing receipts require key-count conservation, verified stockday time grids, original source-stat signature match and existing index revalidation. Receipt conflicts, input drift and partial SQLite index files are not auto-removed or overwritten.

The runner does **not** read purchased OHLCVA or H5 bar content, does not re-materialize purchased price history, never modifies original market data and never activates the research query as a production source. SQLite source-key membership and private JSON checkpoints are its only new artifacts.

## Limits, safety and next steps
- Every **observed purchased A-share stockday** must have 241 1min and 48 5min timestamps and identical symbol sets across periods. This does not independently prove listing, suspension, exchange calendar, vendor amount/volume units or original H5 alignment.
- Saturdays/Sundays with any source rows cause failure. Weekdays absent from all bought rows remain unverified until compared to an independent trading calendar.
- If an existing monthly receipt/source fingerprint differs, STOP and review. Do not automatically delete private artifacts or write H5 fills.
- After completing monthly 2025 source-grid receipts, decide if H5 gap comparisons are warranted; do not automatically stage/merge H5 because a date is absent from purchased data.

## 2026-11-07 Windows full-year checkpoint result; new H5 exact-key stage

User's real Windows log confirms **12/12 months REUSE_VERIFIED_MONTH**, zero new indexes, no purchased OHLCVA copies, no H5 bar reads in the purchased-source-only stage. Both 1min and 5min passed 12 synthetic tests. Accepted 2025 purchased source: **1,316,686 A-share stockdays** in each period, **317,321,326 1min keys** and **63,200,928 5min keys**. No pending months. The key grid stage is complete **for observed purchased source stockdays**, not exchange-calendar-certified and not yet H5-difference-certified.

Next mainline reuses the **EXISTING** accepted 2025 source month receipt and its source-metadata-matched private SQLite index for **real original H5 vs purchased exact key differences**, rather than repeating 2025 purchased-only month audits. New files:

- `tools/audit-2025-purchased-h5-exact-minute-gap-months-readonly.py`: accepts 1 or 2 contiguous 2025 months, calls `verified_receipt` and the existing 2025 index planner, then invokes audited `audit-minute-index-window-readonly.py` per completed source-index window; checks that 1min and 5min purchased exact-key counts reconcile exactly with the accepted month receipt. Source file metadata is checked before/after the whole run and during indexed accesses. Prints per-day and per-month aggregates, never per-security OHLCVA. It never creates new source indexes, reports, Parquet/H5 bar files, or production pointers. Positive H5 differences remain unaccepted **candidates**, not approved fills.
- `tests/test_audit_2025_purchased_h5_exact_minute_gap_months_readonly.py`: **10 synthetic** no-write and source/checkpoint/index-drift guards, including receipt missing, purchased key conservation, index required, source drift, excessive date range and unlicensed market mutation rejection.
- `run-purchased-2025-vs-h5-exact-minute-gap-months-readonly.ps1`: Windows PowerShell 5.1 ASCII-only wrapper, tests first, then 2025-01..2025-02 real source exact-key audit by default; `-FromMonth 2025-03 -ThroughMonth 2025-04` etc. Default only two months to limit disk I/O and preserve bounded audit scope.

**Important:** The new H5 exact-key tool and tests are committed but **not yet verified with user's Windows H5 and licensed Parquet sources**. Its outcome for 2025 is unknown until run. `new_source_key_indexes_created=0`, `purchased_ohlcva_read_or_copied=false`, `production_activated=false`, `h5_candidate_keys_automatically_accepted=0` by contract. Existing H5 session grid, normalized 1min END / 5min START labels and H5 quarantines remain unchanged. Do not treat this as a vendor price/volume/amount unit certification, official listing/exchange calendar certification, or permission to merge original-market sources.

## 2026-11-07: real January-February 2025 H5 source-evidence asymmetry

User's Windows log for `run-purchased-2025-vs-h5-exact-minute-gap-months-readonly.ps1 -FromMonth 2025-01 -ThroughMonth 2025-02`: **10/10 synthetic tests PASS**, 43 candidate weekdays examined, accepted January and February purchased month receipts and both existing SQLite indexes reused, **no vendor Parquet/H5 writes**.

| Jan+Feb 2025 source-key audit | 1min | 5min |
| --- | ---: | ---: |
| Purchased A-share exact minute keys | 46,755,205 | 9,312,240 |
| Original H5 native rows examined | **0** | 9,206,928 |
| H5/purchased overlap | **0** | 9,206,928 |
| H5-only full purchased-stockday keys | 0 | 0 |
| H5-only partial purchased-stockday candidate keys | 0 | 0 |

**Critical interpretation:** no original 1min H5 native records were encountered for Jan-Feb (within the strict original H5 A-share candidate rules). Therefore the `0` H5-only 1min difference is **vacuous**: it is NOT independent confirmation that purchased 1min source is complete, and it does not imply that `sh_1min.h5`, `sz_1min.h5` or `bj_1min.h5` are absent for all dates. In contrast, 5min H5 actually has ~9.2 million comparable native records and zero additional keys in complete source stockdays. This remains a comparison of **keys** only, not OHLCVA vendor units or verified exchange trade truth.

The monthly key comparator now explicitly returns `h5_native_source_observed_during_audit_by_period`, and each month returns `h5_native_source_evidence_by_period`. It also prints a warning when no native 1min rows were examined and adds a synthetic negative-evidence regression test (11 tests in the monthly tool). Existing passed 10-test Windows result remains valid; new tests have **not** been executed on Windows yet.

**Next mainline** is **NOT** to rescan all remaining 2025 months blindly. Existing, already implemented `tools/probe-original-minute-source-ends-readonly.py` reads only each H5 per-symbol table's first and last native datetime, plus purchased Parquet footer times (no OHLCVA). New ASCII-only `run-2025-h5-minute-native-source-boundaries-readonly.ps1` runs this tool's two synthetic tests and the updated 11 monthly-regression tests, then prints each sh/sz/bj 1m/5m H5 source file first and last observed native timestamp and saves an aggregate-only new SAFE under `reports/`. If 1min H5 begins significantly later than 2025-02, prioritize the verified source overlap month rather than 2025-03..12 scans which contain no eligible H5 1m rows. Neither earliest/latest per-symbol envelope nor a 0-gap result proves full intraday source coverage, listing, trading calendar, adjustment regime, or amount units.

All operations preserve purchased-first precedence and do not authorize production merge or restart the retired purchased-source-copy GUI.

## 2026-11-07 H5 source-edge confirmation, then one 2025 1min monthly source inventory

Latest Windows real source-edge probe passed **11 revised 2025-gap tests + 2 original edge tests**. Source earliest observed per H5 native file (one security's first row; NOT continuous market-wide coverage):

| Venue | Native 1min first observed | Native 5min first observed | Native last (both) |
|---|---|---|---|
| Shanghai | 2021-05-17 09:31 | 2019-03-27 09:35 | 2026-10-13 15:00 |
| Shenzhen | 2025-08-07 09:31 | 2012-03-28 09:35 | 2026-10-13 15:00 |
| Beijing | 2026-01-08 09:31 | 2024-03-07 09:35 | 2026-10-13 15:00 |

2025 purchased 1min+5min footer maximums: 2025-12-31 (1min 15:00, 5min 14:55);
2026 purchased footer maximums: 2026-09-30. H5 native latest 2026-10-13.
These edges **do not contradict** the Jan/Feb 2025 1min zero native rows found by actual exact-key audits; a single 2021 Shanghai stock series might not represent 2025 Jan coverage. No company/symbol, licensed OHLCVA or source contents were exported.

**New bounded follow-up for the gap mainline:**
`tools/inventory-2025-h5-native-1min-month-coverage-readonly.py` uses the conservative existing 2025 A-share code filter and **native datetime-only bounded binary searches** over each `sh/sz/bj_1min.h5` candidate stock dataset to count true 2025 source rows by month and market, plus source series with observed rows. It does **not** open purchased Parquet, decode native OHLCVA or infer that month endpoints prove continuous daily coverage. Exact monthly row-count conservation, source metadata stability, input security-code filter, upper dataset/probe budget and only aggregate output are enforced. No per-security symbols or prices are emitted. A monthly positive row count does not imply a complete 240-minute session or certifiable H5 incremental value.

`tests/test_inventory_2025_h5_native_1min_month_coverage_readonly.py` adds **9 synthetic cases** including early 2021 SH record but zero 2025 Jan/Feb, nonconsecutive source months, SZ/BJ listing-era filtration, missing H5 file, bad budgets, bad first/last order, original market file hashes unchanged. ASCII-only `run-2025-h5-native-1min-month-coverage-readonly.ps1` runs these 9 + previously validated 2 original source-edge tests, then prints 12 aggregate market-month counts.

**No user-Windows real run has yet certified this new 2025 monthly 1min source inventory.** Interpret real output before scheduling any additional purchased-vs-H5 exact scans. Prioritize H5 native 1min months that actually have candidate source rows; where a market/month has no H5 1min evidence, the purchased-only data remains authoritative and there is no meaningful 1min H5 cross-validation. Keep possible 5min source-only deltas separate, retain zero accepted gap keys, no production merge.

## 2026-11-07 Windows verified true native H5 2025 1min monthly distribution

Real Windows run of `run-2025-h5-native-1min-month-coverage-readonly.ps1`:
**9 new synthetic tests + 2 prior source-boundary tests PASS**.
The new inventory used 170,178 native datetime-only scalar probes across
5,579 conservatively screened A-share candidate datasets in the three original
H5 market files; all original market files were unchanged, original purchased
Parquet was not opened, no H5 OHLCVA was decoded, and no production merge
was activated.

| Month 2025 | SH native 1min rows | SZ native 1min rows | BJ native 1min rows |
| --- | ---: | ---: | ---: |
| Jan-Aug (each month) | 0 | 0 | 0 |
| Sep | 1,920 | 3,600 | 0 |
| Oct | 21,360 | 15,600 | 0 |
| Nov | 5,355,600 | 6,737,520 | 0 |
| Dec | 12,626,160 | 15,828,720 | 0 |
| **2025 total** | **18,005,040** | **22,585,440** | **0** |

November+December account for 40,548,000 out of 40,590,480 observed
2025 eligible native H5 1min rows (about 99.9%). This **explains why
the earlier Jan-Feb original H5 1min-vs-purchased exact-key audit saw
zero H5 source records** despite a Shanghai 2021 all-time H5 file
first-record date: first/last file edges do not prove continuous monthly
eligible securities' coverage.

**Next real-data mainline**:
1. Run existing index-reuse-only `run-purchased-2025-vs-h5-exact-minute-gap-months-readonly.ps1 -FromMonth 2025-11 -ThroughMonth 2025-12` to inspect the major actual 1min H5 overlap; do NOT rebuild the accepted 2025 source-only monthly SQLite indexes.
2. Then run the same source-safe program on Sep-Oct 2025 for sparse earlier source 1min observations; if extra H5 keys are found, they are candidates only, not automatically accepted rows.
3. 2025 Jan-Aug original H5 **1min has zero eligible native records** under the 2025 A-share code filter, so any 1min H5 exact-key gap comparison is vacuous and should not be called cross-verification. **Do not skip corresponding 5min analysis**, since earlier Jan-Feb 5min source did have about 9.2 million observed native records and its zero H5-only key delta was actually measured. Mar-Aug 5min differences remain to be checked or accounted for separately.
4. Purchased Parquet is authoritative wherever a purchased stockday already exists; original vendor Parquet/H5 remain read-only; historical H5 units, listing, time-label semantics and exchange-calendar certification remain separate gates. Date coverage audit reports are private, with no new market OHLCVA and no active production pointer.

The 2025 1min native monthly inventory reports **raw timestamp rows by month**,
not unique valid 240-minute stockdays, trading days, verified H5 purchase
gaps, or proof of continuous source coverage within a month.
