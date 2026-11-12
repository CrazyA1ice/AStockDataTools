#!/usr/bin/env python3
"""Read-only QMT 1m historical OHLCVA acceptance probe.

Requires a running, entitled MiniQMT/xtquant on the same Windows machine.
Downloads history into QMT's own cache and writes SHA-pinned private JSONL
under ParquetLiveSync/work/qmt_1m_probe/. NEVER touches AllCycleAStockData.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re

CN = timezone(timedelta(hours=8))
DEFAULT_CODES = ("600000.SH", "000001.SZ", "688001.SH")
TARGET_DATES = ("2026-10-14", "2026-10-20", "2026-11-11")
FIELDS = ("open", "high", "low", "close", "volume", "amount")
WORK = Path(__file__).resolve().parent / "work" / "qmt_1m_probe"
FORMAT = "qmt_1m_history_ohlcva_private_probe_v1"


def normalize_code(code):
    code = str(code).strip().upper()
    if re.fullmatch(r"(SH|SZ)\d{6}", code):
        return code[2:] + "." + code[:2]
    if re.fullmatch(r"\d{6}\.(SH|SZ)", code):
        return code
    raise ValueError("QMT sample must be a Shanghai or Shenzhen 6-digit code")


def parse_time(value):
    """QMT may expose millisecond epoch, datetime, or YYYYMMDD[HHMMSS]."""
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.replace(tzinfo=CN) if value.tzinfo is None else value.astimezone(CN)
    s = str(value).strip()
    if re.fullmatch(r"\d{13}", s):
        return datetime.fromtimestamp(int(s) / 1000, CN)
    if re.fullmatch(r"\d{10}", s):
        return datetime.fromtimestamp(int(s), CN)
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=CN)
        except ValueError:
            pass
    raise ValueError("Unsupported QMT minute timestamp: " + s[:40])


def normalize_frame(frame, code, start, end):
    if frame is None or not hasattr(frame, "iterrows"):
        raise ValueError("QMT returned no DataFrame")
    missing = set(FIELDS) - set(frame.columns)
    if missing:
        raise ValueError("QMT OHLCVA columns missing: " + ",".join(sorted(missing)))
    output, seen = [], set()
    for index, row in frame.iterrows():
        stamp = parse_time(row["time"] if "time" in frame.columns else index)
        if not start <= stamp.date() <= end:
            raise ValueError("QMT returned a minute outside requested date window")
        hm = stamp.hour * 60 + stamp.minute
        # Accept market clock labels pending physical purchased-feed timestamp calibration.
        if not (570 <= hm <= 690 or 780 <= hm <= 900):
            raise ValueError("QMT returned a minute outside Shanghai/Shenzhen sessions")
        vals = {}
        for field in FIELDS:
            raw = row[field]
            if isinstance(raw, bool):
                raise ValueError("Boolean QMT OHLCVA value")
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError("Nonfinite QMT OHLCVA value")
            vals[field] = value
        if min(vals[f] for f in FIELDS[:4]) <= 0:
            raise ValueError("Invalid QMT OHLC price; no synthetic correction")
        if not (vals["low"] <= min(vals["open"], vals["close"]) <= vals["high"]
                and vals["low"] <= max(vals["open"], vals["close"]) <= vals["high"]):
            raise ValueError("QMT OHLC invariant violated")
        if vals["volume"] < 0 or vals["amount"] < 0:
            raise ValueError("Negative QMT volume/amount")
        t = stamp.isoformat()
        if t in seen:
            raise ValueError("Duplicate QMT minute timestamp")
        seen.add(t)
        output.append({"datetime_cn": t, "symbol": code, **vals})
    output.sort(key=lambda item: item["datetime_cn"])
    return output


def write_private(root, code, rows, start, end):
    root = Path(root)
    if root.is_symlink() or root.resolve() == Path(os.path.abspath(os.sep)):
        raise ValueError("Unsafe QMT private root")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError("Linked QMT private root")
    slug = f"{code.replace('.', '_')}-{start:%Y%m%d}-{end:%Y%m%d}"
    body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False,
                              separators=(",", ":")) + "\n" for row in rows).encode("utf-8")
    sha = hashlib.sha256(body).hexdigest()
    target = root / f"{slug}-{sha[:16]}.jsonl"
    if target.is_symlink():
        raise ValueError("Linked QMT private output")
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != sha:
            raise ValueError("Existing private QMT receipt SHA mismatch")
    else:
        tmp = root / (target.name + ".part")
        if tmp.is_symlink():
            raise ValueError("Linked temporary QMT path")
        with tmp.open("xb") as f:
            f.write(body)
        os.replace(tmp, target)
    days = Counter(row["datetime_cn"][:10] for row in rows)
    return {"symbol":code,"rows":len(rows),"first":rows[0]["datetime_cn"] if rows else None,
            "last":rows[-1]["datetime_cn"] if rows else None,
            "daily_counts":dict(sorted(days.items())),
            "sha256":sha,"private_path":str(target),
            "coverage_not_certified":True,"market_files_modified":False}


def probe(codes, start, end, root=WORK, xtdata=None):
    if xtdata is None:
        try:
            from xtquant import xtdata
        except ImportError as exc:
            raise RuntimeError("xtquant unavailable: run with the QMT-provided Python SDK") from exc
    results = []
    for raw_code in codes:
        code = normalize_code(raw_code)
        print(f"QMT_DOWNLOAD {code} 1m {start}..{end}", flush=True)
        xtdata.download_history_data(code, period="1m", start_time=start.strftime("%Y%m%d"),
                                     end_time=end.strftime("%Y%m%d"))
        data = xtdata.get_market_data_ex(
            field_list=list(FIELDS), stock_list=[code], period="1m",
            start_time=start.strftime("%Y%m%d"),
            end_time=end.strftime("%Y%m%d"), count=-1,
            dividend_type="none", fill_data=False)
        if not isinstance(data, dict) or code not in data:
            raise ValueError(f"QMT did not return expected symbol {code}")
        rows = normalize_frame(data[code], code, start, end)
        if not rows:
            raise ValueError(f"QMT returned zero 1m OHLCVA rows for {code}")
        receipt = write_private(root, code, rows, start, end)
        receipt["target_dates"] = {day:receipt["daily_counts"].get(day, 0)
                                   for day in TARGET_DATES if start.isoformat() <= day <= end.isoformat()}
        results.append(receipt)
        print("QMT_PROBE_RESULT " + json.dumps(receipt, ensure_ascii=False, sort_keys=True), flush=True)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(DEFAULT_CODES))
    parser.add_argument("--start", default="2026-10-14")
    parser.add_argument("--end", default="2026-11-12")
    parser.add_argument("--work", type=Path, default=WORK)
    args = parser.parse_args(argv)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if start > end or start < date(2026, 10, 14) or end > datetime.now(CN).date():
        parser.error("Invalid requested historical interval")
    codes = [normalize_code(v) for v in args.symbols.split(",")]
    if len(set(codes)) != len(codes) or not 1 <= len(codes) <= 10:
        parser.error("Provide 1..10 distinct sample codes")
    print("QMT_SOURCE_ONLY_NO_MARKET_WRITE", flush=True)
    probe(codes, start, end, args.work)


if __name__ == "__main__":
    main()
