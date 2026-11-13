#!/usr/bin/env python3
"""Recover quarantined QMT 1m stocks at trading-day granularity, without market writes.

Consumes an existing SHA-bound 2026-10-14..11-12 private stage.
Verifies ALL accepted source receipts and source files. Only downloads
stocks absent from that full-stock stage. If a stock has isolated bad days,
preserves its independently verified good days in a NEW private Parquet.
Never edits the original 5039 receipts, physical market Parquet, or H5.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import time

import pyarrow as pa
import pyarrow.parquet as pq

import local_layout as L
import qmt_1m_pipeline as P
import qmt_1m_probe as Q


FORMAT = "qmt_1m_day_level_quarantine_recovery_v1"
START = date(2026, 10, 14)
END = date(2026, 11, 12)


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def validate_original(stage, expected, stock_list, *, progress=print):
    """Fail closed if ANY original complete-stock receipt/parquet was altered."""
    stock_set = set(stock_list)
    records = {}
    folder = stage / "receipts"
    paths = sorted(folder.glob("*.json")) if folder.is_dir() else []
    for i, p in enumerate(paths):
        if p.is_symlink():
            raise ValueError("Symlinked source receipt refused: " + str(p))
        item = json.loads(p.read_bytes())
        code = item.get("symbol")
        if code not in stock_set or code in records or item.get("status") != "private_ohlcva_source_verified":
            raise ValueError("Unexpected or duplicate original accepted receipt: " + str(p))
        if p.name != code.replace(".", "_") + ".json":
            raise ValueError("Original receipt filename/code mismatch")
        original = stage / "source_parquet" / (code.replace(".", "_") + ".parquet")
        if original.is_symlink() or not original.is_file():
            raise ValueError("Missing original SHA-pinned source Parquet: " + code)
        if L.hash_file(original) != item.get("sha256"):
            raise ValueError("Original accepted source SHA mismatch: " + code)
        wanted = sorted(d.isoformat() for d, symbols in expected.items() if code in symbols)
        if item.get("traded_days") != wanted or item.get("rows") != len(wanted) * 241:
            raise ValueError("Original source traded-day/row-count mismatch: " + code)
        reader = pq.ParquetFile(original)
        try:
            if reader.metadata.num_rows != item["rows"]:
                raise ValueError("Original source Parquet footer row mismatch: " + code)
            if reader.schema_arrow != P.PRIVATE_SCHEMA:
                raise ValueError("Original source schema mismatch: " + code)
        finally:
            reader.close()
        records[code] = item
        if (i+1) % 1000 == 0:
            progress(f"QMT_RECOVERY_EXISTING_SHA_CHECKED={i+1}")
    return records


def load_bound_context(root, stage, start, end):
    planpath = stage / "plan.json"
    if planpath.is_symlink() or not planpath.is_file():
        raise ValueError("No immutable original QMT stage plan")
    plan = json.loads(planpath.read_bytes())
    if plan.get("format") != P.FORMAT or plan.get("window") != [str(start), str(end)]:
        raise ValueError("Original QMT stage window or format changed")
    expected, symbols, calendar_sha, source_files = P.official_day_universe(root, start, end)
    if (plan.get("calendar_sha256") != calendar_sha
            or plan.get("day_file_sha256") != source_files
            or plan.get("stock_count") != len(symbols)
            or plan.get("trading_days") != sorted(str(d) for d in expected)):
        raise ValueError("Original source DAY calendar/SHA changed: refuse mixing versions")
    calibpath = P.BASE / "calibration" / "latest.json"
    if calibpath.is_symlink() or not calibpath.is_file():
        raise ValueError("Missing independent paid-source calibration")
    calib = json.loads(calibpath.read_bytes())
    if not calib.get("calibration_passed") or len(calib.get("providers", {})) != 3:
        raise ValueError("Three-category paid 1m overlap was not certified")
    if plan.get("calibration_sha256") != P.sha_bytes(P.canonical(calib)):
        raise ValueError("Calibration changed since original stage plan")
    # The original purchased physical month is an independent immutable pin.
    seen = set()
    for proof in calib["providers"].values():
        path = Path(proof["paid_source_path"])
        if path.is_symlink() or not path.is_file() or L.hash_file(path) != proof["paid_source_sha256"]:
            raise ValueError("Original 2026-09 purchased source changed")
        seen.add(proof["symbol"])
    if seen != set(P.ANCHORS):
        raise ValueError("Paid calibration samples do not match reference anchors")
    return expected, symbols, plan, calib


def fetch_raw_by_day(xtdata, code, start, end):
    xtdata.download_history_data(code, period="1m",
        start_time=start.strftime("%Y%m%d"), end_time=end.strftime("%Y%m%d"))
    response = xtdata.get_market_data_ex(
        field_list=list(Q.FIELDS), stock_list=[code], period="1m",
        start_time=start.strftime("%Y%m%d"), end_time=end.strftime("%Y%m%d"),
        count=-1, dividend_type="none", fill_data=False)
    if not isinstance(response, dict) or code not in response:
        raise ValueError("QMT did not return requested 1m source: "+code)
    frame = response[code]
    if frame is None or not hasattr(frame, "iterrows"):
        raise ValueError("QMT did not return a DataFrame")
    if not set(Q.FIELDS).issubset(set(frame.columns)):
        raise ValueError("QMT raw source lacks OHLCVA")
    grouped = defaultdict(list)
    for index, row in frame.iterrows():
        ts = Q.parse_time(row["time"] if "time" in frame.columns else index)
        if not start <= ts.date() <= end:
            raise ValueError("QMT raw minute outside requested historical window")
        grouped[ts.date()].append({"time": ts, **{k: row[k] for k in Q.FIELDS}})
    if not grouped:
        raise ValueError("QMT_ZERO_HISTORICAL_ROWS_RETRYABLE")
    return grouped


class DayFrame:
    columns = (*Q.FIELDS, "time")
    def __init__(self, rows):
        self.rows = rows

    def iterrows(self):
        yield from enumerate(self.rows)


def check_day(code, day, entries, day_ref):
    """Accept ONLY independently valid 241-grid + matched DAY OHLC."""
    rows = Q.normalize_frame(DayFrame(entries), code, day, day)
    P.validate_full_days(rows, [day], code)
    actual = {"open": rows[0]["open"],
              "high": max(x["high"] for x in rows),
              "low": min(x["low"] for x in rows),
              "close": rows[-1]["close"]}
    reference = {field: float(day_ref[field]) for field in actual}
    matches = {field: math.isclose(actual[field], reference[field],
                  rel_tol=.006, abs_tol=.04) for field in actual}
    # Visible numeric evidence, not just an opaque OHLC_MISMATCH marker.
    detail = {"day": day.isoformat(),
              "qmt": {k:round(v,6) for k,v in actual.items()},
              "day_reference": {k:round(v,6) for k,v in reference.items()},
              "match": matches,
              "qmt_sha256": P.sha_bytes(P.canonical(rows)),
              "rows": len(rows)}
    # Native QMT totals and unconverted official DAY ratios are evidence only;
    # the purchased 1m calibration must be used before any actual physical merge.
    detail["native_totals"] = {
        k: round(sum(float(r[k]) for r in rows), 4) for k in ("volume", "amount")
    }
    detail["day_reference_ratios"] = {
        k: (round(float(day_ref[k]) / detail["native_totals"][k], 8)
            if k in day_ref and detail["native_totals"][k] > 0 else None)
        for k in ("volume", "amount")
    }
    if not all(matches.values()):
        return None, {"reason": "QMT_OFFICIAL_DAY_OHLC_MISMATCH", **detail}
    return rows, detail


def retry_private_atomic(src, dst, *, tries=6, sleeper=time.sleep):
    """Atomic Windows private Parquet replace with bounded transient lock retry."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries-1:
                raise
            sleeper(min(2, .20 * (2**i)))


def save_partial(root, code, approved_rows, approved_days, bad_days, fingerprint):
    """Source-native QMT units, separate from original full-stock accepted stage."""
    root = Path(root)
    target = root / "source_parquet" / (code.replace(".", "_") + ".parquet")
    receipt = root / "receipts" / (code.replace(".", "_") + ".json")
    if receipt.exists() or receipt.is_symlink() or target.exists() or target.is_symlink():
        raise ValueError("Recovery output already exists; refuse to overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"ts": P.stamp_ms(bar["datetime_cn"]), "symbol":L.normal_symbol(code),
         **{k:float(bar[k]) for k in Q.FIELDS}}
        for bar in approved_rows
    ]
    rows.sort(key=lambda x:x["ts"])
    table = pa.Table.from_pylist(rows, schema=P.PRIVATE_SCHEMA)
    if len(rows) != 241 * len(approved_days):
        raise ValueError("Recovered minute count does not match accepted day count")
    if len({r["ts"] for r in rows}) != len(rows):
        raise ValueError("Duplicate recovered timestamp")
    # A stock with no valid days still gets a receipt, but no Parquet artifact.
    digest = None
    if rows:
        temp = target.with_suffix(".parquet.part")
        if temp.is_symlink():
            raise ValueError("Unsafe recovery temp file")
        pq.write_table(table, temp, compression="zstd", row_group_size=8192)
        readback = pq.read_table(temp)
        if not readback.equals(table, check_metadata=False):
            raise ValueError("Recovered Parquet Arrow read-back mismatch")
        del readback
        retry_private_atomic(temp, target)
        digest = L.hash_file(target)
    result = {"format":FORMAT, "status":"private_day_subset_only",
              "symbol":code, "approved_days":sorted(approved_days),
              "quarantined_days":bad_days, "rows":len(rows),
              "sha256":digest, "fingerprint":fingerprint,
              "source_unit":"QMT_NATIVE_NOT_CONVERTED",
              "market_modified":False,
              "production_merge_authorized":False}
    P.safe_save(receipt, P.canonical(result))
    return result


def validate_recovery_receipt(root, code, fingerprint, expected_days):
    receipt = root / "receipts" / (code.replace(".", "_") + ".json")
    if not receipt.exists():
        return None
    if receipt.is_symlink():
        raise ValueError("Recovery receipt symlink refused")
    doc = json.loads(receipt.read_bytes())
    if (doc.get("format") != FORMAT or doc.get("symbol") != code
        or doc.get("fingerprint") != fingerprint
        or doc.get("status") != "private_day_subset_only"
        or doc.get("market_modified") is not False
        or doc.get("production_merge_authorized") is not False):
        raise ValueError("Recovery receipt identity/guard changed: "+code)
    good = doc.get("approved_days")
    bad = doc.get("quarantined_days")
    if not isinstance(good, list) or not isinstance(bad, dict):
        raise ValueError("Recovery receipt missing day map")
    if (set(good) & set(bad) or set(good) | set(bad) != set(expected_days)
            or len(good) != len(set(good)) or doc.get("rows") != len(good)*241):
        raise ValueError("Recovery receipt coverage mismatch: "+code)
    target = root / "source_parquet" / (code.replace(".", "_") + ".parquet")
    if good:
        if target.is_symlink() or not target.is_file() or L.hash_file(target) != doc.get("sha256"):
            raise ValueError("Recovery private Parquet SHA invalid: "+code)
        f = pq.ParquetFile(target)
        try:
            if f.metadata.num_rows != doc["rows"] or f.schema_arrow != P.PRIVATE_SCHEMA:
                raise ValueError("Recovery private Parquet schema/count invalid: "+code)
        finally:
            f.close()
    elif doc.get("sha256") is not None or target.exists():
        raise ValueError("Zero-day recovery unexpectedly has a source file")
    return doc


def run(root, *, start=START, end=END, limit=0, xtdata=None, progress=print):
    root=Path(root)
    stage=P.BASE / f"{start:%Y%m%d}_{end:%Y%m%d}"
    if not stage.is_dir() or stage.is_symlink():
        raise ValueError("Original full-market QMT private stage not found")
    expected, all_stocks, plan, calib=load_bound_context(root,stage,start,end)
    progress("QMT_RECOVERY_STEP_1_VERIFY_EXISTING_5039_SHA")
    original=validate_original(stage,expected,all_stocks,progress=progress)
    missing=[x for x in all_stocks if x not in original]
    recovery=stage/"day_recovery"
    recovery.mkdir(parents=True, exist_ok=True)
    if recovery.is_symlink():
        raise ValueError("Symlinked recovery workspace")
    fingerprint=P.sha_bytes(P.canonical({
        "original_plan_sha256":P.sha_bytes(P.canonical(plan)),
        "calibration_sha256":plan["calibration_sha256"],
        "format":FORMAT}))
    good_by_day=Counter()
    bad_by_reason=Counter()
    recovered_stock_count=0
    repaired_full=0
    reused=0
    failed={}
    for code,doc in original.items():
        for d in doc["traded_days"]:
            good_by_day[d]+=1
    if xtdata is None and any(validate_recovery_receipt(recovery,code,fingerprint,
         sorted(d.isoformat() for d,stock in expected.items() if code in stock)) is None
         for code in missing):
        from xtquant import xtdata
    else:
        # Reuse 100% offline original/recovery SHA audit when all recovery receipts exist.
        xtdata = xtdata
    progress(f"QMT_RECOVERY_STEP_2_ONLY_MISSING_STOCKS={len(missing)}")
    tried=0
    for code in missing:
        dates=sorted(d for d in expected if code in expected[d])
        keys=[d.isoformat() for d in dates]
        try:
            receipt=validate_recovery_receipt(recovery,code,fingerprint,keys)
            if receipt is None:
                if limit and tried>=limit:
                    continue
                tried+=1
                raw=fetch_raw_by_day(xtdata,code,start,end)
                accepted_rows=[]
                approved=[]
                bad={}
                for day in dates:
                    try:
                        rows,detail=check_day(code,day,raw.get(day,[]),expected[day][code])
                        if rows is None:
                            bad[day.isoformat()]=detail
                        else:
                            approved.append(day.isoformat())
                            accepted_rows.extend(rows)
                    except Exception as e:
                        bad[day.isoformat()]={"day":day.isoformat(),
                                              "reason":type(e).__name__+": "+str(e)[:220]}
                extra=sorted(d.isoformat() for d in raw if d not in dates)
                if extra:
                    raise ValueError("Unexpected QMT dates outside official traded dates: "+str(extra[:8]))
                receipt=save_partial(recovery,code,accepted_rows,approved,bad,fingerprint)
                if tried<=3 or tried%20==0:
                    progress(f"QMT_RECOVERY_PROGRESS {tried}/{len(missing)} {code} approved_days={len(approved)} quarantined_days={len(bad)}")
                time.sleep(.1)
            else:
                reused+=1
            recovered_stock_count+=1
            repaired_full+=int(not receipt["quarantined_days"])
            for d in receipt["approved_days"]:
                good_by_day[d]+=1
            for item in receipt["quarantined_days"].values():
                reason=item.get("reason","UNKNOWN")
                bad_by_reason[reason.split(":")[0]]+=1
        except Exception as e:
            failed[code]=type(e).__name__+": "+str(e)[:300]
            progress(f"QMT_RECOVERY_STOCK_FAILED {code} {failed[code]}")
            if len(failed)>=12:
                progress("QMT_RECOVERY_CIRCUIT_BREAKER_12_FAILURES")
                break
    perday={d.isoformat():{"passed":good_by_day[d.isoformat()],
                           "expected":len(expected[d]),
                           "missing":len(expected[d])-good_by_day[d.isoformat()]}
            for d in sorted(expected)}
    original_keys=sum(len(x["traded_days"]) for x in original.values())
    expected_keys=sum(len(v) for v in expected.values())
    accepted_keys=sum(good_by_day.values())
    report={"format":FORMAT,"window":[str(start),str(end)],
            "expected_stocks":len(all_stocks),"original_full_stocks":len(original),
            "original_passed_stock_day_keys":original_keys,
            "original_quarantined_stocks":len(missing),
            "recovered_stocks":recovered_stock_count,
            "fully_recovered_stocks":repaired_full,
            "reused_recovery":reused,"new_recovery_attempts":tried,
            "expected_stock_day_keys":expected_keys,"accepted_stock_day_keys":accepted_keys,
            "remaining_stock_day_gaps":expected_keys-accepted_keys,
            "accepted_stock_day_coverage":round(accepted_keys/expected_keys,8),
            "per_day":perday,"quarantined_reason_counts":dict(bad_by_reason),
            "stock_level_failures":failed,
            "no_original_receipts_modified":True,"market_modified":False,
            "production_merge_authorized":False,
            "recovery_workspace":str(recovery)}
    P.safe_save(recovery/"latest_report.json",P.canonical(report))
    progress("QMT_RECOVERY_SUMMARY="+json.dumps({k:v for k,v in report.items()
        if k not in ("per_day","stock_level_failures")},sort_keys=True,ensure_ascii=False))
    progress("QMT_RECOVERY_PER_DAY="+json.dumps(perday,sort_keys=True,ensure_ascii=False))
    return report


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root",type=Path,default=Path("D:/stock"))
    ap.add_argument("--start",type=date.fromisoformat,default=START)
    ap.add_argument("--end",type=date.fromisoformat,default=END)
    ap.add_argument("--limit-stocks",type=int,default=0)
    args=ap.parse_args(argv)
    if (args.start!=START or args.end!=END or args.limit_stocks<0
            or args.limit_stocks>10000):
        ap.error("This recovery is pinned to the verified 2026-10-14..2026-11-12 historical stage")
    run(args.root,start=args.start,end=args.end,limit=args.limit_stocks)


if __name__=="__main__":
    main()
