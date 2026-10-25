#!/usr/bin/env python3
"""Build a resumable, compact Parquet five-minute key/row-group coverage index.

Reads ONLY (ts, symbol) from licensed yearly files. Persistent SQLite stores
symbol, exchange-local date, 48-slot bitmask, row count and row-group locators;
NO OHLCV values. Source files stay read-only. All artifacts stay inside
H5ParquetReconciler. This is an index, NOT a merged database or truth source.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "reconcile_engine_for_parquet_index", HERE / "reconcile-local-a-share-h5-parquet.py")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)

VERSION = "parquet-5min-coverage-index-v1"
DAY_ZERO = date(1970, 1, 1)
STATS = ("source_rows", "candidate_rows", "outside_year", "bad_timestamp",
         "unexpected_session_stamp", "unrecognized_symbol", "excluded_security_type")


def minute_slot(ts, year, cache=None):
    """Return (YYYYMMDD, slot [0..47]) only for valid A-share start-labeled 5min bars.

    Timestamps are interpreted as epoch milliseconds and Beijing local time.
    Reject unusual session labels rather than silently assigning them to a bar.
    """
    try:
        value = int(ts)
    except (ValueError, TypeError, OverflowError):
        return None, "bad_timestamp"
    if not 1_000_000_000_000 <= value < 10_000_000_000_000 or value % 60_000 != 0:
        return None, "bad_timestamp"
    minute = value // 60_000 + 8 * 60
    ordinal, minute_of_day = divmod(minute, 1440)
    try:
        if cache is not None and ordinal in cache:
            trade_day = cache[ordinal]
        else:
            trade_day = DAY_ZERO + timedelta(days=ordinal)
            if cache is not None:
                cache[ordinal] = trade_day
    except OverflowError:
        return None, "bad_timestamp"
    if trade_day.year != year:
        return None, "outside_year"
    if minute_of_day % 5:
        return None, "unexpected_session_stamp"
    if 570 <= minute_of_day <= 685:       # 09:30 .. 11:25
        slot = (minute_of_day - 570) // 5
    elif 780 <= minute_of_day <= 895:     # 13:00 .. 14:55
        slot = 24 + (minute_of_day - 780) // 5
    else:
        return None, "unexpected_session_stamp"
    return (int(trade_day.strftime("%Y%m%d")), slot), None


def aggregate_batches(batches, year, universe):
    """Compress a row group into at most one in-memory record per stock/date.

    Duplicate keys across batches/groups/files are computed globally later as
    SUM(source_rows - bit_count(slot_mask)); aggregation cannot conceal them.
    """
    packed = {}
    counts = Counter()
    cache = {}
    for batch in batches:
        ts_values = batch.column(0).to_pylist()
        symbols = batch.column(1).to_pylist()
        for ts, raw_symbol in zip(ts_values, symbols):
            counts["source_rows"] += 1
            symbol = core.symbol_id(raw_symbol)
            if symbol is None:
                counts["unrecognized_symbol"] += 1
                continue
            if universe == "a-share-candidate" and not core.is_a_share_candidate(symbol, year):
                counts["excluded_security_type"] += 1
                continue
            result, err = minute_slot(ts, year, cache)
            if err:
                counts[err] += 1
                continue
            day, slot = result
            key = (symbol, day)
            row = packed.get(key)
            if row is None:
                packed[key] = [1 << slot, 1]
            else:
                row[0] |= 1 << slot
                row[1] += 1
            counts["candidate_rows"] += 1
    return packed, counts


def file_manifest(root, paths, year, universe):
    files = []
    for file in paths:
        st = file.stat()
        files.append({
            "relative_path": file.relative_to(root).as_posix(),
            "bytes": st.st_size, "mtime_ns": st.st_mtime_ns
        })
    return {"version": VERSION, "year": year, "period": "5min",
            "universe": universe, "files": files}


def manifest_signature(manifest):
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def create_tables(db):
    db.executescript("""
        CREATE TABLE meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE groups_done (
          file_id INTEGER NOT NULL,
          row_group INTEGER NOT NULL,
          source_rows INTEGER NOT NULL,
          candidate_rows INTEGER NOT NULL,
          outside_year INTEGER NOT NULL,
          bad_timestamp INTEGER NOT NULL,
          unexpected_session_stamp INTEGER NOT NULL,
          unrecognized_symbol INTEGER NOT NULL,
          excluded_security_type INTEGER NOT NULL,
          PRIMARY KEY(file_id, row_group)
        ) WITHOUT ROWID;
        CREATE TABLE daily_coverage (
          symbol TEXT NOT NULL,
          trade_day INTEGER NOT NULL,
          slot_mask INTEGER NOT NULL,
          source_rows INTEGER NOT NULL,
          PRIMARY KEY(symbol, trade_day)
        ) WITHOUT ROWID;
        CREATE TABLE row_group_locator (
          symbol TEXT NOT NULL,
          trade_day INTEGER NOT NULL,
          file_id INTEGER NOT NULL,
          row_group INTEGER NOT NULL,
          PRIMARY KEY(symbol, trade_day, file_id, row_group)
        ) WITHOUT ROWID;
    """)


def insert_group(db, file_id, row_group, packed, counts):
    """One SQLite transaction per Parquet row group; rollback is automatic on error."""
    daily = [(sym, day, values[0], values[1])
             for (sym, day), values in packed.items()]
    groups = [(sym, day, file_id, row_group) for sym, day in packed]
    with db:
        db.executemany("""
            INSERT INTO daily_coverage(symbol,trade_day,slot_mask,source_rows)
            VALUES(?,?,?,?)
            ON CONFLICT(symbol,trade_day) DO UPDATE SET
              slot_mask=(daily_coverage.slot_mask | excluded.slot_mask),
              source_rows=(daily_coverage.source_rows + excluded.source_rows)
        """, daily)
        db.executemany("""
            INSERT OR IGNORE INTO row_group_locator(symbol,trade_day,file_id,row_group)
            VALUES(?,?,?,?)
        """, groups)
        db.execute("""
            INSERT INTO groups_done VALUES(?,?,?,?,?,?,?,?,?)
        """, (file_id, row_group, *(counts[k] for k in STATS)))


def open_index(index, manifest, resume):
    index.parent.mkdir(parents=True, exist_ok=True)
    existing = index.exists()
    if existing and not resume:
        raise ValueError(f"Index exists. Use --resume after checking source integrity: {index}")
    if not existing and resume:
        raise ValueError(f"--resume requested but index does not exist: {index}")
    db = sqlite3.connect(str(index), timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA busy_timeout=60000")
    db.create_function("bitcount", 1, lambda n: int(n).bit_count(), deterministic=True)
    signature = manifest_signature(manifest)
    if existing:
        try:
            saved = dict(db.execute("SELECT key,value FROM meta"))
            if saved.get("fingerprint") != signature:
                raise ValueError("Underlying Parquet size/mtime/file set, year or universe changed; "
                                 "refuse unsafe --resume, use a new index path")
            if saved.get("version") != VERSION:
                raise ValueError("Incompatible saved key index format")
        except (sqlite3.DatabaseError, ValueError):
            db.close()
            raise
    else:
        try:
            create_tables(db)
            with db:
                db.executemany("INSERT INTO meta(key,value) VALUES(?,?)", (
                    ("fingerprint", signature),
                    ("version", VERSION),
                    ("manifest", json.dumps(manifest, ensure_ascii=False, sort_keys=True)),
                    ("completed", "false")
                ))
        except Exception:
            db.close()
            index.unlink(missing_ok=True)
            raise
    return db


def index_summary(db, manifest, row_groups_total):
    scanned = dict(db.execute(f"""
        SELECT {','.join('COALESCE(SUM('+k+'),0)' for k in STATS)},
               COUNT(*) FROM groups_done
    """).fetchone().__iter__() if False else [])
    row = db.execute(
        "SELECT " + ",".join("COALESCE(SUM("+key+"),0)" for key in STATS)
        + ",COUNT(*) FROM groups_done").fetchone()
    totals = dict(zip((*STATS, "row_groups_complete"), map(int, row)))
    unique_key_count, raw_key_rows, duplicate_count, stock_days = db.execute("""
        SELECT COALESCE(SUM(bitcount(slot_mask)),0),
               COALESCE(SUM(source_rows),0),
               COALESCE(SUM(source_rows - bitcount(slot_mask)),0), COUNT(*)
        FROM daily_coverage
    """).fetchone()
    locator_count = db.execute("SELECT COUNT(*) FROM row_group_locator").fetchone()[0]
    assert int(raw_key_rows) == totals["candidate_rows"], (
        "Daily-key counts disagree with committed row-group statistics")
    return {
        "format": VERSION,
        "year": manifest["year"],
        "universe": manifest["universe"],
        "files": len(manifest["files"]),
        "row_groups_total": row_groups_total,
        "row_groups_complete": totals.pop("row_groups_complete"),
        "index_complete": (row_groups_total == len(list(db.execute(
            "SELECT file_id,row_group FROM groups_done")))),
        "source_fingerprint_uses_only_file_size_mtime": True,
        "unique_regular_session_keys": int(unique_key_count),
        "candidate_source_rows": int(raw_key_rows),
        "duplicate_regular_session_keys": int(duplicate_count),
        "stock_day_partitions": int(stock_days),
        "row_group_locator_entries": int(locator_count),
        "row_groups_stats": totals,
        "security_master_certified": False,
        "timestamp_5min_convention_certified": False,
        "safe_to_automatically_union": False,
        "no_raw_ohlcv_in_index": True,
        "source_files_modified": False
    }


def index_matches_and_groups(db, symbols, trade_day):
    """Trusted caller must first verify saved source metadata and completion."""
    groups = {}
    for sym in symbols:
        for file_id, rg in db.execute(
                "SELECT file_id,row_group FROM row_group_locator "
                "WHERE symbol=? AND trade_day=?", (sym, trade_day)):
            groups.setdefault(file_id, set()).add(rg)
    return {key: sorted(value) for key, value in groups.items()}


def validate_existing_index(index, root, year, universe):
    """Verify complete checkpoint and source manifest before using locators."""
    paths = core.year_files(root, "5min", year)
    if not paths:
        raise ValueError("Parquet yearly source files absent; cannot validate index")
    manifest = file_manifest(root, paths, year, universe)
    if not index.is_file():
        raise ValueError(f"Coverage index missing: {index}")
    db = sqlite3.connect(f"file:{index.as_posix()}?mode=ro", uri=True)
    try:
        saved = dict(db.execute("SELECT key,value FROM meta"))
        if saved.get("fingerprint") != manifest_signature(manifest):
            raise ValueError("Index source fingerprint changed; rebuild from scratch")
        if saved.get("version") != VERSION or saved.get("completed") != "true":
            raise ValueError("Coverage index incomplete or incompatible")
        for file_id, path in enumerate(paths):
            import pyarrow.parquet as pq
            pf = pq.ParquetFile(str(path))
            expected = pf.metadata.num_row_groups
            count = db.execute("SELECT COUNT(*) FROM groups_done WHERE file_id=?",
                               (file_id,)).fetchone()[0]
            if count != expected:
                raise ValueError("Coverage index row-group checkpoint count differs from source")
    finally:
        db.close()
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--universe", choices=("all", "a-share-candidate"),
                    default="a-share-candidate")
    ap.add_argument("--out", type=Path, default=None,
                    help="SQLite coverage index under module, default work/indexes/...")
    ap.add_argument("--report", type=Path, default=None,
                    help="JSON summary under module, default reports/...")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--read-only", action="store_true", required=True,
                    help="Protect original data; local index and report are created inside module")
    args = ap.parse_args(argv)
    db = None
    try:
        if not 2000 <= args.year <= 2100:
            raise ValueError("Year outside supported range")
        suffix = f"{args.year}-{args.universe}"
        out, scratch = core.resolve_module_artifact_paths(
            args.out or Path("work") / "indexes" / f"pq-5min-{suffix}.sqlite", None)
        report, _ = core.resolve_module_artifact_paths(
            args.report or Path("reports") / f"pq-5min-{suffix}-index.json", None)
        root, _, _ = core.resolve_safe_paths(args.root, out, scratch)
        if report.exists():
            raise ValueError(f"Report exists, choose a new --report path: {report}")
        if out == report:
            raise ValueError("SQLite index and report must not be the same file")
        paths = core.year_files(root, "5min", args.year)
        if not paths:
            raise ValueError("Parquet year files not found")
        manifest = file_manifest(root, paths, args.year, args.universe)
        db = open_index(out, manifest, args.resume)
        import pyarrow.parquet as pq
        started = time.monotonic()
        total_groups = 0
        for file_id, filename in enumerate(paths):
            pf = pq.ParquetFile(str(filename))
            if not {"ts","symbol"}.issubset(pf.schema_arrow.names):
                raise ValueError(f"Parquet key columns absent in {filename.name}")
            for rg in range(pf.metadata.num_row_groups):
                total_groups += 1
                if db.execute("SELECT 1 FROM groups_done WHERE file_id=? AND row_group=?",
                              (file_id, rg)).fetchone():
                    continue
                batches = pf.iter_batches(row_groups=[rg], columns=["ts", "symbol"],
                                          batch_size=65536, use_threads=True)
                packed, counts = aggregate_batches(batches, args.year, args.universe)
                insert_group(db, file_id, rg, packed, counts)
                if total_groups % 10 == 0 or rg == pf.metadata.num_row_groups-1:
                    print(f"Index {filename.name} group {rg+1}/{pf.metadata.num_row_groups}, "
                          f"source rows in group={counts['source_rows']:,}, "
                          f"distinct stock-days in group={len(packed):,}, "
                          f"elapsed={time.monotonic()-started:.1f}s", flush=True)
        result = index_summary(db, manifest, total_groups)
        with db:
            db.execute("UPDATE meta SET value=? WHERE key='completed'",
                       ("true" if result["index_complete"] else "false",))
        result["saved_index"] = out.relative_to(core.MODULE_DIR).as_posix()
        result["source_fingerprint"] = manifest_signature(manifest)
        report.parent.mkdir(parents=True, exist_ok=True)
        staging = report.with_name(report.name + ".tmp")
        staging.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
        staging.replace(report)
        print("Saved index:", out, "and summary:", report, flush=True)
    except (ValueError, OSError, sqlite3.Error, OverflowError, AssertionError) as exc:
        ap.error(str(exc))
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    main()
