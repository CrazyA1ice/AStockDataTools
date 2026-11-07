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
