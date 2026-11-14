# QMT 1m first-traded-minute opening quarantine revalidation (2026-11-14)

## Evidence and scope

The pre-existing SHA-pinned 2026-10-14..2026-11-12 QMT source covered
114,463 of 114,749 stock-days; the 286 quarantine days contained
276 official DAY OHLC mismatch days and 10 invalid OHLCVA days.
Among those 276, QMT native local-DAT review found 261 days whose 09:31
open strictly matched the official DAY open, and 15 days whose FIRST
positive-volume/positive-amount minute strictly matched (12 at 09:32,
2 at 09:33, 1 at 09:34). **These are observations, not new admission
receipts.** Prior original 241-bar records remain unchanged.

## Run

On the Windows machine with QMT main client already running, using
the project .venv:

Read-only pilot (first 5 affected stocks):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-qmt-1m-opening-revalidation.ps1 -LimitStocks 5
```

Read-only all 276 candidates:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-qmt-1m-opening-revalidation.ps1
```

After inspecting the result and its rejection counts, create the **new private
source**, never touching official/production month files:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-qmt-1m-opening-revalidation.ps1 -WritePrivate
```

No download, subscription, standalone datacenter start, tick-period read,
TDX ZIP retrieval, old recovery receipt mutation, existing purchased
Parquet or H5 update is performed by this tool. A running QMT local
xtdata service is used only to call `get_local_data` against explicit
`D:\software\JHQMT\datadir`.

New files are exclusively inside ignored
`ParquetLiveSync/work/qmt_1min_market/20261014_20261112/opening_first_trade_v1`:
`source_parquet/<code>.parquet` and `receipts/<code>.json`.
The source retains the entire unchanged 241 native bars per accepted
day. Any rejected cases remain in the original `day_recovery`
quarantine, with reason recorded in the new receipt.

The safety checks include: original recovery receipt SHA and stage plan SHA;
per-DAT before/after SHA; 241 complete grid; original source aggregate
OHLC and volume/amount evidence; identical original price fields without
alteration; all pre-trade bars have BOTH zero volume and zero amount;
first strictly positive-volume/positive-amount minute open strictly
matches official DAY open; HLC of actual-trade bars and post-prefix bars
both pass the original official DAY tolerance; Arrow roundtrip, unique
timestamp keys, and immutable SHA receipts. Bad data fails closed.
Re-running verifies prior receipt and private source file hashes before
reuse. An interrupted orphan Parquet can be adopted only when its full
table exactly matches the newly revalidated 241-bar records.

The tool does **not** recalibrate/convert QMT volume and amount, resolve
the 10 invalid-OHLCVA days, prove the entire month universe, or authorize
physical 1min month merges. The separate monthly bridge must apply the
already independently measured paid calibration (vendor timestamp offset,
volume factor and amount factor) and perform its own full coverage,
source-key overlap and production transaction preflights. It must not
interpret any hypothetical coverage figure as an already completed merge.
