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
import math
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

VERSION = "parquet-5min-coverage-index-v3"
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


def encode_group_ids(groups):
    """Canonical sorted unique unsigned LEB128 list of (row_group+1).

    Encodes a sparse row group at offset 521 in just two bytes, not a
    zero-padded 66-byte absolute position mask. No arbitrary upper bound.
    """
    result = bytearray()
    for group in sorted(set(groups)):
        if not isinstance(group, int) or group < 0 or group >= (1 << 63) - 1:
            raise ValueError("Invalid row group ID")
        number = group + 1
        while number >= 128:
            result.append((number & 127) | 128)
            number >>= 7
        result.append(number)
    return bytes(result)


def decode_group_ids(encoded):
    """Fail closed on invalid/truncated/malformed varints."""
    values = []
    number, shift = 0, 0
    for octet in bytes(encoded):
        number |= (octet & 127) << shift
        if octet & 128:
            shift += 7
            if shift >= 70:
                raise ValueError("Row group varint is too long")
        else:
            if number == 0:
                raise ValueError("Invalid zero row group token")
            values.append(number - 1)
            number, shift = 0, 0
    if shift:
        raise ValueError("Truncated row group varint")
    if values != sorted(set(values)) or encode_group_ids(values) != bytes(encoded):
        raise ValueError("Noncanonical or duplicate row group IDs")
    return values


def merge_group_ids(existing, added):
    """OR-set union of compact group-ID lists, including unordered resumes."""
    if not existing:
        return bytes(added)
    if not added:
        return bytes(existing)
    return encode_group_ids(decode_group_ids(existing) + decode_group_ids(added))


def connect_udfs(db):
    db.create_function("bitcount", 1, lambda n: int(n).bit_count(), deterministic=True)
    db.create_function("group_id_union", 2, merge_group_ids, deterministic=True)
    db.create_function("group_id_count", 1,
                       lambda v: len(decode_group_ids(v)), deterministic=True)


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
          group_ids BLOB NOT NULL,
          PRIMARY KEY(symbol, trade_day, file_id)
        ) WITHOUT ROWID;
    """)


def insert_group(db, file_id, row_group, packed, counts, write_order="source"):
    """Atomic UPSERTs in original or sorted primary-key order.

    Sorting affects only the order of commutative bitmask/row-count unions and
    group-id set unions. It must not alter any final indexes or safety gates.
    """
    if write_order not in ("source", "pk-sorted"):
        raise ValueError("Unsupported SQLite write ordering")
    # Keep the original iteration order as default for comparable benchmarks.
    items = packed.items() if write_order == "source" else sorted(packed.items())
    daily = [(sym, day, values[0], values[1])
             for (sym, day), values in items]
    encoded_group = encode_group_ids([row_group])
    groups = [(sym, day, file_id, encoded_group) for sym, day, _, _ in daily]
    with db:
        db.executemany("""
            INSERT INTO daily_coverage(symbol,trade_day,slot_mask,source_rows)
            VALUES(?,?,?,?)
            ON CONFLICT(symbol,trade_day) DO UPDATE SET
              slot_mask=(daily_coverage.slot_mask | excluded.slot_mask),
              source_rows=(daily_coverage.source_rows + excluded.source_rows)
        """, daily)
        db.executemany("""
            INSERT INTO row_group_locator(symbol,trade_day,file_id,group_ids)
            VALUES(?,?,?,?)
            ON CONFLICT(symbol,trade_day,file_id) DO UPDATE SET
              group_ids=group_id_union(row_group_locator.group_ids,excluded.group_ids)
        """, groups)
        db.execute("""
            INSERT INTO groups_done VALUES(?,?,?,?,?,?,?,?,?)
        """, (file_id, row_group, *(counts[k] for k in STATS)))


def open_index(index, manifest, resume, journal_mode="wal"):
    index.parent.mkdir(parents=True, exist_ok=True)
    existing = index.exists()
    if existing and not resume:
        raise ValueError(f"Index exists. Use --resume after checking source integrity: {index}")
    if not existing and resume:
        raise ValueError(f"--resume requested but index does not exist: {index}")
    db = sqlite3.connect(str(index), timeout=60)
    if journal_mode not in ("wal", "delete"):
        db.close()
        raise ValueError("Unsupported SQLite journal mode")
    try:
        actual = db.execute("PRAGMA journal_mode=" + journal_mode.upper()).fetchone()[0].lower()
    except Exception:
        db.close()
        raise
    if actual != journal_mode:
        db.close()
        raise ValueError("Unable to enable SQLite journal mode " + journal_mode)
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA busy_timeout=60000")
    db.execute("PRAGMA cache_size=-65536")  # 64 MiB SQLite page cache
    connect_udfs(db)
    signature = manifest_signature(manifest)
    if existing:
        try:
            saved = dict(db.execute("SELECT key,value FROM meta"))
            if saved.get("fingerprint") != signature:
                raise ValueError("Parquet source fingerprint mismatch: file size/mtime/file set, "
                                 "year or universe changed; refuse unsafe --resume, "
                                 "use a new index path")
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


def index_summary(db, manifest, row_groups_total, detail="full"):
    """Exact full audit or a visibly incomplete O(row_groups) progress report.

    On a partial year, scanning millions of stock-days and locator blobs on
    every small run takes measurable time. Progress mode skips those two
    full-table scans and never reports unknown unique/duplicate counts as zero.
    Finishing the final source row group ALWAYS performs a full audit.
    """
    if detail not in ("full", "progress"):
        raise ValueError("Unsupported report detail; use full or progress")
    row = db.execute(
        "SELECT " + ",".join("COALESCE(SUM("+key+"),0)" for key in STATS)
        + ",COUNT(*) FROM groups_done").fetchone()
    totals = dict(zip((*STATS, "row_groups_complete"), map(int, row)))
    groups_done = totals.pop("row_groups_complete")
    complete = groups_done == row_groups_total
    effective = "full" if complete else detail
    unique_key_count = duplicate_count = stock_days = None
    locator_rows = locator_memberships = mask_bytes = None
    if effective == "full":
        unique_key_count, raw_key_rows, duplicate_count, stock_days = db.execute("""
            SELECT COALESCE(SUM(bitcount(slot_mask)),0),
                   COALESCE(SUM(source_rows),0),
                   COALESCE(SUM(source_rows - bitcount(slot_mask)),0), COUNT(*)
            FROM daily_coverage
        """).fetchone()
        locator_rows, locator_memberships, mask_bytes = db.execute("""
            SELECT COUNT(*),COALESCE(SUM(group_id_count(group_ids)),0),
                   COALESCE(SUM(length(group_ids)),0)
            FROM row_group_locator
        """).fetchone()
        if int(raw_key_rows) != totals["candidate_rows"]:
            raise ValueError("Daily-key counts disagree with committed row-group statistics")
    else:
        # Exact groups_done totals; uniqueness/duplicate/locator metrics unknown.
        raw_key_rows = totals["candidate_rows"]
    return {
        "format": VERSION,
        "year": manifest["year"],
        "universe": manifest["universe"],
        "files": len(manifest["files"]),
        "row_groups_total": row_groups_total,
        "row_groups_complete": groups_done,
        "index_complete": complete,
        "report_detail_effective": effective,
        "full_key_audit_performed": effective == "full",
        "progress_metrics_require_full_audit": effective == "progress",
        "source_fingerprint_uses_only_file_size_mtime": True,
        "unique_regular_session_keys": (int(unique_key_count)
                                        if unique_key_count is not None else None),
        "candidate_source_rows": int(raw_key_rows),
        "duplicate_regular_session_keys": (int(duplicate_count)
                                           if duplicate_count is not None else None),
        "stock_day_partitions": (int(stock_days) if stock_days is not None else None),
        "row_group_locator_entries": (int(locator_memberships)
                                      if locator_memberships is not None else None),
        "row_group_locator_compact_rows": (int(locator_rows)
                                          if locator_rows is not None else None),
        "row_group_locator_payload_bytes": (int(mask_bytes)
                                            if mask_bytes is not None else None),
        "locator_storage": "one sorted unsigned LEB128 ID list per (symbol,day,file)",
        "row_group_locator_compression_ratio": (
            round(locator_memberships / locator_rows, 4)
            if locator_rows else None),
        "sqlite_main_estimated_allocated_bytes": (
            db.execute("PRAGMA page_size").fetchone()[0]
            * db.execute("PRAGMA page_count").fetchone()[0]
        ),
        "sqlite_wal_not_included_in_estimate": True,
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
        for file_id, encoded in db.execute(
                "SELECT file_id,group_ids FROM row_group_locator "
                "WHERE symbol=? AND trade_day=?", (sym, trade_day)):
            groups.setdefault(file_id, set()).update(decode_group_ids(encoded))
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


def index_storage_usage(db, path: Path):
    """Budget for logical DB and on-disk main+WAL.

    A SQLite WAL contains not-yet-checkpointed pages.  Use the *larger* of
    logical page allocation and actual main+WAL bytes; do not mistake a tiny
    main-file stat for the full allocation while WAL is active.  The limit is
    checked at whole-row-group transaction boundaries and is not a hard quota.
    """
    page_size = int(db.execute("PRAGMA page_size").fetchone()[0])
    page_count = int(db.execute("PRAGMA page_count").fetchone()[0])
    allocated = page_size * page_count
    physical = 0
    for candidate in (path, Path(str(path) + "-wal")):
        try:
            physical += candidate.stat().st_size
        except FileNotFoundError:
            pass
    return {
        "sqlite_logical_allocated_bytes": allocated,
        "sqlite_main_and_wal_on_disk_bytes": physical,
        "sqlite_budget_measure_bytes": max(allocated, physical),
        "sqlite_wal_file_included_if_present": True
    }


def budget_exceeded(usage: dict, max_mib: float | None) -> bool:
    return (max_mib is not None
            and usage["sqlite_budget_measure_bytes"] >= max_mib * 1024 * 1024)


def budget_check_after_wal_recovery(db, path: Path, max_mib: float):
    """Recover avoidable WAL space at a committed row-group boundary.

    A large WAL can temporarily duplicate the entire SQLite page file and
    falsely make the soft budget look exhausted. Only checkpoint *after*
    insert_group's transaction committed. A busy checkpoint cannot be treated
    as success; stop conservatively and preserve the existing index.
    """
    if db.in_transaction:
        raise ValueError("Cannot checkpoint SQLite WAL inside a transaction")
    before = index_storage_usage(db, path)
    if not budget_exceeded(before, max_mib):
        return False, before, None
    checkpoint_started = time.monotonic()
    busy, log_frames, checkpointed_frames = db.execute(
        "PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    checkpoint_seconds = time.monotonic() - checkpoint_started
    after = index_storage_usage(db, path)
    event = {
        "checkpoint_busy": bool(busy),
        "checkpoint_elapsed_seconds": checkpoint_seconds,
        "wal_frames_before": int(log_frames),
        "wal_frames_checkpointed": int(checkpointed_frames),
        "physical_bytes_before": before["sqlite_main_and_wal_on_disk_bytes"],
        "physical_bytes_after": after["sqlite_main_and_wal_on_disk_bytes"],
        "reclaimed_disk_bytes": max(
            0, before["sqlite_main_and_wal_on_disk_bytes"]
            - after["sqlite_main_and_wal_on_disk_bytes"])
    }
    return bool(busy) or budget_exceeded(after, max_mib), after, event


def clone_partial_index(source_path: Path, target_path: Path, manifest: dict):
    """Make a transactionally consistent SQLite snapshot for a journal A/B pilot.

    Source is read-only. Destination MUST be a fresh file inside module work/.
    Snapshot is version/fingerprint checked; no H5/Parquet licensed bars copied.
    """
    if source_path.resolve() == target_path.resolve():
        raise ValueError("Index clone target must differ from source")
    if target_path.exists():
        raise ValueError("Refusing to overwrite an existing index clone")
    if not source_path.is_file():
        raise ValueError("Source V3 index missing: " + str(source_path))
    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    try:
        meta = dict(source.execute("SELECT key,value FROM meta"))
        if meta.get("version") != VERSION:
            raise ValueError("Source index version is not V3")
        if meta.get("fingerprint") != manifest_signature(manifest):
            raise ValueError("Source index fingerprint differs from yearly Parquet inputs")
        if meta.get("completed") != "false":
            raise ValueError("Journal A/B pilot requires an incomplete checkpoint index")
        if source.execute("SELECT COUNT(*) FROM groups_done").fetchone()[0] == 0:
            raise ValueError("Source index has no completed row-group checkpoints")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(target_path))
        try:
            source.backup(target)
        finally:
            target.close()
        # Reopen copied target and verify backup before future mutation.
        cloned = sqlite3.connect(str(target_path))
        try:
            copy_meta = dict(cloned.execute("SELECT key,value FROM meta"))
            if copy_meta != meta:
                raise ValueError("SQLite index clone meta differs after backup")
            if source.execute("SELECT COUNT(*) FROM groups_done").fetchone()[0] != cloned.execute(
                    "SELECT COUNT(*) FROM groups_done").fetchone()[0]:
                raise ValueError("SQLite index clone checkpoints differ after backup")
        finally:
            cloned.close()
    except Exception:
        # Only a newly-created destination can be removed; never touch source.
        target_path.unlink(missing_ok=True)
        raise
    finally:
        source.close()


def row_group_loop_residual(loop_elapsed, phase_times):
    """Measured loop wall time outside individually timed nested stages.

    This can include Python overhead, blocked logging, OS scheduling gaps or
    machine suspension; never classify this residual as SQLite/Parquet CPU.
    WAL checkpoint seconds already live inside budget_guard_and_checkpoint.
    """
    nested = ("checkpoint_lookup", "parquet_read_and_key_aggregation",
              "sqlite_group_commit", "budget_guard_and_checkpoint",
              "progress_output")
    return max(0.0, loop_elapsed - sum(phase_times.get(k, 0.0) for k in nested))


def processing_profile(phase_times, group_timings, elapsed):
    """Aggregate group-stage wall time; avoid misleading CPU/I/O attributions.

    Arrow iter_batches is lazy, so the read/aggregation stage includes Parquet
    decompression, Arrow conversion and Python key normalization together.
    WAL checkpoint time is a SUBSET of the budget stage (do not add twice).
    """
    stages = ("parquet_metadata_open", "checkpoint_lookup",
              "parquet_read_and_key_aggregation", "sqlite_group_commit",
              "budget_guard_and_checkpoint", "progress_output",
              "row_group_loop_other", "final_index_summary")
    group_count = len(group_timings)
    known = sum(phase_times.get(name, 0.0) for name in stages)
    slow_read = sorted(group_timings,
                       key=lambda x: (-x["read_and_aggregate_seconds"],
                                      x["file_id"], x["row_group"]))[:5]
    slow_commit = sorted(group_timings,
                         key=lambda x: (-x["commit_seconds"],
                                        x["file_id"], x["row_group"]))[:5]
    slow_wall = sorted(
        (row for row in group_timings if "row_group_wall_seconds" in row),
        key=lambda x: (-x["row_group_wall_seconds"],
                       x["file_id"], x["row_group"]))[:5]
    return {
        "profiled_new_groups": group_count,
        "phases_seconds": {name: round(phase_times.get(name, 0.0), 3)
                           for name in stages},
        "wal_checkpoint_inside_budget_seconds": round(
            phase_times.get("wal_checkpoint_inside_budget", 0.0), 3),
        "unattributed_seconds": round(max(0.0, elapsed-known), 3),
        "slowest_parquet_read_and_aggregate_groups": slow_read,
        "slowest_sqlite_commit_groups": slow_commit,
        "slowest_row_group_wall_groups": slow_wall,
        "interpretation": (
            "Wall-clock stage estimates; Parquet decoding+key normalization are combined; "
            "WAL checkpoint time is included in budget guard, not additive. "
            "row_group_loop_other is a residual including Python loop/scheduling gaps, "
            "not proof of CPU or disk work. Wall time can include OS suspension or "
            "external I/O stalls. Clone setup and index opening precede this run timer.")
    }


def persist_report_certification(db, result):
    """Persist only verified stats; never publish stale duplicate=0 in progress mode."""
    with db:
        db.execute("UPDATE meta SET value=? WHERE key='completed'",
                   ("true" if result["index_complete"] and result["full_key_audit_performed"]
                    else "false",))
        db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                   ("full_key_audit_performed",
                    "true" if result["full_key_audit_performed"] else "false"))
        if result["full_key_audit_performed"]:
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                       ("duplicate_regular_session_keys",
                        str(result["duplicate_regular_session_keys"])))
        else:
            # Previous verified count is stale after an incomplete checkpoint.
            db.execute("DELETE FROM meta WHERE key='duplicate_regular_session_keys'")
        for key in ("bad_timestamp", "unexpected_session_stamp",
                    "unrecognized_symbol"):
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                       (key, str(result["row_groups_stats"][key])))


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
    ap.add_argument("--max-new-groups", type=int, default=None,
                    help="Optional smoke run limit; index stays incomplete and can resume later")
    ap.add_argument("--report-detail", choices=("full","progress"), default="full",
                    help="On incomplete indexes, progress skips exact key/duplicate scans; "
                         "last group always forces full audit")
    ap.add_argument("--max-index-mib", type=float, default=None,
                    help="Soft SQLite main+WAL space guard (MiB), checked after every completed row group")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--write-order", choices=("source","pk-sorted"), default="source",
                    help="SQLite UPSERT iteration ordering; source is existing default, pk-sorted is A/B pilot")
    ap.add_argument("--journal-mode", choices=("wal","delete"), default="wal",
                    help="Offline SQLite mode; default WAL. Use an index clone for comparable WAL/DELETE pilots")
    ap.add_argument("--clone-from-index", type=Path, default=None,
                    help="Copy an existing incomplete V3 index into new --out path before a bounded benchmark")
    ap.add_argument("--read-only", action="store_true", required=True,
                    help="Protect original data; local index and report are created inside module")
    args = ap.parse_args(argv)
    db = None
    try:
        if not 2000 <= args.year <= 2100:
            raise ValueError("Year outside supported range")
        if args.max_index_mib is not None and (
                not math.isfinite(args.max_index_mib) or args.max_index_mib <= 0):
            raise ValueError("--max-index-mib must be finite and >0")
        suffix = f"{args.year}-{args.universe}-v3"
        out, scratch = core.resolve_module_artifact_paths(
            args.out or Path("work") / "indexes" / f"pq-5min-{suffix}.sqlite", None)
        report, _ = core.resolve_module_artifact_paths(
            args.report or Path("reports") / f"pq-5min-{suffix}-index.json", None)
        root, _, _ = core.resolve_safe_paths(args.root, out, scratch)
        if report.exists():
            raise ValueError(f"Report exists, choose a new --report path: {report}")
        if out == report:
            raise ValueError("SQLite index and report must not be the same file")
        if args.clone_from_index is not None:
            if args.resume or args.out is None:
                raise ValueError("--clone-from-index needs a new explicit --out and must not use --resume")
            if args.max_new_groups is None:
                raise ValueError("Clone A/B benchmarks must specify --max-new-groups")
            if args.max_index_mib is None:
                raise ValueError("Clone A/B benchmarks must specify --max-index-mib")
        paths = core.year_files(root, "5min", args.year)
        if not paths:
            raise ValueError("Parquet year files not found")
        manifest = file_manifest(root, paths, args.year, args.universe)
        clone_origin = None
        if args.clone_from_index is not None:
            clone_origin, _ = core.resolve_module_artifact_paths(args.clone_from_index, None)
            if out.exists():
                raise ValueError("Index target exists; choose a fresh pilot --out path")
            clone_partial_index(clone_origin, out, manifest)
        db = open_index(out, manifest, args.resume or args.clone_from_index is not None,
                        journal_mode=args.journal_mode)
        import pyarrow.parquet as pq
        if args.max_new_groups is not None and args.max_new_groups < 1:
            raise ValueError("--max-new-groups must be >=1")
        started = time.monotonic()
        metadata_started = time.monotonic()
        open_files = [(filename, pq.ParquetFile(str(filename))) for filename in paths]
        total_groups = sum(pf.metadata.num_row_groups for _, pf in open_files)
        metadata_seconds = time.monotonic() - metadata_started
        newly_processed = 0
        source_rows_this_run = 0
        limit_reached = False
        budget_reached = False
        stopped_for = None
        wal_checkpoint_attempts = 0
        wal_checkpoint_busy = 0
        wal_disk_bytes_reclaimed = 0
        phase_times = {
            "parquet_metadata_open": metadata_seconds,
            "checkpoint_lookup": 0.0,
            "progress_output": 0.0,
            "row_group_loop_other": 0.0,
            "parquet_read_and_key_aggregation": 0.0,
            "sqlite_group_commit": 0.0,
            "budget_guard_and_checkpoint": 0.0,
            "wal_checkpoint_inside_budget": 0.0,
            "final_index_summary": 0.0
        }
        group_timings = []
        loop_started = time.monotonic()
        for file_id, (filename, pf) in enumerate(open_files):
            if not {"ts","symbol"}.issubset(pf.schema_arrow.names):
                raise ValueError(f"Parquet key columns absent in {filename.name}")
            for rg in range(pf.metadata.num_row_groups):
                lookup_started = time.monotonic()
                already_done = db.execute(
                    "SELECT 1 FROM groups_done WHERE file_id=? AND row_group=?",
                    (file_id, rg)).fetchone()
                phase_times["checkpoint_lookup"] += time.monotonic() - lookup_started
                if already_done:
                    continue
                if args.max_new_groups is not None and newly_processed >= args.max_new_groups:
                    limit_reached = True
                    stopped_for = "max_new_groups"
                    break
                group_wall_started = time.monotonic()
                if args.max_index_mib is not None:
                    budget_started = time.monotonic()
                    too_large, usage, checkpoint = budget_check_after_wal_recovery(
                        db, out, args.max_index_mib)
                    phase_times["budget_guard_and_checkpoint"] += time.monotonic() - budget_started
                    if checkpoint:
                        phase_times["wal_checkpoint_inside_budget"] += checkpoint[
                            "checkpoint_elapsed_seconds"]
                        wal_checkpoint_attempts += 1
                        wal_checkpoint_busy += int(checkpoint["checkpoint_busy"])
                        wal_disk_bytes_reclaimed += checkpoint["reclaimed_disk_bytes"]
                    if too_large:
                        budget_reached = True
                        stopped_for = (
                            "wal_checkpoint_busy_before_group"
                            if checkpoint and checkpoint["checkpoint_busy"]
                            else "max_index_mib_before_group")
                        break
                read_started = time.monotonic()
                batches = pf.iter_batches(row_groups=[rg], columns=["ts", "symbol"],
                                          batch_size=65536, use_threads=True)
                packed, counts = aggregate_batches(batches, args.year, args.universe)
                read_seconds = time.monotonic() - read_started
                write_started = time.monotonic()
                insert_group(db, file_id, rg, packed, counts,
                             write_order=args.write_order)
                write_seconds = time.monotonic() - write_started
                phase_times["parquet_read_and_key_aggregation"] += read_seconds
                phase_times["sqlite_group_commit"] += write_seconds
                group_timings.append({
                    "file_id": file_id, "row_group": rg,
                    "source_rows": counts["source_rows"],
                    "stock_day_partitions_in_group": len(packed),
                    "read_and_aggregate_seconds": round(read_seconds, 3),
                    "commit_seconds": round(write_seconds, 3)
                })
                newly_processed += 1
                source_rows_this_run += counts["source_rows"]
                if newly_processed % 5 == 0 or rg == pf.metadata.num_row_groups-1:
                    output_started = time.monotonic()
                    print(f"Index {filename.name} group {rg+1}/{pf.metadata.num_row_groups}, "
                          f"source rows in group={counts['source_rows']:,}, "
                          f"distinct stock-days in group={len(packed):,}, "
                          f"new groups={newly_processed}, "
                          f"elapsed={time.monotonic()-started:.1f}s", flush=True)
                    phase_times["progress_output"] += time.monotonic() - output_started
                if args.max_index_mib is not None:
                    budget_started = time.monotonic()
                    too_large, usage, checkpoint = budget_check_after_wal_recovery(
                        db, out, args.max_index_mib)
                    phase_times["budget_guard_and_checkpoint"] += time.monotonic() - budget_started
                    if checkpoint:
                        phase_times["wal_checkpoint_inside_budget"] += checkpoint[
                            "checkpoint_elapsed_seconds"]
                        wal_checkpoint_attempts += 1
                        wal_checkpoint_busy += int(checkpoint["checkpoint_busy"])
                        wal_disk_bytes_reclaimed += checkpoint["reclaimed_disk_bytes"]
                        if not too_large:
                            print("WAL checkpoint recovered temporary disk usage; "
                                  "continuing with durable row-group index", flush=True)
                    if too_large:
                        budget_reached = True
                        stopped_for = (
                            "wal_checkpoint_busy_after_group"
                            if checkpoint and checkpoint["checkpoint_busy"]
                            else "max_index_mib_after_group")
                        print(f"SOFT BUDGET reached after committed row-group "
                              f"(limit={args.max_index_mib:g} MiB); stopping with resumable index",
                              flush=True)
                        group_timings[-1]["row_group_wall_seconds"] = round(
                            time.monotonic() - group_wall_started, 3)
                        break
                group_timings[-1]["row_group_wall_seconds"] = round(
                    time.monotonic() - group_wall_started, 3)
            if limit_reached or budget_reached:
                break
        loop_elapsed = time.monotonic() - loop_started
        phase_times["row_group_loop_other"] = row_group_loop_residual(
            loop_elapsed, phase_times)
        summary_started = time.monotonic()
        result = index_summary(db, manifest, total_groups,
                               detail=args.report_detail)
        phase_times["final_index_summary"] = time.monotonic() - summary_started
        elapsed = time.monotonic()-started
        result["sqlite_journal_mode"] = db.execute("PRAGMA journal_mode").fetchone()[0].lower()
        result["sqlite_write_order"] = args.write_order
        result["report_detail_requested"] = args.report_detail
        result["clone_source_index"] = (
            clone_origin.relative_to(core.MODULE_DIR).as_posix()
            if clone_origin is not None else None)
        result["new_row_groups_this_run"] = newly_processed
        result["source_rows_this_run"] = source_rows_this_run
        result["elapsed_seconds_this_run"] = round(elapsed, 3)
        result["stage_profile_this_run"] = processing_profile(
            phase_times, group_timings, elapsed)
        result["new_groups_per_second"] = (
            round(newly_processed / elapsed, 5) if elapsed > 0 else None)
        result["run_limited_before_complete"] = bool(
            (limit_reached or budget_reached) and not result["index_complete"])
        result["max_index_mib_soft_budget"] = args.max_index_mib
        result["soft_budget_reached"] = budget_reached
        result["stopped_for"] = stopped_for
        result["wal_checkpoint_attempts_this_run"] = wal_checkpoint_attempts
        result["wal_checkpoint_busy_this_run"] = wal_checkpoint_busy
        result["wal_reclaimed_bytes_this_run"] = wal_disk_bytes_reclaimed
        result.update(index_storage_usage(db, out))
        persist_report_certification(db, result)
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
