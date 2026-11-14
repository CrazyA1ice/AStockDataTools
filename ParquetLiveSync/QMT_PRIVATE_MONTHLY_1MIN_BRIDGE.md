# QMT 1m private calibrated month bridge (2026-10-14..2026-11-12)

The original full-stock and day-recovery private source, plus separately
accepted first-traded-open private sources, are the only inputs. They must
all be present and individually bound by unmodified SHA receipts. This
script never calls QMT/xtdata or a network API and never touches the user's
physical `D:\stock\AllCycleAStockData` or H5.

The Windows run on 2026-11-14 admitted **276/276** opening cases
to the isolated `opening_first_trade_v1` private source; the cumulative
QMT-derived source coverage is **114,739/114,749** stock-days
(27,652,099 original 241-grid minute bars), with 10 OHLCVA invalid cases
still quarantined. This is **source acceptance**, not a physical monthly
database merge.

On the Windows repository working tree (with local .venv), use:

Read-only checks and manifest preview:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-qmt-1m-private-month-bridge.ps1
```

After confirming the preflight report, write the private month increments:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-qmt-1m-private-month-bridge.ps1 -WritePrivate
```

Private outputs are created under ignored
`ParquetLiveSync/work/qmt_1min_market/20261014_20261112/private_monthly_1min_v1`:
`2026-10.parquet`, `2026-11.parquet`, and `.receipt.json` peers.
These are **partial-month increments**: October includes only Oct 14-30,
November only Nov 2-12. Neither is a full canonical physical month.

Entry gates: original official DAY calendar and month SHA source,
purchased 2026-09 calibration receipts, all original 5039 source SHA files
and original receipts, recovery 184 source/receipt hashes, opening
acceptance 181 receipt and accepted source hashes, exact disjoint
stock-day membership, and prior coverage report. Prior paid provider
calibration is applied to private copies: timestamp offset in milliseconds,
volume factor and amount factor separately for SH, SZ, STAR. Original
QMT source values remain unchanged, including the 09:30 special bar.

Each source Parquet is then rehashed, checked for original exact 241
minute grid and symbol, and streamed by stock/month into a bounded-memory
Arrow ParquetWriter. All private output rowgroups undergo complete Arrow
content SHA readback, row count/schema verification, and final Parquet file
SHA signing. Existing month files are verified, never overwritten.
Mismatched or interrupted output/receipt pairs fail closed, avoiding
silent replacement. Partial scratch files are cleaned on Python exceptions.

No production write is implemented; `production_merge_authorized=false`
in all private receipts. Ten original invalid OHLCVA stock-days remain
explicitly absent. The 09:30 zero-volume price artifacts are preserved as
raw source evidence, so the eventual production policy and 5m aggregation
must still be independently decided. Post-Nov 12 / Nov 13 onward and the
Oct 1-13 legacy purchased data are **not** included by this tool. The
final physical merge needs overlap/reconciliation and atomic backup/
restore checks and an explicit, separately approved production action.
