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
