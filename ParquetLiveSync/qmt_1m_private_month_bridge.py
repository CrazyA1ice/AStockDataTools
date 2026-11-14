#!/usr/bin/env python3
"""Build SHA-verified *private* 1min month increments from three QMT receipt layers.

2026-10-14..2026-11-12 only. Never downloads QMT, touches H5 or writes
AllCycleAStockData. Original QMT 241 bars and their receipts remain intact.
Output uses the separately verified purchased-provider time/volume/amount
calibration, but does NOT imply authorization to merge physical market months.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

import local_layout as L
import qmt_1m_pipeline as P
import qmt_1m_recover as R
import qmt_1m_opening_revalidate as O

FORMAT = "qmt_private_calibrated_month_1min_bridge_v1"
START = date(2026, 10, 14)
END = date(2026, 11, 12)
MONTHS = ("2026-10", "2026-11")
TARGET = "private_monthly_1min_v1"


def _json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing/redirected SHA-bound input: " + str(path))
    return json.loads(path.read_bytes())


def _safe_dir(path):
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Redirected private directory: " + str(path))
    return path


def _hex(value):
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value)


def _calibration(calib, code):
    group = calib["providers"].get(P.category(code))
    if not group or group.get("category") != P.category(code):
        raise ValueError("Missing purchased calibration category for " + code)
    offset = group.get("offset_ms")
    if (type(offset) is not int or offset not in
            [x * 60000 for x in P.OFFSET_MINUTES]):
        raise ValueError("Unsupported QMT calibrated minute offset " + code)
    factors = []
    for field in ("volume", "amount"):
        value = group.get(field, {}).get("factor")
        if (type(value) not in (float, int) or not math.isfinite(value)
                or value <= 0 or value not in P.FACTORS):
            raise ValueError("Uncertified QMT " + field + " factor " + code)
        factors.append(float(value))
    return {"offset_ms": offset, "volume_factor": factors[0],
            "amount_factor": factors[1]}


def _add_entry(entries, occupied, expected, code, days, kind, path, receipt_sha, file_sha):
    if not _hex(receipt_sha) or not _hex(file_sha):
        raise ValueError("Invalid input receipt/source SHA " + code)
    wanted = sorted(d.isoformat() for d, symbols in expected.items() if code in symbols)
    if not isinstance(days, list) or len(days) != len(set(days)) or days != sorted(days):
        raise ValueError("Nonunique/unsorted source days " + code)
    if not set(days) <= set(wanted):
        raise ValueError("Stock day absent from pinned official DAY universe " + code)
    for day in days:
        key = (day, code)
        if key in occupied:
            raise ValueError("Overlapping stock-day source ownership " + str(key))
        occupied[key] = kind
    if days:
        entries.append({"code": code, "days": days, "kind": kind,
                        "path": str(path), "receipt_sha256": receipt_sha,
                        "source_sha256": file_sha})


def load_sealed_context(stage, *, min_daily_stocks=2500):
    """Recover historical DAY stock-days from immutable receipts and pinned SHA.

    Physical DAY months can be legitimately updated after original QMT intake.
    This reconstructs the exact OLD stock-day calendar and checks its digest
    against the original plan, not a new mutable physical DAY snapshot.
    """
    stage = Path(stage)
    plan = _json(stage / "plan.json")
    sources = plan.get("day_file_sha256")
    if (plan.get("format") != P.FORMAT
            or plan.get("window") != [str(START), str(END)]
            or not isinstance(sources, dict)
            or set(sources) != {"physical", "tdx_overlay"}
            or any(not isinstance(sources[k], dict) for k in sources)
            or any(not _hex(v) for m in sources.values() for v in m.values())
            or not _hex(plan.get("calendar_sha256"))
            or not _hex(plan.get("calibration_sha256"))
            or type(plan.get("stock_count")) is not int
            or not isinstance(plan.get("trading_days"), list)):
        raise ValueError("Original stage DAY plan identity invalid")
    original_dir = stage / "receipts"
    recovery_dir = stage / "day_recovery" / "receipts"
    if (not original_dir.is_dir() or original_dir.is_symlink()
            or not recovery_dir.is_dir() or recovery_dir.is_symlink()):
        raise ValueError("Missing original/recovery receipt inventory")
    expected = defaultdict(dict)
    owners = set()
    for kind, folder in (("original", original_dir), ("recovery", recovery_dir)):
        for path in sorted(folder.glob("*.json")):
            doc = _json(path)
            code = doc.get("symbol")
            if (not isinstance(code, str)
                    or path.name != code.replace(".", "_") + ".json"
                    or P.normalize_code(code) != code or code in owners):
                raise ValueError("Duplicate or invalid original stock receipt")
            owners.add(code)
            if kind == "original":
                if (doc.get("status") != "private_ohlcva_source_verified"
                        or doc.get("market_modified") is not False):
                    raise ValueError("Original QMT stock status changed " + code)
                days = doc.get("traded_days")
            else:
                good, bad = doc.get("approved_days"), doc.get("quarantined_days")
                if (doc.get("format") != R.FORMAT
                        or doc.get("status") != "private_day_subset_only"
                        or doc.get("market_modified") is not False
                        or doc.get("production_merge_authorized") is not False
                        or not isinstance(good, list) or not isinstance(bad, dict)
                        or set(good) & set(bad)):
                    raise ValueError("Recovery stock receipt invalid " + code)
                days = good + list(bad)
            if (not isinstance(days, list) or not days
                    or len(days) != len(set(days))):
                raise ValueError("Invalid original traded-day list " + code)
            for iso in days:
                if not isinstance(iso, str):
                    raise ValueError("Invalid stock/day key type")
                day = date.fromisoformat(iso)
                if not START <= day <= END or iso != day.isoformat():
                    raise ValueError("Stock/day outside original stage " + code)
                if code in expected[day]:
                    raise ValueError("Duplicate original stock/day")
                expected[day][code] = None
    symbols = sorted(owners)
    if (len(symbols) != plan["stock_count"]
            or sorted(d.isoformat() for d in expected) != plan["trading_days"]
            or any(len(codes) < min_daily_stocks for codes in expected.values())):
        raise ValueError("Sealed DAY stock/date inventory changed")
    # This is the EXACT proof construction in P.official_day_universe,
    # but using the old, original source SHA values already in plan.json.
    proof = P.sha_bytes(P.canonical({
        "physical_month_sha256": sources["physical"],
        "used_tdx_day_overlay_sha256": sources["tdx_overlay"],
        "days": sorted((str(day), code)
                       for day, codes in expected.items() for code in codes)}))
    if proof != plan["calendar_sha256"]:
        raise ValueError("Reconstructed historical DAY calendar SHA mismatch")
    calib = _json(P.BASE / "calibration" / "latest.json")
    if (calib.get("calibration_passed") is not True
            or not isinstance(calib.get("providers"), dict)
            or len(calib["providers"]) != 3
            or P.sha_bytes(P.canonical(calib)) != plan["calibration_sha256"]):
        raise ValueError("Sealed paid-provider calibration changed")
    purchased = set()
    for item in calib["providers"].values():
        old = Path(item["paid_source_path"])
        if (old.is_symlink() or not old.is_file()
                or L.hash_file(old) != item.get("paid_source_sha256")):
            raise ValueError("Original purchased source SHA changed")
        purchased.add(item["symbol"])
    if purchased != set(P.ANCHORS):
        raise ValueError("Original purchased calibration anchors changed")
    return expected, symbols, plan, calib


def resolve(root, stage, progress=print):
    """Prove three disjoint sources against original calendar/calibration and recovery."""
    stage = Path(stage)
    if not stage.is_dir() or stage.is_symlink():
        raise ValueError("Original QMT private stage missing or redirected")
    expected, all_stocks, plan, calib = load_sealed_context(stage)
    progress("QMT_PRIVATE_MONTH_SOURCE_BINDING=SEALED_ORIGINAL_DAY_CALENDAR_SHA_VERIFIED")
    report = _json(stage / "day_recovery" / "latest_report.json")
    orig = R.validate_original(stage, expected, all_stocks, progress=progress)
    original_plan_sha = L.hash_file(stage / "plan.json")
    fp = P.sha_bytes(P.canonical({
        "original_plan_sha256": P.sha_bytes(P.canonical(plan)),
        "calibration_sha256": plan["calibration_sha256"], "format": R.FORMAT}))
    recovery_folder = stage / "day_recovery"
    opening_folder = stage / "opening_first_trade_v1"
    if (not opening_folder.is_dir() or opening_folder.is_symlink()
            or not (opening_folder / "receipts").is_dir()):
        raise ValueError("Completed new opening private receipts not found")
    entries, owned = [], {}
    original_count, recovered_count, opening_count = 0, 0, 0
    for code in all_stocks:
        all_days = sorted(d.isoformat() for d in expected if code in expected[d])
        if code in orig:
            doc = orig[code]
            src = stage / "source_parquet" / (code.replace(".", "_") + ".parquet")
            receipt = stage / "receipts" / (code.replace(".", "_") + ".json")
            _add_entry(entries, owned, expected, code, doc["traded_days"], "original",
                       src, L.hash_file(receipt), doc["sha256"])
            original_count += len(doc["traded_days"])
            bound = _calibration(calib, code)
            if (doc.get("paid_calibration_passed_for_category") is not True
                    or doc.get("calibrated_offset_ms") != bound["offset_ms"]
                    or doc.get("calibrated_volume_factor") != bound["volume_factor"]
                    or doc.get("calibrated_amount_factor") != bound["amount_factor"]):
                raise ValueError("Original QMT stock calibration receipt changed " + code)
            continue
        doc = R.validate_recovery_receipt(recovery_folder, code, fp, all_days)
        if doc is None:
            raise ValueError("Missing partial recovery receipt for " + code)
        rfile = recovery_folder / "receipts" / (code.replace(".", "_") + ".json")
        rsha = L.hash_file(rfile)
        approved = doc["approved_days"]
        if approved:
            src = recovery_folder / "source_parquet" / (code.replace(".", "_") + ".parquet")
            _add_entry(entries, owned, expected, code, approved, "recovery",
                       src, rsha, doc["sha256"])
            recovered_count += len(approved)
        errors = {d: ev for d, ev in doc["quarantined_days"].items()
                  if ev.get("reason") == O.ORIGINAL_REASON}
        opening_path = opening_folder / "receipts" / (code.replace(".", "_") + ".json")
        if errors:
            candidate = _json(opening_path)
            native_sha = candidate.get("source_native_dat_sha256")
            if not _hex(native_sha):
                raise ValueError("Missing proven source DAT digest " + code)
            proven = O._reuse(opening_folder, code,
                              {"source_recovery_receipt_sha256": rsha,
                               "source_stage_plan_sha256": original_plan_sha,
                               "source_native_dat_sha256": native_sha}, errors)
            if proven is None:
                raise ValueError("Missing new opening private source " + code)
            passed = proven["approved_days"]
            if (not isinstance(passed, dict)
                    or any(detail.get("reason") != "VERIFIED_FIRST_TRADED_OPEN"
                           or detail.get("original_0930_bar_preserved") is not True
                           for detail in passed.values())):
                raise ValueError("Opening acceptance detail invalid " + code)
            if passed:
                source = opening_folder / "source_parquet" / (code.replace(".", "_") + ".parquet")
                _add_entry(entries, owned, expected, code, sorted(passed), "opening",
                           source, L.hash_file(opening_path), proven["sha256"])
                opening_count += len(passed)
        elif opening_path.exists() or opening_path.is_symlink():
            raise ValueError("Unexpected opening receipt for stock without OHLC conflict")
    expected_keys = {(d.isoformat(), code) for d, codes in expected.items() for code in codes}
    if not set(owned).issubset(expected_keys):
        raise ValueError("Accepted source key not in official reference")
    gaps = sorted(expected_keys - set(owned))
    prior = original_count + recovered_count
    if (report.get("expected_stock_day_keys") != len(expected_keys)
            or report.get("accepted_stock_day_keys") != prior
            or report.get("remaining_stock_day_gaps") != len(expected_keys) - prior):
        raise ValueError("Old recovery full-market coverage report changed")
    if opening_count + len(gaps) != report["remaining_stock_day_gaps"]:
        raise ValueError("Opening source and remaining quarantine do not partition old gaps")
    for day, code in gaps:
        recovery = _json(recovery_folder / "receipts" / (code.replace(".", "_") + ".json"))
        if day not in recovery["quarantined_days"]:
            raise ValueError("Remaining source gap lacks old quarantine evidence")
    months = {}
    for mon in MONTHS:
        exp = sum(1 for day, _ in expected_keys if day.startswith(mon))
        valid = sum(1 for day, _ in owned if day.startswith(mon))
        months[mon] = {"stock_days_expected": exp, "stock_days_accepted": valid,
                       "stock_days_quarantined": exp - valid,
                       "minute_rows_expected_from_accepted": valid * 241,
                       "incomplete_window": True,
                       "window_limited_to": ["2026-10-14", "2026-10-30"]
                           if mon == "2026-10" else ["2026-11-02", "2026-11-12"]}
    records = sorted(entries, key=lambda x: (x["code"], x["kind"]))
    identity = {"format": FORMAT, "window": [str(START), str(END)],
                "original_plan_sha256": original_plan_sha,
                "calibration_sha256": plan["calibration_sha256"],
                "source_receipts": [
                    {"code": x["code"], "kind": x["kind"], "days": x["days"],
                     "receipt_sha256": x["receipt_sha256"],
                     "source_sha256": x["source_sha256"]} for x in records],
                "gaps": gaps}
    return {"entries": records, "expected": expected, "calib": calib,
            "identity_sha256": P.sha_bytes(P.canonical(identity)),
            "gaps": gaps, "months": months, "original": original_count,
            "recovered": recovered_count, "opening": opening_count,
            "total_expected": len(expected_keys), "plan": plan}


def _expected_timestamps(expected):
    return {d.isoformat(): [P.stamp_ms(s) for s in sorted(P.expected_minute_grid(d))]
            for d in expected}


def validate_source_table(table, entry, time_grid):
    """Verify the exact 241 original native minute labels of every receipt day."""
    if table.schema != P.PRIVATE_SCHEMA or table.num_rows != len(entry["days"]) * 241:
        raise ValueError("Original native source schema/row count changed " + entry["code"])
    observed = table["ts"].to_pylist()
    if observed != [ts for day in entry["days"] for ts in time_grid[day]]:
        raise ValueError("QMT native source minute grid/ordering changed " + entry["code"])
    if any(x != L.normal_symbol(entry["code"]) for x in table["symbol"].to_pylist()):
        raise ValueError("QMT native source security code mismatch " + entry["code"])


def calibrate_table(table, gate, year_month):
    """Return a calibrated private Arrow table; leave the native source unchanged."""
    offset = gate["offset_ms"]
    columns = []
    for field in P.PRIVATE_SCHEMA:
        array = table[field.name]
        if field.name == "ts" and offset:
            array = pc.add(array, pa.scalar(offset, pa.int64()))
        if field.name == "volume":
            array = pc.multiply(array, pa.scalar(gate["volume_factor"], pa.float64()))
        if field.name == "amount":
            array = pc.multiply(array, pa.scalar(gate["amount_factor"], pa.float64()))
        columns.append(array)
    out = pa.Table.from_arrays(columns, schema=P.PRIVATE_SCHEMA).combine_chunks()
    for ts in out["ts"].to_pylist():
        if L.market_ts_day(int(ts)).strftime("%Y-%m") != year_month:
            raise ValueError("Calibrated time offset moved minute into a different month")
    for name in ("volume", "amount"):
        vals = out[name].to_pylist()
        if any(not math.isfinite(v) or v < 0 for v in vals):
            raise ValueError("Invalid calibrated " + name)
    return out


def _arrow_digest(table):
    """Hash logical values, not Arrow IPC buffers/chunk framing.

    Parquet roundtrips can change Arrow buffer or batch layout while
    preserving every ts/symbol/OHLCVA value. JSON canonicalisation matches
    our existing SHA receipt convention and is deterministic across batches.
    Each call covers one bounded stock/month row group, not an entire market.
    """
    if table.schema != P.PRIVATE_SCHEMA:
        raise ValueError("Private monthly Arrow digest schema changed")
    return hashlib.sha256(P.canonical(table.to_pylist())).hexdigest()


def verify_private_month(path, manifest, identity):
    if (manifest.get("format") != FORMAT
            or manifest.get("identity_sha256") != identity
            or manifest.get("status") != "PRIVATE_MONTH_ONLY"
            or manifest.get("market_modified") is not False
            or manifest.get("production_merge_authorized") is not False
            or not isinstance(manifest.get("groups"), list)
            or not _hex(manifest.get("sha256"))):
        raise ValueError("Private monthly manifest identity or safety guard changed")
    if path.is_symlink() or not path.is_file() or L.hash_file(path) != manifest["sha256"]:
        raise ValueError("Private monthly Parquet SHA mismatch")
    reader = pq.ParquetFile(path)
    try:
        if (reader.schema_arrow != P.PRIVATE_SCHEMA
                or reader.metadata.num_rows != manifest["rows"]
                or reader.num_row_groups != len(manifest["groups"])):
            raise ValueError("Private monthly schema/count/rowgroups changed")
        total = 0
        for i, desc in enumerate(manifest["groups"]):
            chunk = reader.read_row_group(i)
            if (chunk.num_rows != desc["rows"]
                    or _arrow_digest(chunk) != desc["arrow_sha256"]):
                raise ValueError("Private monthly full Arrow readback mismatch at group " + str(i))
            total += chunk.num_rows
        if total != manifest["rows"]:
            raise ValueError("Private monthly rowgroup total mismatch")
    finally:
        reader.close()


def _output_allowed(stage, output):
    work = (Path(__file__).resolve().parent / "work").resolve()
    target = Path(output).resolve()
    if (target != Path(stage).resolve() / TARGET
            or not target.is_relative_to(work)
            or Path(output).is_symlink()
            or Path(output).parent.is_symlink()):
        raise ValueError("Private month writing outside fixed stage/work directory is forbidden")


def build(root=Path("D:/stock"), stage=P.BASE / "20261014_20261112",
          *, write_private=False, progress=print):
    plan = resolve(root, stage, progress=progress)
    summary = {"format": FORMAT, "window": [str(START), str(END)],
               "expected_stock_days": plan["total_expected"],
               "original_accepted_stock_days": plan["original"],
               "recovery_accepted_stock_days": plan["recovered"],
               "opening_accepted_stock_days": plan["opening"],
               "total_accepted_stock_days":
                   plan["original"] + plan["recovered"] + plan["opening"],
               "remaining_quarantined_stock_days": len(plan["gaps"]),
               "remaining_quarantined_keys": [
                   {"day": day, "symbol": code} for day, code in plan["gaps"]],
               "month_coverage": plan["months"],
               "source_entries": len(plan["entries"]),
               "source_identity_sha256": plan["identity_sha256"],
               "private_written": bool(write_private), "market_modified": False,
               "production_merge_authorized": False}
    if not write_private:
        progress("QMT_PRIVATE_MONTH_PREFLIGHT=" + json.dumps(summary, sort_keys=True))
        return summary
    stage = Path(stage)
    output = stage / TARGET
    _output_allowed(stage, output)
    _safe_dir(output)
    output.mkdir(parents=True, exist_ok=True)
    existing, new = {}, {}
    for mon in MONTHS:
        path = output / (mon + ".parquet")
        receipt = output / (mon + ".receipt.json")
        if path.is_symlink() or receipt.is_symlink():
            raise ValueError("Linked private month output")
        if path.exists() != receipt.exists():
            raise ValueError("Interrupted private month output/receipt pair: " + mon)
        if path.exists():
            doc = _json(receipt)
            if (doc.get("month_coverage") != plan["months"][mon]
                    or doc.get("calibration_sha256") != plan["plan"]["calibration_sha256"]):
                raise ValueError("Private month receipt stale versus bound source context")
            verify_private_month(path, doc, plan["identity_sha256"])
            existing[mon] = doc
            progress("QMT_PRIVATE_MONTH_REUSED=" + mon)
        else:
            new[mon] = {"path": path, "receipt": receipt}
    if not new:
        progress("QMT_PRIVATE_MONTH_RESULT=" + json.dumps(
            {**summary, "months_reused": len(existing), "months_created": 0}, sort_keys=True))
        return summary
    timestamps = _expected_timestamps(plan["expected"])
    writers, groups, count = {}, {m: [] for m in new}, Counter()
    scratch = {}
    try:
        for mon, dest in new.items():
            tmp = dest["path"].with_suffix(".parquet.part")
            if tmp.exists() or tmp.is_symlink():
                raise ValueError("Stale private month scratch file: " + str(tmp))
            scratch[mon] = tmp
            writers[mon] = pq.ParquetWriter(tmp, P.PRIVATE_SCHEMA, compression="zstd")
        for i, entry in enumerate(plan["entries"], 1):
            active_months = sorted({day[:7] for day in entry["days"] if day[:7] in new})
            if not active_months:
                continue
            source = Path(entry["path"])
            if (source.is_symlink() or not source.is_file()
                    or L.hash_file(source) != entry["source_sha256"]):
                raise ValueError("SHA-verified input source changed: " + entry["code"])
            source_table = pq.read_table(source)
            if L.hash_file(source) != entry["source_sha256"]:
                raise ValueError("QMT input changed during private monthly read: " + entry["code"])
            validate_source_table(source_table, entry, timestamps)
            gate = _calibration(plan["calib"], entry["code"])
            bymonth = defaultdict(list)
            for n, day in enumerate(entry["days"]):
                if day[:7] in new:
                    bymonth[day[:7]].append(source_table.slice(n * 241, 241))
            for mon, chunks in sorted(bymonth.items()):
                incoming = pa.concat_tables(chunks).combine_chunks()
                converted = calibrate_table(incoming, gate, mon)
                writers[mon].write_table(converted, row_group_size=converted.num_rows)
                groups[mon].append({"symbol": L.normal_symbol(entry["code"]),
                                     "source_kind": entry["kind"],
                                     "source_receipt_sha256": entry["receipt_sha256"],
                                     "rows": converted.num_rows,
                                     "arrow_sha256": _arrow_digest(converted)})
                count[mon] += converted.num_rows
            if i % 500 == 0:
                progress("QMT_PRIVATE_MONTH_SOURCE_PROGRESS=" + str(i) + "/" + str(len(plan["entries"])))
        for mon in writers:
            writers[mon].close()
        writers.clear()
        for mon in new:
            if count[mon] != plan["months"][mon]["minute_rows_expected_from_accepted"]:
                raise ValueError("Private month complete source row total mismatch " + mon)
            tmp = scratch[mon]
            provisional = {"format": FORMAT, "status": "PRIVATE_MONTH_ONLY",
                           "month": mon, "identity_sha256": plan["identity_sha256"],
                           "calibration_sha256": plan["plan"]["calibration_sha256"],
                           "rows": count[mon], "groups": groups[mon],
                           "month_coverage": plan["months"][mon],
                           "remaining_quarantined_keys": [
                               {"day": day, "symbol": code} for day, code in plan["gaps"]
                               if day.startswith(mon)],
                           "sha256": L.hash_file(tmp),
                           "market_modified": False, "production_merge_authorized": False,
                           "not_a_full_month_where_window_is_partial": True}
            verify_private_month(tmp, provisional, plan["identity_sha256"])
            # The manifest is written last. If the process crashes after replace,
            # an orphan is deliberately refused rather than overwritten.
            R.retry_private_atomic(tmp, new[mon]["path"])
            P.safe_save(new[mon]["receipt"], P.canonical(provisional))
            progress("QMT_PRIVATE_MONTH_CREATED=" + json.dumps(
                {"month": mon, "rows": count[mon], "sha256": provisional["sha256"],
                 "stock_day_gaps": plan["months"][mon]["stock_days_quarantined"]},
                sort_keys=True))
    finally:
        for writer in writers.values():
            writer.close()
        for tmp in scratch.values():
            if tmp.exists() and not tmp.is_symlink():
                tmp.unlink()
    progress("QMT_PRIVATE_MONTH_RESULT=" + json.dumps(
        {**summary, "months_reused": len(existing), "months_created": len(new)},
        sort_keys=True))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--write-private", action="store_true")
    args = parser.parse_args(argv)
    build(args.root, write_private=args.write_private)


if __name__ == "__main__":
    main()
