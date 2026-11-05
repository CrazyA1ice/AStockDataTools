# Purchased-primary minute research query: verified Windows smoke and bounded batch

## Source priority and constraints
- Original purchased `D:\stock\AllCycleAStockData\{1min,5min}` Parquet is authoritative per **(symbol,period,day)** whenever ANY purchased minute keys exist for that stock-day.
- Only when a purchased stock-day is absent can a caller explicitly request existing, SHA-verified private H5-derived full stock-day rows. Partial purchased days are NEVER silently filled or overridden.
- The private fallback uses pre-existing immutable stage/union receipts and SHA-verified Parquet, rather than modifying original `D:\stock\HikyuuData` or writing a replacement bought-data copy.
- Purchasing source-index lookups must be backed by a unique, valid private SQLite bitmask window. Missing or overlapping indexes are errors, NOT permission to declare purchased data absent.
- No production active pointer changes, H5 mirror writes, private market file creation, or output of licensed OHLCVA to CLI. The Python API returns licensed bars in local process memory only.
- H5 price/volume/amount physical units are **not independently vendor-certified**. This is an opt-in **research-stage** query, not a production-certified dataset.
- 1min purchased keys generally include 09:30, while H5-derived full-session 1min bars use 09:31..15:00 (240); 5min uses 48 start-labelled bars for both. Do not synthesize nonexistent 09:30 data or override purchased bars.
- Existing H5 native 13:00 label anomalies on 2026-07-16 are quarantined; purchased 2026-07-16 minute source time-key grids were verified complete and remain authoritative.

## Windows evidence already observed by user (2026-11-05)
- The original 13 synthetic tests passed on local Windows.
- Original purchased 2026-09-30 SH600000: 1min=241, 5min=48, source/grid PASS.
- Existing corrected private H5 gap 2026-10-13 SH600000: 1min=240, 5min=48, SHA/native time/source PASS.
- The original single-security CLI queried 2026-09-30..2026-10-13: 1min=1,201, 5min=240. The intervening 2026-10-08/09/12 and 13 full-day H5 gap partitions already exist and match the exact-key audit counts (no restaging required).
- The original 13-test/single-security gate passed in the user's Windows environment. **The new six synthetic multi-security tests and two-security Windows batch smoke are not yet verified**.

## Current interfaces
- `H5ParquetReconciler/tools/query-purchased-primary-minute-with-private-gap-readonly.py`:
  - `query_bars(root, symbol, period, first, last, allow_verified_private_h5=False)`: existing single-security API.
  - `query_many(root, symbols, period, first, last, allow_verified_private_h5=False)`: bounded v1 batch for 1..8 distinct canonical symbols, returning in-memory bars and aggregate metadata only.
  - CLI `--symbol SH600000` or `--symbols SH600000 SZ000001` (mutually exclusive).
- `H5ParquetReconciler/run-purchased-primary-minute-query-smoke.ps1`: existing single-security 13-test real-data smoke.
- `H5ParquetReconciler/run-purchased-primary-minute-batch-smoke.ps1`: new multi-security synthetic/real-data gate, default SH600000+SZ000001, source window 2026-09-30..2026-10-13 and 1min/5min. It requires both securities to have present full regular purchased 2026-09-30 days and full existing private H5 2026-10-08,09,12,13 days. This is an acceptance expectation, not a claimed verified result.

## Next milestones
1. Pass the new six synthetic batch tests and two-security live smoke; no action on a failing source count until provenance checked.
2. Reuse verified 2026 monthly purchased source-key indexes for remaining month coverage, without rerunning completed 2..10 month data.
3. Expand missing data to the actual licensed 2025 minute source coverage and later 15/30/60 minute/week/month period read-only consumers.
4. Establish vendor unit/adjustment semantics and numeric cross-period consistency gates before production activation.
