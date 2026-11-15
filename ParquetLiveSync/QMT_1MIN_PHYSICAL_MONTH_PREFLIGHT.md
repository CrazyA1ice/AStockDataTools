# 1-minute physical-month entry preflight (READ-ONLY)

**Scope:** Existing `D:\stock\AllCycleAStockData\1min\2026-10.parquet`
and `2026-11.parquet` compared against previously materialized SHA-signed
PRIVATE increments for 2026-10-14..2026-11-12.

## Safe execution

One line from repo root, with project virtual environment:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-qmt-1m-physical-month-preflight.ps1
```

The runner first executes 7 synthetic offline tests. It then independently
validates old QMT receipts, pinned 2026-09 purchased calibration, all three
accepted stock-day source layers and the two **existing** private monthly
SHA receipts with *full Arrow row-group readback*. It reads (not modifies)
physical 1min target Parquet metadata and timestamp column, rehashing each
target file before and after scan. Missing target months are reported as
absent, not synthesized.

A shared **trading date** between the increment and the existing physical
month is conservatively reported as `BLOCKED_SHARED_TRADING_DATES`, even
if the exact (symbol,timestamp) keys might be disjoint; further exact-key
analysis is mandatory before any merge of such a month. A disjoint date
population is reported as `DATE_DISJOINT_CANDIDATE`. Neither is a write
permit. Physical 2026 annual 1min Parquet is a hard blocker.

The input is the 27,652,099-row private increment (Oct 16,337,149; Nov
11,314,950); 114,739/114,749 source stock-days accepted, with 10 excluded
`301139.SZ` days Oct 14..27 explicitly retained as unresolved. This tool
does NOT synthesize these missing stock-days, infer data after Nov 12,
or backfill Oct 1..13. Private 241 native labels preserve the 09:30 QMT
zero-trade placeholder and require a distinct future production policy.

This script is strictly read-only: no output files, archives, backups,
market updates, H5 writes, subscriptions, QMT downloads, or DAT reads.
It does not prove full key-level uniqueness of an existing physical month,
perform production transaction planning, or authorize physical merging.
Every report explicitly carries `production_merge_authorized=false`.
