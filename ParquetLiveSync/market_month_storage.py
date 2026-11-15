#!/usr/bin/env python3
"""Streamed month append and crash-safe ledger for local canonical Parquet.

No global 2011+ history scan. Only the month being changed is read.
Canonical schema is ts:int64, symbol:string, OHLCVA:float64.
"""
from __future__ import annotations
from collections import Counter
from datetime import date, timedelta, datetime
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

import local_layout as L
from live_sync import WORK
import qmt_1m_private_month_bridge as B

FORMAT = "one_command_market_parquet_incremental_v1"
STATE_DIR = WORK / "market_update"
STATE_FILE = STATE_DIR / "commits.json"
CN_MS = 28800000
DAY_MS = 86400000
BATCH = 65536
SCHEMA = B.P.PRIVATE_SCHEMA
FIELDS = ("open", "high", "low", "close", "volume", "amount")


def _json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing/redirected updater receipt " + str(path))
    return json.loads(path.read_bytes())


def _save(path, payload):
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Linked updater state or journal")
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_suffix(path.suffix + ".part")
    if scratch.is_symlink():
        raise ValueError("Linked updater temp state")
    if scratch.exists():
        scratch.unlink()
    with scratch.open("xb") as out:
        out.write(B.P.canonical(payload))
        out.flush()
        os.fsync(out.fileno())
    os.replace(scratch, path)


def state_for(root, *, workspace=STATE_DIR):
    state = Path(workspace) / "commits.json"
    if not state.exists():
        return {"format": FORMAT,
                "canonical_storage_root": str(L.storage_root(root).resolve()),
                "periods": {"1min": {}},
                "status": "INCREMENTAL_WRITER_ONLY"}
    doc = _json(state)
    if (doc.get("format") != FORMAT
            or doc.get("canonical_storage_root") != str(L.storage_root(root).resolve())
            or not isinstance(doc.get("periods", {}).get("1min"), dict)):
        raise ValueError("Market updater ledger identity changed")
    return doc


def target_path(root, month):
    if month[:4] != "2026" or month not in ("2026-10", "2026-11"):
        # First supported rollout; later months require an explicit
        # rolling-window upgrade, not a hidden broad write.
        raise ValueError("Uncertified first-run target month " + month)
    market = L.storage_root(root) / "1min"
    if market.is_symlink():
        raise ValueError("Linked market minute folder")
    annual = market / "2026.parquet"
    if annual.exists() or annual.is_symlink():
        raise ValueError("2026 annual 1min Parquet already exists")
    output = market / (month + ".parquet")
    if output.is_symlink():
        raise ValueError("Linked target 1min month")
    return output


def _daily_group_rows(table):
    ts = table["ts"].to_numpy(zero_copy_only=False)
    days = np.unique((ts + CN_MS) // DAY_MS)
    epoch = date(1970, 1, 1)
    return [str(epoch + timedelta(days=int(n))) for n in days]


def _canonical(source):
    """Convert source's vendor symbols to existing canonical prefixed style."""
    L.validate_schema(source.schema)
    if source.num_rows == 0:
        return pa.Table.from_batches([], schema=SCHEMA)
    names = [L.normal_symbol(sym) for sym in source["symbol"].to_pylist()]
    columns = [source["ts"].cast(pa.int64()), pa.array(names, type=pa.string())]
    columns.extend(source[field].cast(pa.float64()) for field in FIELDS)
    result = pa.Table.from_arrays(columns, schema=SCHEMA)
    if any(pc.any(pc.is_null(c)).as_py() for c in result.columns):
        raise ValueError("Null market source column")
    return result


def adapt_241_private(source, category_offset_ms, month):
    """Drop ONLY proven zero-volume native 09:30 from 241-label QMT.

    Purchased minute history uses 240 trading-minute bars; DO NOT silently
    import a 241st auction placeholder as a real market trade.
    """
    raw = _canonical(source)
    local = np.asarray(raw["ts"].to_numpy(zero_copy_only=False), dtype=np.int64)
    native_label = ((local + CN_MS - int(category_offset_ms)) // 60000) % 1440
    placeholder = native_label == 9 * 60 + 30
    if not np.any(placeholder):
        raise ValueError("Private 241 QMT source lacks explicit 09:30 placeholder")
    volume = raw["volume"].to_numpy(zero_copy_only=False)
    amount = raw["amount"].to_numpy(zero_copy_only=False)
    if np.any(volume[placeholder] != 0) or np.any(amount[placeholder] != 0):
        raise ValueError("QMT 09:30 is not a verified zero-trade placeholder")
    out = raw.filter(pa.array(~placeholder))
    output = out["ts"].to_numpy(zero_copy_only=False)
    times = ((output + CN_MS) // 60000) % 1440
    standard = (((times >= 571) & (times <= 690))
                | ((times >= 781) & (times <= 900)))
    if not np.all(standard):
        raise ValueError("Calibrated QMT timestamps do not match 240 purchased minute labels")
    if any(d[:7] != month for d in _daily_group_rows(out)):
        raise ValueError("Private QMT day moved outside target month")
    return out, int(np.sum(placeholder))


def legacy_october_batches(root, *, baseline_loader=None):
    """Accepted pre-cutoff Oct 1..13 minute fragments from immutable dataset.

    Full source manifest is verified once; no 2011..2025 rows are imported.
    """
    from live_sync import baseline, BASE_MODULE, checked_path
    doc = (baseline_loader or baseline)()
    assert doc["asof_inclusive"] == "2026-10-13"
    lo = int(datetime(2026, 10, 1, tzinfo=L.UTC8).timestamp() * 1000)
    hi = int(datetime(2026, 10, 14, tzinfo=L.UTC8).timestamp() * 1000)
    refs = doc["period_physical_files"]["1min"]
    for item in refs:
        category = item.get("source_class")
        # Only the source fragments that could contain Oct1..13:
        # all private H5 minute references and the purchased 2026 shard.
        if category == "purchased_original":
            if "2026" not in item["relative_file"]:
                continue
            path = checked_path(root, item["relative_file"])
            # Purchased-source stats are intentionally not rewritten.
            stat = item.get("source_stat", {})
            if stat and (path.stat().st_size != stat.get("size_bytes")
                         or path.stat().st_mtime_ns != stat.get("mtime_ns")):
                raise ValueError("Old purchased 1minute Parquet source changed")
        elif category == "h5_only_verified_complete_stockday":
            path = checked_path(BASE_MODULE, item["relative_file"])
            if L.hash_file(path) != item.get("content_sha256"):
                raise ValueError("Old H5-only Oct 1minute source SHA changed")
        else:
            continue
        reader = pq.ParquetFile(path)
        try:
            L.validate_schema(reader.schema_arrow)
            for rowid in range(reader.num_row_groups):
                rg = reader.metadata.row_group(rowid)
                index = reader.schema_arrow.get_field_index("ts")
                stat = rg.column(index).statistics
                if stat and stat.has_min_max:
                    if stat.max < lo or stat.min >= hi:
                        continue
                for batch in reader.iter_batches(
                        batch_size=BATCH, row_groups=[rowid],
                        columns=list(L.COLS), use_threads=False):
                    original = pa.Table.from_batches([batch])
                    t = original["ts"]
                    keep = pc.and_(pc.greater_equal(t, pa.scalar(lo, pa.int64())),
                                   pc.less(t, pa.scalar(hi, pa.int64())))
                    selected = original.filter(keep)
                    if selected.num_rows:
                        yield _canonical(selected)
        finally:
            reader.close()


def private_oct_nov_batches(month, *, stage=B.P.BASE / "20261014_20261112",
                            plan=None):
    """Stream immutable already-calibrated QMT private month by stock group."""
    if plan is None:
        raise ValueError("Source proof plan must be supplied")
    private = Path(stage) / B.TARGET / (month + ".parquet")
    receipt = _json(private.with_suffix(".receipt.json"))
    if (receipt.get("month") != month or receipt.get("identity_sha256") !=
            plan["identity_sha256"]
            or receipt.get("month_coverage") != plan["months"][month]
            or receipt.get("sha256") != L.hash_file(private)):
        raise ValueError("Previously accepted QMT private month SHA changed")
    reader = pq.ParquetFile(private)
    try:
        if reader.num_row_groups != len(receipt["groups"]):
            raise ValueError("QMT private month row group inventory changed")
        for i, group in enumerate(receipt["groups"]):
            raw = reader.read_row_group(i)
            if B._arrow_digest(raw) != group["arrow_sha256"]:
                raise ValueError("QMT private month content SHA changed")
            code = group["symbol"]
            gate = B._calibration(plan["calib"], code[2:] + "." + code[:2])
            out, skipped = adapt_241_private(raw, gate["offset_ms"], month)
            if out.num_rows != group["rows"] - skipped:
                raise ValueError("QMT private minute count inconsistent with removed placeholder")
            yield out
    finally:
        reader.close()


def _verify_writer(temp, expected_rows):
    reader = pq.ParquetFile(temp)
    try:
        if reader.schema_arrow != SCHEMA or reader.metadata.num_rows != expected_rows:
            raise ValueError("Canonical physical month staged footer mismatch")
    finally:
        reader.close()
    if not expected_rows:
        raise ValueError("Refusing to install empty 1minute physical month")
    return L.hash_file(temp)


def install_month(root, month, chunks, *, source_id, days, state=None,
                  workspace=STATE_DIR, progress=print):
    """Transaction: idempotent append into existing original monthly file.

    Existing months can only be changed by THIS ledger; entirely new month
    files can be created without copying any full historical source.
    """
    target = target_path(root, month)
    work = Path(workspace)
    if work.is_symlink():
        raise ValueError("Linked updater workspace")
    work.mkdir(parents=True, exist_ok=True)
    ledger = state if state is not None else state_for(root, workspace=work)
    current = ledger["periods"]["1min"].get(month)
    if target.exists() and current is None:
        raise ValueError("Existing physical month has no updater ledger; refuse takeover")
    if current is not None:
        if (not target.is_file() or target.is_symlink()
                or L.hash_file(target) != current["sha256"]):
            raise ValueError("Physical month changed since previous updater commit")
        if source_id in current["sources"]:
            progress("MARKET_UPDATE_SKIP_SOURCE=" + month + " " + source_id[:16])
            return {"month": month, "status": "ALREADY_INSTALLED", "rows": current["rows"],
                    "added": 0, "sha256": current["sha256"]}
        present = set(current["days"])
        if present & set(days):
            raise ValueError("Overlapping trading date needs explicit repair, not blind append")
    else:
        if target.exists() or target.is_symlink():
            raise ValueError("Existing target not under updater control")
        present = set()
    expected_days = set(days)
    if not expected_days or any(d[:7] != month for d in expected_days):
        raise ValueError("Only nonempty same-month incoming day sets")
    scratch = work / (month + ".parquet.tmp")
    if scratch.is_symlink() or scratch.exists():
        raise ValueError("Unresolved previous updater temporary file: " + str(scratch))
    original_sha = current["sha256"] if current else None
    new_rows = 0
    old_rows = current["rows"] if current else 0
    accepted_days = set()
    try:
        writer = pq.ParquetWriter(scratch, SCHEMA, compression="zstd")
        try:
            if current:
                reader = pq.ParquetFile(target)
                try:
                    if reader.schema_arrow != SCHEMA or reader.metadata.num_rows != old_rows:
                        raise ValueError("Prior physical month schema/footer changed")
                    for batch in reader.iter_batches(batch_size=BATCH, use_threads=False):
                        writer.write_table(pa.Table.from_batches([batch]), row_group_size=BATCH)
                finally:
                    reader.close()
            for chunk in chunks:
                if chunk.schema != SCHEMA:
                    raise ValueError("Noncanonical incoming minute Arrow schema")
                if not chunk.num_rows:
                    continue
                for day in _daily_group_rows(chunk):
                    if day not in expected_days:
                        raise ValueError("Incoming market rows outside expected date inventory")
                    accepted_days.add(day)
                writer.write_table(chunk, row_group_size=BATCH)
                new_rows += chunk.num_rows
        finally:
            writer.close()
        if accepted_days != expected_days:
            raise ValueError("Market increment missing promised date(s)")
        digest = _verify_writer(scratch, old_rows + new_rows)
        if current and L.hash_file(target) != original_sha:
            raise ValueError("Physical month changed during staging")
        if current:
            backup = work / "backups" / (month + "-" + original_sha[:16] + ".parquet")
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.is_symlink():
                raise ValueError("Redirected physical backup")
            if not backup.exists():
                # On the same NTFS drive, hardlink is an O(1) immutable
                # old-file snapshot, avoiding duplicate GB-scale copies.
                try:
                    os.link(target, backup)
                except OSError:
                    import shutil
                    shutil.copyfile(target, backup)
            if L.hash_file(backup) != original_sha:
                raise ValueError("Physical backup does not match old SHA")
        else:
            backup = None
        next_entry = {"sha256": digest, "rows": old_rows + new_rows,
                      "days": sorted(present | accepted_days),
                      "sources": sorted(set(current["sources"] if current else []) | {source_id}),
                      "previous_sha256": original_sha,
                      "backup": str(backup) if backup else None}
        intent = work / ("intent-" + month + ".json")
        if intent.exists() or intent.is_symlink():
            raise ValueError("Existing updater transaction intent: inspect before retry")
        _save(intent, {"format": FORMAT, "month": month, "target": str(target),
                       "old_sha256": original_sha, "new": next_entry,
                       "source_id": source_id})
        os.replace(scratch, target)
        if L.hash_file(target) != digest:
            raise ValueError("Atomic physical month SHA differs from preflight")
        ledger["periods"]["1min"][month] = next_entry
        _save(work / "commits.json", ledger)
        intent.unlink()
        summary = {"month": month, "status": "COMMITTED",
                   "added": new_rows, "rows": old_rows + new_rows,
                   "sha256": digest, "original_backup": str(backup) if backup else None}
        progress("MARKET_MONTH_COMMITTED=" + json.dumps(summary, sort_keys=True))
        return summary
    finally:
        if scratch.exists() and not scratch.is_symlink():
            scratch.unlink()


def recover_intent(root, *, workspace=STATE_DIR):
    """Finish crash after atomic swap; never overwrite unrelated external bytes."""
    work = Path(workspace)
    ledger = state_for(root, workspace=work)
    for month in ("2026-10", "2026-11"):
        path = work / ("intent-" + month + ".json")
        if not path.exists():
            continue
        intent = _json(path)
        if (intent.get("format") != FORMAT or intent.get("month") != month
                or intent.get("target") != str(target_path(root, month))):
            raise ValueError("Untrusted interrupted market month transaction")
        target = target_path(root, month)
        if (not target.is_file() or target.is_symlink()
                or L.hash_file(target) != intent["new"]["sha256"]):
            raise ValueError("Interrupted month not at committed SHA; manual audit required")
        ledger["periods"]["1min"][month] = intent["new"]
        _save(work / "commits.json", ledger)
        path.unlink()
    return ledger
