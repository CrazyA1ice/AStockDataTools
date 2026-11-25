#!/usr/bin/env python3
"""Read-only adapter: producer daily quarantine receipts -> generic quality cases.

Supports any bounded date range; never contacts QMT or changes raw/daily files.
An accepted-stock Parquet digest authenticates ONLY that accepted candidate,
not missing/quarantined QMT raw minutes or an independent official reference.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import re

import market_quality_engine as Q

FORMAT = "one_command_qmt_market_update_v1"
STATUS = "READ_ONLY_DAILY_QUARANTINE_QUALITY_TRIAGE"
SYMBOL = re.compile(r"^(SH|SZ|BJ)[0-9]{6}$")
OHLC_REASON = re.compile(
    r"Independent official DAY materialized OHLC discrepancy: (open|high|low|close)"
)
ONE_MINUTE_MISSING = "QMT returned no original OHLCVA 1m"
MAX_DAYS = 180
MAX_RECEIPT_BYTES = 24 * 1024 * 1024
MAX_PARQUET_BYTES = 2 * 1024 * 1024 * 1024


class AdapterError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise AdapterError(reason)


def parse_day(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value),
            "INVALID_DATE")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AdapterError("INVALID_DATE") from exc


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_OBJECT_KEY")
        result[key] = value
    return result


def _raw_file(path, *, max_bytes):
    path = Path(path)
    require(path.is_file() and not path.is_symlink()
            and 0 < path.stat().st_size <= max_bytes,
            "INPUT_MISSING_SYMLINK_OR_INVALID_SIZE")
    return path


def _hash_file(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            chunk = f.read(4 * 1024 * 1024)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


def _load_day_receipt(receipt_path, parquet_path):
    receipt_path = _raw_file(receipt_path, max_bytes=MAX_RECEIPT_BYTES)
    parquet_path = _raw_file(parquet_path, max_bytes=MAX_PARQUET_BYTES)
    require(receipt_path.parent == parquet_path.parent
            and receipt_path.stem == parquet_path.stem
            and receipt_path.suffix == ".json" and parquet_path.suffix == ".parquet",
            "DAILY_SOURCE_PAIR_PATHS_MISMATCH")
    receipt_bytes = receipt_path.read_bytes()
    try:
        data = json.loads(receipt_bytes.decode("utf-8"),
                          object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AdapterError("DAILY_RECEIPT_JSON_INVALID") from exc
    require(isinstance(data, dict) and data.get("format") == FORMAT
            and data.get("date") == receipt_path.stem,
            "DAILY_RECEIPT_IDENTITY_CHANGED")
    parse_day(data["date"])
    require(data.get("source_family") == "QMT_AND_TDX_OFFICIAL_DAY"
            and data.get("production_merge_authorized") is False,
            "DAILY_RECEIPT_SOURCE_OR_PERMISSION_CHANGED")
    accepted = data.get("stock_days_accepted")
    expected = data.get("expected_stock_days")
    count = data.get("rows")
    require(type(accepted) is int and type(expected) is int
            and type(count) is int and 0 <= accepted <= expected <= 100000
            and count == accepted * 240, "DAILY_RECEIPT_STOCK_COUNTS_INVALID")
    quarantined = data.get("quarantined")
    require(isinstance(quarantined, dict)
            and len(quarantined) == expected - accepted,
            "DAILY_RECEIPT_QUARANTINE_COUNT_INVALID")
    for symbol, reason in quarantined.items():
        require(SYMBOL.fullmatch(symbol) and isinstance(reason, str)
                and 0 < len(reason) <= 250, "DAILY_RECEIPT_QUARANTINE_INVALID")
    sha = data.get("sha256")
    require(isinstance(sha, str) and Q.HEX64.fullmatch(sha),
            "DAILY_CANDIDATE_SHA_INVALID")
    actual = _hash_file(parquet_path)
    require(actual.lower() == sha.lower(), "DAILY_CANDIDATE_SHA_CHANGED")
    return data, hashlib.sha256(receipt_bytes).hexdigest(), actual


def _case_for_quarantine(day, symbol, reason, receipt_sha, candidate_sha):
    # Actual QMT raw source SHA and official DAY raw SHA are NOT in this
    # daily receipt. Never substitute the accepted candidate Parquet SHA.
    raw_empty = ONE_MINUTE_MISSING in reason
    match = OHLC_REASON.search(reason)
    record = {
        "format": Q.FORMAT, "trading_day":day, "symbol":symbol,
        "period":"1min", "source_id":"qmt-daily-stage",
        "source_state":"READY" if raw_empty else "UNKNOWN",
        "official_stock_day":None,
        "observed_bars":0 if raw_empty else None,
        "expected_bars":241,
        "grid_complete":None,
        "raw_source_sha256":None,
        "official_reference_sha256":None,
        "calibration_verified":None,
        "receipt_integrity_valid":True,
        "producer_quarantined":True,
        "producer_receipt_sha256":receipt_sha,
        "accepted_candidate_parquet_sha256_not_raw_qmt":candidate_sha,
        "producer_error_category":("QMT_RAW_MINUTE_EMPTY" if raw_empty else
                                   "OFFICIAL_MATERIALIZED_FIELD_REJECTED" if match else
                                   "OTHER_PRODUCER_QUARANTINE"),
    }
    if match:
        # The producer rejects on its FIRST mismatch; other five fields
        # are not certified by the truncated error string.
        record["fields_within_tolerance"]={match.group(1):False}
    return record


def classify_daily(root, *, start_day, end_day):
    """Inspect only existing bounded daily receipts; no calendar-day guessing."""
    start, end = parse_day(start_day), parse_day(end_day)
    require(start <= end and (end-start).days < MAX_DAYS,
            "INVALID_OR_OVERSIZE_DATE_RANGE")
    root=Path(root)
    require(root.is_dir() and not root.is_symlink(), "MODULE_ROOT_MISSING_OR_SYMLINK")
    folder=root / "work" / "market_update" / "daily"
    require(folder.is_dir() and not folder.is_symlink(),
            "DAILY_CANDIDATE_DIR_MISSING_OR_SYMLINK")
    candidates=[]
    for path in sorted(folder.glob("*.json")):
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", path.stem):
            continue
        day=parse_day(path.stem)
        if start <= day <= end:
            candidates.append(path)
    require(0 < len(candidates) <= MAX_DAYS,
            "NO_VERIFIABLE_RECEIPTS_IN_REQUESTED_WINDOW")
    records=[]
    source_receipts=[]
    total_accepted=0
    for receipt in candidates:
        doc, receipt_sha, parquet_sha=_load_day_receipt(
            receipt, receipt.with_suffix(".parquet"))
        total_accepted+=doc["stock_days_accepted"]
        source_receipts.append({
            "day":doc["date"],
            "producer_receipt_bytes_sha256":receipt_sha,
            "accepted_candidate_parquet_sha256":parquet_sha,
            "reported_accepted_stock_days":doc["stock_days_accepted"],
            "reported_quarantined_stock_days":len(doc["quarantined"]),
            "candidate_physical_sha_matches_receipt":True,
            "quarantined_raw_qmt_sha_verified":False,
            "official_day_reference_independently_verified":False,
        })
        for symbol, reason in sorted(doc["quarantined"].items()):
            records.append(_case_for_quarantine(doc["date"],symbol,reason,
                                                receipt_sha,parquet_sha))
    require(len(records) <= Q.MAX_CASES, "TOO_MANY_QUARANTINES_TO_CLASSIFY")
    classified=(Q.analyze_batch(records) if records else {
        "format": Q.REPORT + "_batch", "case_count":0,
        "by_quality_state":{}, "cases":[],
        "market_files_modified":False, "source_download_calls":0,
        "production_admission_authorized":False,
    })
    return {
        "status":STATUS, "window":[start.isoformat(),end.isoformat()],
        "existing_day_receipts_checked":len(source_receipts),
        "producer_accepted_stock_days_reported_not_recrossvalidated":total_accepted,
        "producer_quarantines_preserved":len(records),
        "source_receipts":source_receipts,
        "quality_cases":classified,
        "original_paid_qmt_source_independently_certified":False,
        "official_day_source_independently_certified":False,
        "data_quality_cleared":False, "production_merge_authorized":False,
        "qmt_cache_write_authorized":False, "project_market_files_modified":False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module-root",type=Path,required=True)
    parser.add_argument("--start-day",required=True)
    parser.add_argument("--end-day",required=True)
    args=parser.parse_args(argv)
    try:
        result=classify_daily(args.module_root,start_day=args.start_day,
                              end_day=args.end_day)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True,
                         indent=2,allow_nan=False))
        return 0
    except (AdapterError,Q.QualityPolicyError,OSError,ValueError,TypeError) as exc:
        print("MARKET_DAILY_QUALITY_ADAPTER_REVIEW_REQUIRED: "+str(exc)[:180])
        return 3


if __name__=="__main__":
    raise SystemExit(main())
