#!/usr/bin/env python3
"""Revalidate QMT 1m quarantined opening days from local DAT; private output only.

Never downloads, changes QMT DAT, rewrites earlier receipts, or writes to the
physical AllCycleAStockData / H5. The 241 native bars remain unchanged.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

import local_layout as L
import qmt_1m_pipeline as P
import qmt_1m_recover as R
import qmt_local_dat_241_native_readonly as M

FORMAT = "qmt_1m_first_traded_minute_opening_private_v1"
POLICY = "first_positive_volume_amount_after_zero_prefix;native_241_unchanged"
ORIGINAL_REASON = "QMT_OFFICIAL_DAY_OHLC_MISMATCH"
STAGE = P.BASE / "20261014_20261112"
FIELDS = ("open", "high", "low", "close")
STRICT_PRICE = 0.0002


def _check_dir(folder):
    folder = Path(folder)
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("Private/source directory missing or redirected: " + str(folder))
    return folder


def _digest(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or redirected SHA-bound input: " + str(path))
    return L.hash_file(path)


def _close(actual, expected, *, strict=False):
    return math.isclose(float(actual), float(expected),
                        rel_tol=0 if strict else .006,
                        abs_tol=STRICT_PRICE if strict else .04)


def assess_day(rows, day, evidence):
    """Pure admission decision; never edits QMT bars or relaxes DAY tolerance."""
    fail = lambda why: (False, {"reason": why})
    if evidence.get("reason") != ORIGINAL_REASON or not isinstance(evidence.get("qmt"), dict):
        return fail("NOT_AN_ORIGINAL_OPENING_QUARANTINE")
    if len(rows) != 241:
        return fail("NOT_241_NATIVE_BARS")
    ticks = [datetime.fromtimestamp(int(r["ts"]) / 1000, M.CN) for r in rows]
    if (any(t.date().isoformat() != day or t.second or t.microsecond for t in ticks)
            or [(t.hour, t.minute) for t in ticks] != sorted(P.GRID)):
        return fail("NATIVE_GRID_MISMATCH")
    for r in rows:
        vals = [float(r[k]) for k in (*FIELDS, "volume", "amount")]
        if (not all(math.isfinite(x) for x in vals)
                or any(float(r[k]) <= 0 for k in FIELDS)
                or float(r["volume"]) < 0 or float(r["amount"]) < 0
                or float(r["low"]) > min(float(r["open"]), float(r["close"]))
                or float(r["high"]) < max(float(r["open"]), float(r["close"]))):
            return fail("INVALID_NATIVE_OHLCVA")
    aggregate = {"open": rows[0]["open"], "high": max(r["high"] for r in rows),
                 "low": min(r["low"] for r in rows), "close": rows[-1]["close"]}
    if any(not _close(aggregate[k], evidence["qmt"][k], strict=True) for k in FIELDS):
        return fail("SAVED_NATIVE_SNAPSHOT_DISAGREES")
    totals = evidence.get("native_totals", {})
    for k in ("volume", "amount"):
        if k not in totals:
            return fail("MISSING_ORIGINAL_VOLUME_AMOUNT_EVIDENCE")
        observed = sum(float(r[k]) for r in rows)
        saved = float(totals[k])
        if not math.isclose(observed, saved, rel_tol=1e-8, abs_tol=.0002):
            return fail("SAVED_NATIVE_" + k.upper() + "_DISAGREES")
    if rows[0]["volume"] != 0 or rows[0]["amount"] != 0:
        return fail("0930_HAS_TRADES")
    # A nonzero volume with zero amount (or the reverse) is not a valid trade.
    for r in rows:
        if (float(r["volume"]) > 0) != (float(r["amount"]) > 0):
            return fail("AMBIGUOUS_VOLUME_AMOUNT_PAIR")
    traded = [(i, r) for i, r in enumerate(rows) if r["volume"] > 0]
    if not traded or traded[0][0] == 0:
        return fail("NO_VERIFIED_FIRST_REGULAR_TRADE")
    first_index, first = traded[0]
    if any(r["volume"] != 0 or r["amount"] != 0 for r in rows[:first_index]):
        return fail("NONZERO_PREFIX_BEFORE_FIRST_TRADE")
    ref = evidence.get("day_reference", {})
    if any(k not in ref for k in FIELDS):
        return fail("MISSING_OFFICIAL_DAY_REFERENCE")
    if not _close(first["open"], ref["open"], strict=True):
        return fail("FIRST_TRADED_OPEN_NOT_STRICT")
    active = [r for _, r in traded]
    derived = {"open": first["open"], "high": max(r["high"] for r in active),
               "low": min(r["low"] for r in active),
               "close": active[-1]["close"]}
    if any(not _close(derived[k], ref[k]) for k in ("high", "low", "close")):
        return fail("TRADED_MINUTES_HLC_MISMATCH")
    # A cross-check of the entire post-prefix time sequence, including zero-volume
    # native bars: it is intentionally stronger than the five-case exploratory probe.
    tail = rows[first_index:]
    tail_check = {"high": max(r["high"] for r in tail),
                  "low": min(r["low"] for r in tail),
                  "close": rows[-1]["close"]}
    if any(not _close(tail_check[k], ref[k]) for k in tail_check):
        return fail("POST_PREFIX_HLC_MISMATCH")
    return True, {"reason": "VERIFIED_FIRST_TRADED_OPEN",
                  "first_traded_label": ticks[first_index].strftime("%H:%M"),
                  "zero_prefix_bars": first_index, "native_bars": 241,
                  "original_0930_bar_preserved": True,
                  "official_open_strict": True,
                  "official_traded_hlc_with_original_tolerance": True}


def candidates(stage):
    """All 184 immutable recovery receipts; only their explicit OHLC failures."""
    folder = _check_dir(Path(stage) / "day_recovery" / "receipts")
    stage_sha = _digest(Path(stage) / "plan.json")
    records = {}
    all_reasons = Counter()
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_bytes())
        code = data.get("symbol")
        if (data.get("format") != R.FORMAT
                or data.get("status") != "private_day_subset_only"
                or data.get("market_modified") is not False
                or data.get("production_merge_authorized") is not False
                or not isinstance(code, str)
                or path.name != code.replace(".", "_") + ".json"
                or code in records):
            raise ValueError("Recovery receipt identity changed: " + path.name)
        approved = data.get("approved_days")
        bad = data.get("quarantined_days")
        if (not isinstance(approved, list) or not isinstance(bad, dict)
                or set(approved) & set(bad)
                or data.get("rows") != len(approved) * 241):
            raise ValueError("Recovery receipt stock/day coverage changed: " + code)
        if approved:
            original = Path(stage) / "day_recovery" / "source_parquet" / (code.replace(".", "_") + ".parquet")
            if _digest(original) != data.get("sha256"):
                raise ValueError("Accepted recovery source Parquet SHA changed: " + code)
        elif data.get("sha256") is not None:
            raise ValueError("Empty recovery source has unexpected SHA")
        for value in bad.values():
            all_reasons[value.get("reason", "UNKNOWN").split(":")[0]] += 1
        selected = {day: ev for day, ev in bad.items()
                    if ev.get("reason") == ORIGINAL_REASON}
        if selected:
            records[code] = {"path": path, "receipt_sha256": _digest(path),
                             "days": selected}
    expected = sum(len(r["days"]) for r in records.values())
    report_path = Path(stage) / "day_recovery" / "latest_report.json"
    report = json.loads(report_path.read_bytes())
    if (report.get("remaining_stock_day_gaps") != sum(all_reasons.values())
            or report.get("quarantined_reason_counts", {}).get(ORIGINAL_REASON) != expected):
        raise ValueError("Recovery summary no longer matches quarantine receipts")
    return records, stage_sha, all_reasons


def _source_table(code, accepted):
    flat = []
    for day in sorted(accepted):
        for bar in accepted[day]:
            flat.append({"ts": int(bar["ts"]), "symbol": L.normal_symbol(code),
                         **{k: float(bar[k]) for k in M.FIELDS}})
    return pa.Table.from_pylist(flat, schema=P.PRIVATE_SCHEMA)


def _save_stock(folder, code, source, approved, refused, provenance):
    """New private-only source and receipt. Existing orphans must match exactly."""
    folder = Path(folder)
    if folder.is_symlink() or folder.parent.is_symlink():
        raise ValueError("Redirected private output")
    receipt_path = folder / "receipts" / (code.replace(".", "_") + ".json")
    source_path = folder / "source_parquet" / (code.replace(".", "_") + ".parquet")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ValueError("Immutable opening receipt already exists: " + code)
    source_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    table = _source_table(code, source)
    if table.num_rows != len(approved) * 241:
        raise ValueError("Opening source rows not equal to approved stock/day keys")
    if table.num_rows:
        L.checked_records(table)
        if source_path.is_symlink():
            raise ValueError("Linked opening source file")
        if source_path.exists():
            saved = pq.read_table(source_path)
            if not saved.equals(table, check_metadata=False):
                raise ValueError("Interrupted opening source differs; refuse overwrite")
        else:
            scratch = source_path.with_suffix(".parquet.part")
            if scratch.is_symlink() or scratch.exists():
                raise ValueError("Opening private temp file already exists")
            pq.write_table(table, scratch, compression="zstd", row_group_size=8192)
            try:
                checked = pq.read_table(scratch)
                if not checked.equals(table, check_metadata=False):
                    raise ValueError("Opening source Arrow roundtrip mismatch")
            except BaseException:
                scratch.unlink(missing_ok=True)
                raise
            R.retry_private_atomic(scratch, source_path)
        digest = _digest(source_path)
    else:
        if source_path.exists() or source_path.is_symlink():
            raise ValueError("Empty opening source unexpectedly has Parquet")
        digest = None
    record = {"format": FORMAT, "status": "private_source_reviewed_not_production",
              "symbol": code, "approved_days": approved,
              "quarantined_days": refused, "rows": table.num_rows,
              "sha256": digest, "source_unit": "QMT_NATIVE_NOT_CONVERTED",
              "policy": POLICY, **provenance, "market_modified": False,
              "production_merge_authorized": False}
    P.safe_save(receipt_path, P.canonical(record))
    return record


def _reuse(folder, code, provenance, days):
    receipt = Path(folder) / "receipts" / (code.replace(".", "_") + ".json")
    if not receipt.exists() and not receipt.is_symlink():
        return None
    if receipt.is_symlink():
        raise ValueError("Symlink opening acceptance receipt")
    data = json.loads(receipt.read_bytes())
    if (data.get("format") != FORMAT or data.get("policy") != POLICY
            or data.get("status") != "private_source_reviewed_not_production"
            or data.get("market_modified") is not False
            or data.get("production_merge_authorized") is not False
            or any(data.get(k) != v for k, v in provenance.items())
            or set(data.get("approved_days", [])) | set(data.get("quarantined_days", {})) != set(days)
            or set(data.get("approved_days", [])) & set(data.get("quarantined_days", {}))
            or data.get("rows") != len(data.get("approved_days", [])) * 241):
        raise ValueError("Immutable opening receipt identity mismatch: " + code)
    source = Path(folder) / "source_parquet" / (code.replace(".", "_") + ".parquet")
    if data["approved_days"]:
        if _digest(source) != data.get("sha256"):
            raise ValueError("Immutable opening source SHA mismatch: " + code)
        f = pq.ParquetFile(source)
        try:
            if f.metadata.num_rows != data["rows"] or f.schema_arrow != P.PRIVATE_SCHEMA:
                raise ValueError("Immutable opening source Parquet schema mismatch: " + code)
        finally:
            f.close()
    elif data.get("sha256") is not None or source.exists():
        raise ValueError("Unexpected empty opening source")
    return data


def run(stage=STAGE, datadir=Path("D:/software/JHQMT/datadir"),
        *, limit=0, write_private=False, native_reader=M.read_xtdata, progress=print):
    stage = _check_dir(stage)
    datadir = _check_dir(datadir)
    found, plan_sha, reasons = candidates(stage)
    output = stage / "opening_first_trade_v1"
    if write_private:
        # User-selected action can only create SHA-bound private files under this work tree.
        work = (Path(__file__).resolve().parent / "work").resolve()
        if not output.resolve().is_relative_to(work):
            raise ValueError("Opening private writes forbidden outside work/")
    if limit < 0:
        raise ValueError("Negative stock limit")
    total_cases = sum(len(r["days"]) for r in found.values())
    counts = Counter()
    read_stocks = 0
    reused_stocks = 0
    accepted = 0
    rejected = 0
    for code, item in sorted(found.items())[:limit or None]:
        provenance = {"source_recovery_receipt_sha256": item["receipt_sha256"],
                      "source_stage_plan_sha256": plan_sha}
        if write_private:
            old = _reuse(output, code, provenance, item["days"])
            if old is not None:
                accepted += len(old["approved_days"])
                rejected += len(old["quarantined_days"])
                counts.update(v["reason"] for v in old["quarantined_days"].values())
                reused_stocks += 1
                continue
        number, market = code.split(".")
        if market not in ("SH", "SZ") or not number.isdigit() or len(number) != 6:
            raise ValueError("Unrecognized recovery symbol")
        dat = datadir / market / "60" / (number + ".DAT")
        original = M.fingerprint(dat)
        bars, shape, error = native_reader(code, datadir)
        if M.fingerprint(dat) != original:
            raise ValueError("QMT source DAT mutated during read: " + code)
        if error:
            raise ValueError("QMT native local read failed " + code + ": " + str(error))
        read_stocks += 1
        grouped = defaultdict(list)
        for bar in bars:
            day = datetime.fromtimestamp(bar["ts"] / 1000, M.CN).date().isoformat()
            grouped[day].append(bar)
        passed, failed, source = {}, {}, {}
        for day, ev in sorted(item["days"].items()):
            ok, detail = assess_day(grouped.get(day, []), day, ev)
            if ok:
                passed[day] = detail
                source[day] = grouped[day]
                accepted += 1
            else:
                failed[day] = detail
                rejected += 1
                counts[detail["reason"]] += 1
        if write_private:
            _save_stock(output, code, source, passed, failed,
                        {**provenance, "source_native_dat_sha256": original["sha256"]})
        if read_stocks % 25 == 0:
            progress("QMT_OPENING_PROGRESS stocks=" + str(read_stocks)
                     + " admitted_days=" + str(accepted))
    result = {"format": FORMAT, "expected_candidates": total_cases,
              "checked_candidates": accepted + rejected,
              "newly_passed_stock_days": accepted, "still_quarantined": rejected,
              "candidate_stocks": len(found), "read_stocks": read_stocks,
              "reused_stocks": reused_stocks, "rejection_reasons": dict(counts),
              "prior_other_quarantine": dict(reasons),
              "private_written": bool(write_private), "market_modified": False,
              "production_merge_authorized": False}
    progress("QMT_OPENING_REVALIDATION=" + json.dumps(result, sort_keys=True))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, default=STAGE)
    parser.add_argument("--datadir", type=Path, default=Path("D:/software/JHQMT/datadir"))
    parser.add_argument("--limit-stocks", type=int, default=0)
    parser.add_argument("--write-private", action="store_true")
    args = parser.parse_args(argv)
    run(args.stage, args.datadir, limit=args.limit_stocks, write_private=args.write_private)


if __name__ == "__main__":
    main()
