# 2025 purchased-minute 12-month exact-key audit: completed, and source totals reconciliation

## User-confirmed 2026-11-05 full-year result
The bounded batch ran five sequential passes and finished with:
`2025_FULL_YEAR_GRID_PASS` / `complete_private_key_grid_receipts_not_exchange_calendar` and no pending months. From the twelve private source-only receipts:
- Observed purchased A-share stockdays (2025): **1,316,686**, identical across 1min and 5min.
- All observed A-share stockdays had standard timestamp grids (1min=241, 5min=48); both periods' stock-day symbol sets matched; no weekend bars detected.
- Purchased selected A-share time keys: 1min **317,321,326**, 5min **63,200,928**.
- No originals modified, no purchased OHLCVA opened/copied and no H5 bar reads. No production data-source activation.
- These receipts are guarded by original source metadata and checked against existing private SQLite key indexes on reuse.

## Existing 2025 purchased source footer counts (independent earlier Windows audit)
- 1min=321,744,640, 5min=64,081,920, 15min=21,360,640, 30min=10,680,320, 60min=5,340,160.
- Each of the five cycle totals is exactly **1,335,040 theoretical standard-stockday equivalents** (divide by 241, 48, 16, 8, 4).
- Against the selected 2025 candidate A-share universe, the source/footer differences are:
  - 1min: **4,423,314** rows;
  - 5min: **880,992** rows;
  - both represent **18,354 theoretical stockday equivalents**.
- The 18,354 equivalent figure is an aggregate ratio. Its underlying source-symbol categories and per-security time-key completeness remain **UNCLASSIFIED**. Never automatically label these as non-A-share stocks, missing A-share data or complete individual stockdays without separate evidence.

## New low-cost 2025 reconciliation gate
- `tools/reconcile-2025-selected-minute-keys-to-five-cycle-footers-readonly.py` checks that all twelve saved month receipts remain valid against the current input source fingerprint and source-only SQLite index windows.
- Reads only the five purchased original Parquet **file footers**, never bar batches, original H5 or OHLCVA.
- Requires in-year, complete footer timestamp-statistics bounds, exact integer standard-stockday-equivalent row-count conservation and agreement between the 1min/5min unselected equivalent differences.
- On any mismatch or source drift it **fails closed**. Does not create new indexes, stage H5 data or touch production pointers. Does not treat any date as an independently certified exchange trading day.
- `tests/test_reconcile_2025_selected_minute_keys_to_five_cycle_footers_readonly.py`: seven synthetic contracts.
- `run-purchased-2025-minute-source-footer-reconciliation.ps1`: Windows tests first, then only private receipt revalidation and five-cycle Parquet footer reading.

This new reconciliation code has been committed but the user's Windows verification has **not yet run**. After a PASS, next inspect unselected source-symbol categories using a tightly bounded sample of `ts,symbol` (no OHLCVA), and independently check observed weekday dates against the official historical exchange calendar. These are research quality stages, not production activation.
