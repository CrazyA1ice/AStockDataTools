#!/usr/bin/env python3
"""只读：Hikyuu H5 与购买的年度 Parquet 数据按年/周期核验差集、交集和量价差异。

逐年、逐周期处理，SQLite临时库有界内存；输出JSON及中文Markdown，支持 --resume。
注意：当前版本对 day/5min/1min 生效，其他周期属于后续开发范围。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import tempfile
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PERIODS = ("day", "5min", "1min")
NEEDED = ("ts", "symbol", "open", "high", "low", "close", "volume", "amount")
H5_FIELDS = ("datetime", "openPrice", "highPrice", "lowPrice", "closePrice", "transCount", "transAmount")
ALIASES = {"SH": "SH", "SHSE": "SH", "SSE": "SH", "XSHG": "SH",
           "SZ": "SZ", "SZSE": "SZ", "XSHE": "SZ",
           "BJ": "BJ", "BSE": "BJ", "BJSE": "BJ", "XBSE": "BJ"}
UTC8 = timezone(timedelta(hours=8))
MAX_EXAMPLES = 24
YEAR_NAME = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
MODULE_DIR = Path(__file__).resolve().parent.parent



def symbol_id(value):
    s = str(value).strip().upper()
    m = re.fullmatch(r"([A-Z]{2,5})[.:-]?(\d{6})", s)
    if m and m.group(1) in ALIASES:
        return ALIASES[m.group(1)] + m.group(2)
    m = re.fullmatch(r"(\d{6})[.:-]([A-Z]{2,5})", s)
    if m and m.group(2) in ALIASES:
        return ALIASES[m.group(2)] + m.group(1)
    if re.fullmatch(r"(?:SH|SZ|BJ)\d{6}", s):
        return s
    return None


def is_a_share_candidate(symbol: str, year: int) -> bool:
    """Conservative code-pattern filter for A-share equity candidates.

    Not a certified security master. Historical BJ pre-opening/legacy
    remappings are deliberately isolated, not relabeled as A shares.
    """
    if not isinstance(symbol, str) or len(symbol) != 8:
        return False
    venue, code = symbol[:2], symbol[2:]
    if not code.isdigit():
        return False
    if venue == "SH":
        return code.startswith(("600", "601", "603", "605")) or (
            year >= 2019 and code.startswith(("688", "689")))
    if venue == "SZ":
        return code.startswith(("000", "001", "002", "003", "300", "301"))
    if venue == "BJ":
        # 2021-11-15 market launch; year-wide conservative exclusion of
        # 2021 transitional listings because exact day+old-code remapping
        # needs security master validation.
        return year >= 2022 and code.startswith(("920", "430", "830", "870"))
    return False


def pq_stamp(epoch_ms, period):
    """购买的 Parquet: UTC epoch_ms；5min 时间戳按起点 +5m，都是候选规则。"""
    d = datetime.fromtimestamp(int(epoch_ms) / 1000, tz=UTC8)
    if period == "5min":
        d += timedelta(minutes=5)
    if period == "day":
        return int(d.strftime("%Y%m%d")) * 10000
    return int(d.strftime("%Y%m%d%H%M"))


def year_files(root, period, year):
    folder = root / "AllCycleAStockData" / period
    if not folder.is_dir():
        return []
    return sorted(
        p for p in folder.rglob("*.parquet")
        if not p.is_symlink()
        and str(year) in YEAR_NAME.findall(p.relative_to(folder).as_posix())
    )


def h5_year_slice(ds, year):
    lo_key, hi_key = year * 100000000, (year + 1) * 100000000

    def lower(key):
        lo, hi = 0, len(ds)
        while lo < hi:
            mid = (lo + hi) // 2
            if int(ds[mid]["datetime"]) < key:
                lo = mid + 1
            else:
                hi = mid
        return lo

    return lower(lo_key), lower(hi_key)


def parse_day_range(year, from_date=None, to_date=None):
    """Validated inclusive Beijing-calendar bounds, or full year when omitted."""
    left=date.fromisoformat(from_date) if from_date else date(year,1,1)
    right=date.fromisoformat(to_date) if to_date else date(year,12,31)
    if left.year != year or right.year != year or left > right:
        raise ValueError(f"Date window must be within {year}, start<=end")
    lower=int(left.strftime("%Y%m%d"))*10000
    upper=int((right+timedelta(days=1)).strftime("%Y%m%d"))*10000
    lower_ms=int(datetime(left.year,left.month,left.day,tzinfo=UTC8).timestamp()*1000)
    after=right+timedelta(days=1)
    upper_ms=int(datetime(after.year,after.month,after.day,tzinfo=UTC8).timestamp()*1000)
    return lower, upper, lower_ms, upper_ms


def h5_key_slice(ds, lower_key, upper_key):
    """Binary search sorted H5 dataset datetime without loading full history."""
    def lower(target):
        lo,hi=0,len(ds)
        while lo<hi:
            mid=(lo+hi)//2
            if int(ds[mid]["datetime"])<target:
                lo=mid+1
            else:
                hi=mid
        return lo
    return lower(lower_key),lower(upper_key)


def row_group_overlaps_timestamp(row_group, low_ms, high_ms):
    """Only skip a row group when trustworthy ts min/max proves non-overlap."""
    for c in range(row_group.num_columns):
        column=row_group.column(c)
        if column.path_in_schema != "ts":
            continue
        st=column.statistics
        if st is None or not st.has_min_max:
            return True
        try:
            return not (int(st.max)<low_ms or int(st.min)>=high_ms)
        except (ValueError,TypeError,OverflowError):
            return True
    return True


def db_open(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("PRAGMA synchronous=OFF")
    db.execute("PRAGMA temp_store=MEMORY")
    db.execute("PRAGMA cache_size=-65536")
    db.execute(
        "CREATE TABLE h (s TEXT,t INTEGER,o REAL,hi REAL,lo REAL,c REAL,v REAL,a REAL,"
        "seen INT DEFAULT 0, PRIMARY KEY(s,t)) WITHOUT ROWID"
    )
    db.execute("CREATE TEMP TABLE p (s TEXT,t INTEGER,o REAL,hi REAL,lo REAL,c REAL,v REAL,a REAL)")
    db.execute("CREATE INDEX p_key ON p(s,t)")
    # Scratch-only key table: catch duplicate Parquet keys across all Arrow
    # batches and RowGroups, not just within the current batch.
    db.execute("CREATE TABLE pq_seen (s TEXT,t INTEGER,PRIMARY KEY(s,t)) WITHOUT ROWID")
    return db


def update_bounds(stats, origin, low, high):
    lk, hk = origin+"_earliest", origin+"_latest"
    if stats.get(lk) is None or low < stats[lk]:
        stats[lk] = low
    if stats.get(hk) is None or high > stats[hk]:
        stats[hk] = high


def store_h5(db, root, period, year, stats, universe="all", from_date=None, to_date=None, progress=False):
    import h5py

    total = 0
    lower,upper,_,_=parse_day_range(year,from_date,to_date)
    started=time.monotonic()
    for market in ("sh", "sz", "bj"):
        path = root / "HikyuuData" / f"{market}_{period}.h5"
        if not path.is_file():
            stats["missing_h5_market_files"] += 1
            continue
        with h5py.File(path, "r") as f:
            group = f.get("data")
            if not isinstance(group, h5py.Group):
                stats["h5_schema_errors"] += 1
                continue
            symbols=list(group.keys())
            for idx,symbol in enumerate(symbols):
                if progress and idx and idx % 400 == 0:
                    print(f"  H5 {market.upper()} symbols {idx:,}/{len(symbols):,}, "
                          f"indexed bars={total:,}, elapsed={time.monotonic()-started:.1f}s",
                          flush=True)
                if not re.fullmatch(market.upper() + r"\d{6}", symbol):
                    continue
                ds = group.get(symbol)
                if universe == "a-share-candidate" and not is_a_share_candidate(symbol, year):
                    if isinstance(ds, h5py.Dataset) and "datetime" in (ds.dtype.names or ()):
                        left_skip, right_skip = h5_key_slice(ds, lower,upper)
                        stats["h5_excluded_non_equity_rows"] += right_skip - left_skip
                    stats["h5_excluded_non_equity_symbol_datasets"] += 1
                    continue
                if not isinstance(ds, h5py.Dataset) or not set(H5_FIELDS).issubset(ds.dtype.names or ()):
                    stats["h5_schema_errors"] += 1
                    continue
                left, right = h5_key_slice(ds,lower,upper)
                for begin in range(left, right, 8192):
                    block = ds[begin:min(right, begin + 8192)]
                    vals = []
                    for x in block:
                        t = int(x["datetime"])
                        vals.append((
                            symbol, t,
                            float(x["openPrice"]) / 1000,
                            float(x["highPrice"]) / 1000,
                            float(x["lowPrice"]) / 1000,
                            float(x["closePrice"]) / 1000,
                            float(x["transCount"]) * (100 if period == "day" else 1),
                            float(x["transAmount"]) * 1000
                        ))
                    before = db.total_changes
                    db.executemany(
                        "INSERT OR IGNORE INTO h(s,t,o,hi,lo,c,v,a) VALUES(?,?,?,?,?,?,?,?)",
                        vals
                    )
                    inserted = db.total_changes - before
                    total += inserted
                    stats["h5_duplicate_keys"] += len(vals) - inserted
                    if vals:
                        update_bounds(stats, "h5", vals[0][1], vals[-1][1])
        db.commit()
        if progress:
            print(f"  H5 {market.upper()} completed: {total:,} indexed bars, {time.monotonic()-started:.1f}s elapsed",flush=True)
    stats["h5_rows"] = total
    return total


def example(stats, category, symbol, stamp, fields=None):
    entry = {"symbol": symbol, "bar_end": str(stamp)}
    if fields:
        entry["different_fields"] = fields
    arr = stats.setdefault(category+"_examples", [])
    if len(arr) < MAX_EXAMPLES:
        arr.append(entry)
    last = stats.setdefault(category+"_latest_examples", [])
    last.append(entry)
    if len(last) > MAX_EXAMPLES:
        del last[0]


def pq_metadata_only(paths, stats, universe="all"):
    """仅H5该周期该年没有K线时，用Parquet footer做候选覆盖估计；不是逐条验证。"""
    import pyarrow.parquet as pq

    for p in paths:
        pf = pq.ParquetFile(str(p))
        if not set(NEEDED).issubset(pf.schema_arrow.names):
            stats["schema_errors"] += 1
            continue
        stats["pq_rows"] += pf.metadata.num_rows
        stats["pq_only_candidate_rows_from_year_file_metadata"] += pf.metadata.num_rows
        for rg_idx in range(pf.metadata.num_row_groups):
            rg = pf.metadata.row_group(rg_idx)
            for col_idx in range(rg.num_columns):
                c = rg.column(col_idx)
                if c.path_in_schema == "ts" and c.statistics is not None and c.statistics.has_min_max:
                    try:
                        update_bounds(
                            stats, "pq",
                            pq_stamp(c.statistics.min, stats["period"]),
                            pq_stamp(c.statistics.max, stats["period"])
                        )
                    except (ValueError, OverflowError, OSError):
                        stats["timestamp_errors"] += 1
    stats["pq_year_metadata_only_no_h5_rows"] = True
    if universe == "a-share-candidate":
        stats["pq_footer_contains_unfiltered_security_types"] = True
        stats["pq_footer_row_count_not_equity_filtered"] = True


def count_difference(stats, category, symbol, stamp):
    day = str(stamp // 10000)
    day_bucket = stats.setdefault("by_day", {}).setdefault(day, {})
    day_bucket[category] = day_bucket.get(category, 0) + 1
    stock_bucket = stats.setdefault("by_symbol", {}).setdefault(symbol, {})
    stock_bucket[category] = stock_bucket.get(category, 0) + 1
    lo, hi = category+"_earliest", category+"_latest"
    if stats.get(lo) is None or stamp < stats[lo]:
        stats[lo] = stamp
    if stats.get(hi) is None or stamp > stats[hi]:
        stats[hi] = stamp


def symbol_prefix_group(symbol):
    """Descriptive code-prefix groups; never certify the actual listed board."""
    if symbol.startswith(("SH688", "SH689")):
        return "SH_688_689_prefix"
    if symbol.startswith(("SZ300", "SZ301")):
        return "SZ_300_301_prefix"
    if symbol.startswith("BJ"):
        return "BJ_prefix"
    if symbol.startswith("SH"):
        return "SH_other_prefix"
    if symbol.startswith("SZ"):
        return "SZ_other_prefix"
    return "unclassified_prefix"


def increment_prefix(stats, symbol, field):
    groups = stats.setdefault("by_code_prefix_group", {})
    counts = groups.setdefault(symbol_prefix_group(symbol), {})
    counts[field] = counts.get(field, 0) + 1


def summarize_stock_day_gaps(db, stats):
    """Classify full-vs-partial source absence using exact H5/PQ keys.

    This is only about keys actually present in each input. It cannot certify
    an instrument's listing status, data vendor quality or missing-trade truth.
    """
    h5_stock_days = {}
    for symbol, day, total, common in db.execute(
            "SELECT s,CAST(t / 10000 AS INTEGER),COUNT(*),"
            "SUM(CASE WHEN seen=1 THEN 1 ELSE 0 END) "
            "FROM h GROUP BY s,CAST(t / 10000 AS INTEGER)"):
        h5_stock_days[(symbol, day)] = (int(total), int(common or 0))
    pq_stock_days = {}
    for symbol, day, count in db.execute(
            "SELECT s,CAST(t / 10000 AS INTEGER),COUNT(*) "
            "FROM pq_seen GROUP BY s,CAST(t / 10000 AS INTEGER)"):
        pq_stock_days[(symbol, day)] = int(count)
    keys = sorted(set(h5_stock_days) | set(pq_stock_days))
    names = ("both_present_stock_days",
             "pq_only_full_h5_absence_stock_days",
             "pq_only_partial_h5_coverage_stock_days",
             "pq_only_keys_on_full_h5_absence_days",
             "pq_only_keys_on_partial_h5_coverage_days",
             "h5_only_full_pq_absence_stock_days",
             "h5_only_partial_pq_coverage_stock_days",
             "h5_only_keys_on_full_pq_absence_days",
             "h5_only_keys_on_partial_pq_coverage_days")
    totals = {name: 0 for name in names}
    full_pq_examples, partial_pq_examples = [], []
    for symbol, day in keys:
        h5_n, matched = h5_stock_days.get((symbol, day), (0, 0))
        pq_n = pq_stock_days.get((symbol, day), 0)
        if not 0 <= matched <= min(h5_n, pq_n):
            raise ValueError("Stock-day matched key count outside source bounds")
        pq_only = pq_n - matched
        h5_only = h5_n - matched
        day_bucket = stats.setdefault("by_day", {}).setdefault(str(day), {})
        if h5_n and pq_n:
            totals["both_present_stock_days"] += 1
        if pq_only:
            full = h5_n == 0
            tag = "full_h5_absence" if full else "partial_h5_coverage"
            totals[f"pq_only_{tag}_stock_days"] += 1
            totals[f"pq_only_keys_on_{tag}_days"] += pq_only
            day_key = f"pq_only_keys_on_{tag}_days"
            day_bucket[day_key] = day_bucket.get(day_key, 0) + pq_only
            examples = full_pq_examples if full else partial_pq_examples
            if len(examples) < 12:
                examples.append({"symbol": symbol, "day": str(day),
                                 "h5_keys": h5_n, "parquet_keys": pq_n,
                                 "parquet_only_keys": pq_only})
        if h5_only:
            full = pq_n == 0
            tag = "full_pq_absence" if full else "partial_pq_coverage"
            totals[f"h5_only_{tag}_stock_days"] += 1
            totals[f"h5_only_keys_on_{tag}_days"] += h5_only
            day_key = f"h5_only_keys_on_{tag}_days"
            day_bucket[day_key] = day_bucket.get(day_key, 0) + h5_only
    if (totals["pq_only_keys_on_full_h5_absence_days"]
        + totals["pq_only_keys_on_partial_h5_coverage_days"]
        != stats["pq_only_rows"]):
        raise ValueError("Parquet-only stock-day key conservation failed")
    if (totals["h5_only_keys_on_full_pq_absence_days"]
        + totals["h5_only_keys_on_partial_pq_coverage_days"]
        != stats["h5_only_rows"]):
        raise ValueError("H5-only stock-day key conservation failed")
    totals["candidate_stock_days_in_either_source"] = len(keys)
    totals["examples_full_h5_absence"] = full_pq_examples
    totals["examples_partial_h5_coverage"] = partial_pq_examples
    totals["source_key_gap_does_not_certify_missing_trades"] = True
    return totals


def check_batch(db, rows, stats, period):
    if not rows:
        return
    db.execute("DELETE FROM p")
    db.executemany("INSERT INTO p VALUES(?,?,?,?,?,?,?,?)", rows)
    ndup = db.execute(
        "SELECT sum(n-1) FROM (SELECT count(*) AS n FROM p GROUP BY s,t HAVING n>1)"
    ).fetchone()[0]
    stats["pq_duplicate_keys_within_batch"] += int(ndup or 0)
    # Retain only the first row per key in this batch. Duplicates are flagged
    # (never treated as trustworthy candidate additions), not counted twice.
    if ndup:
        db.execute("DELETE FROM p WHERE rowid NOT IN "
                   "(SELECT MIN(rowid) FROM p GROUP BY s,t)")
    # Any key already observed in an earlier batch/RowGroup is a duplicate.
    # Never classify it again as matched/only/conflicting.
    previous_duplicates = db.execute(
        "SELECT COUNT(*) FROM p JOIN pq_seen AS seen "
        "ON seen.s=p.s AND seen.t=p.t").fetchone()[0]
    stats["pq_duplicate_keys_across_batches"] += int(previous_duplicates)
    if previous_duplicates:
        db.execute("DELETE FROM p WHERE EXISTS ("
                   "SELECT 1 FROM pq_seen AS seen "
                   "WHERE seen.s=p.s AND seen.t=p.t)")
    db.execute("INSERT INTO pq_seen SELECT s,t FROM p")
    stats["pq_unique_keys"] += db.execute("SELECT COUNT(*) FROM p").fetchone()[0]
    cursor = db.execute(
        "SELECT p.s,p.t,p.o,p.hi,p.lo,p.c,p.v,p.a,h.s,h.o,h.hi,h.lo,h.c,h.v,h.a "
        "FROM p LEFT JOIN h ON p.s=h.s AND p.t=h.t"
    )
    for z in cursor:
        sym, t = z[:2]
        if z[8] is None:
            if period == "1min" and t % 10000 == 930:
                stats["pq_0930_extra_candidate_rows"] += 1
                count_difference(stats, "pq_0930", sym, t)
            else:
                stats["pq_only_rows"] += 1
                increment_prefix(stats, sym, "pq_only")
                count_difference(stats, "pq_only", sym, t)
                example(stats, "pq_only", sym, t)
            continue
        stats["matched_keys"] += 1
        increment_prefix(stats, sym, "matched")
        bucket = stats.setdefault("by_day", {}).setdefault(str(t // 10000), {})
        bucket["matched"] = bucket.get("matched", 0) + 1
        p, h = z[2:8], z[9:]
        differing = []
        for i, name in enumerate(("open", "high", "low", "close")):
            if abs(p[i] - h[i]) > 0.005:
                differing.append(name)
        if abs(p[4]-h[4]) > max(1.0, 0.00001*max(abs(p[4]), abs(h[4]))):
            differing.append("volume")
        if abs(p[5]-h[5]) > max(1000.0, 0.001*max(abs(p[5]), abs(h[5]))):
            differing.append("amount")
        if differing:
            category = (
                "opening_candidate_mismatch"
                if period == "1min" and t % 10000 == 931
                else "value_mismatch"
            )
            stats[category+"_rows"] += 1
            increment_prefix(stats, sym, category)
            count_difference(stats, category, sym, t)
            if any(x in differing for x in ("open", "high", "low", "close")):
                stats["price_mismatch_rows"] += 1
                increment_prefix(stats, sym, "price_mismatch")
                bucket["price_mismatch"] = bucket.get("price_mismatch", 0) + 1
            if any(x in differing for x in ("volume", "amount")):
                stats["quantity_mismatch_rows"] += 1
                increment_prefix(stats, sym, "quantity_mismatch")
                bucket["quantity_mismatch"] = bucket.get("quantity_mismatch", 0) + 1
            example(stats, category, sym, t, differing)
    db.execute("UPDATE h SET seen=1 WHERE (s,t) IN (SELECT s,t FROM p)")
    db.commit()


def scan_parquet(db, paths, period, year, stats, batch_size, universe="all",
                 from_date=None, to_date=None, progress=False):
    import pyarrow.parquet as pq

    lower, upper, low_ms, high_ms = parse_day_range(year,from_date,to_date)
    bounded=from_date is not None or to_date is not None
    started=time.monotonic()
    last_progress=started
    for file in paths:
        try:
            pf=pq.ParquetFile(str(file))
            if not set(NEEDED).issubset(pf.schema_arrow.names):
                stats["schema_errors"]+=1
                continue
            groups=pf.metadata.num_row_groups
            stats["pq_row_groups_total"]+=groups
            for group_i in range(groups):
                row_group=pf.metadata.row_group(group_i)
                if bounded and not row_group_overlaps_timestamp(row_group,low_ms,high_ms):
                    stats["pq_row_groups_skipped_by_time"]+=1
                    continue
                stats["pq_row_groups_read"]+=1
                for batch in pf.iter_batches(row_groups=[group_i],batch_size=batch_size,
                                             columns=list(NEEDED),use_threads=True):
                    timestamps=batch.column(0).to_pylist()
                    symbols=batch.column(1).to_pylist()
                    # Fast day filter before decoding six numeric arrays
                    indices=[]
                    if bounded:
                        for i,ts in enumerate(timestamps):
                            try:
                                if low_ms<=int(ts)<high_ms:
                                    indices.append(i)
                            except (ValueError,TypeError,OverflowError):
                                stats["timestamp_or_value_errors"]+=1
                    else:
                        indices=list(range(len(timestamps)))
                    stats["pq_source_rows_scanned"]+=len(timestamps)
                    if not indices:
                        continue
                    cols=[batch.column(i).to_pylist() for i in range(2,8)]
                    selected=[]
                    for i in indices:
                        sym=symbol_id(symbols[i])
                        if sym is None:
                            stats["unknown_pq_symbols"]+=1
                            continue
                        if universe=="a-share-candidate" and not is_a_share_candidate(sym,year):
                            stats["pq_excluded_non_equity_rows"]+=1
                            continue
                        stats["pq_rows"]+=1
                        try:
                            t=pq_stamp(timestamps[i],period)
                            if not lower<=t<upper:
                                stats["pq_rows_outside_filename_year"]+=1
                                continue
                            vals=[float(col[i]) for col in cols]
                            if not all(math.isfinite(v) for v in vals):
                                stats["nonfinite_parquet_rows"]+=1
                                continue
                        except (ValueError,TypeError,OverflowError,OSError):
                            stats["timestamp_or_value_errors"]+=1
                            continue
                        selected.append((sym,t,*vals))
                        update_bounds(stats,"pq",t,t)
                    check_batch(db,selected,stats,period)
                now=time.monotonic()
                if progress and (now-last_progress>=20 or group_i==groups-1):
                    print(f"  Parquet {file.name} group {group_i+1}/{groups}, "
                          f"read groups={stats['pq_row_groups_read']}, "
                          f"skipped={stats['pq_row_groups_skipped_by_time']}, "
                          f"source rows scanned={stats['pq_source_rows_scanned']:,}, "
                          f"window rows={stats['pq_rows']:,}, "
                          f"elapsed={now-started:.1f}s",flush=True)
                    last_progress=now
        except (OSError,ValueError,RuntimeError,TypeError) as exc:
            stats["parquet_file_read_errors"]+=1
            example(stats,"scan_error",file.name,0,[type(exc).__name__])

def h5_remaining(db, stats):
    for sym, t in db.execute("SELECT s,t FROM h WHERE seen=0 ORDER BY t"):
        if t % 10000 == 1300 and stats["period"] in ("1min", "5min"):
            stats["h5_1300_noon_label_suspect_rows"] += 1
        stats["h5_only_rows"] += 1
        increment_prefix(stats, sym, "h5_only")
        count_difference(stats, "h5_only", sym, t)
        example(stats, "h5_only", sym, t)


def reconcile_section(root, scratch, period, year, batch_size, universe="all",
                      from_date=None, to_date=None, progress=False):
    if universe not in ("all", "a-share-candidate"):
        raise ValueError("Invalid universe mode")
    stats = Counter()
    stats.update({
        "period": period, "year": year, "universe_mode": universe,
        "from_date": from_date, "to_date": to_date,
        "h5_rows": 0, "pq_rows": 0, "matched_keys": 0,
        "h5_only_rows": 0, "pq_only_rows": 0,
        "pq_0930_extra_candidate_rows": 0,
        "value_mismatch_rows": 0, "opening_candidate_mismatch_rows": 0,
        "price_mismatch_rows": 0, "quantity_mismatch_rows": 0,
        # Coverage provenance flags must exist even if the fallback path
        # was not taken. Their absence caused KeyError in bounded 5min
        # audits where H5 had zero rows and Parquet was scanned exactly.
        "pq_year_metadata_only_no_h5_rows": False,
        "pq_footer_contains_unfiltered_security_types": False,
        "pq_footer_row_count_not_equity_filtered": False
    })
    parse_day_range(year,from_date,to_date)
    paths = year_files(root, period, year)
    stats["parquet_year_files"] = len(paths)
    with tempfile.TemporaryDirectory(prefix="h5pq_", dir=str(scratch)) as temporary:
        db = db_open(Path(temporary)/"join.sqlite")
        try:
            count = store_h5(db, root, period, year, stats, universe,
                             from_date,to_date,progress)
            if not count and paths and from_date is None and to_date is None:
                pq_metadata_only(paths, stats, universe)
            elif paths:
                # With a bounded window, even an empty H5 slice needs exact
                # Parquet key enumeration, not an annual footer estimate.
                scan_parquet(db, paths, period, year, stats, batch_size, universe,
                             from_date,to_date,progress)
            h5_remaining(db, stats)
            # Build exact date-level coverage from the two key stores while
            # scratch SQLite is open. One multi-day Parquet pass, not a new
            # annual scan per trading day.
            by_day = stats.setdefault("by_day", {})
            for day_key, count in db.execute(
                    "SELECT CAST(t / 10000 AS INTEGER),COUNT(*) FROM h "
                    "GROUP BY CAST(t / 10000 AS INTEGER)"):
                bucket = by_day.setdefault(str(day_key), {})
                bucket["h5_unique"] = int(count)
            for day_key, count in db.execute(
                    "SELECT CAST(t / 10000 AS INTEGER),COUNT(*) FROM pq_seen "
                    "GROUP BY CAST(t / 10000 AS INTEGER)"):
                bucket = by_day.setdefault(str(day_key), {})
                bucket["parquet_unique"] = int(count)
            # For each day distinguish total overlapping time keys from
            # mismatches, and keep missing-series statuses explicit.
            if period == "5min" and paths and (from_date or to_date):
                stats["stock_day_gap_summary"] = summarize_stock_day_gaps(db, stats)
            for bucket in by_day.values():
                h5_n = bucket.get("h5_unique", 0)
                pq_n = bucket.get("parquet_unique", 0)
                common = bucket.get("matched", 0)
                only_h5 = bucket.get("h5_only", 0)
                only_pq = bucket.get("pq_only", 0)
                if stats["period"] == "1min":
                    only_pq += bucket.get("pq_0930", 0)
                if h5_n != common + only_h5 or pq_n != common + only_pq:
                    raise ValueError("Daily two-source unique-key conservation failed")
                bucket["intersection_unique"] = common
                bucket["union_candidate_unique"] = h5_n + pq_n - common
                bucket["overlap_value_mismatch_pct"] = (
                    round(100 * (bucket.get("value_mismatch", 0) +
                                 bucket.get("opening_candidate_mismatch", 0)) / common, 3)
                    if common else None)
        finally:
            db.close()
    issues = [
        k for k in (
            "h5_schema_errors", "schema_errors", "parquet_file_read_errors",
            "timestamp_or_value_errors", "nonfinite_parquet_rows",
            "unknown_pq_symbols", "pq_rows_outside_filename_year",
            "h5_duplicate_keys", "timestamp_errors",
            "pq_duplicate_keys_within_batch", "pq_duplicate_keys_across_batches",
            "missing_h5_market_files"
        ) if stats[k]
    ]
    stats["scan_complete"] = not issues
    stats["issues"] = issues
    stats["by_day"] = dict(sorted(stats.get("by_day", {}).items()))
    prefix_groups = stats.get("by_code_prefix_group", {})
    for entry in prefix_groups.values():
        n = entry.get("matched", 0)
        entry["overlap_value_mismatch_pct"] = (
            round(100 * entry.get("value_mismatch", 0) / n, 3)
            if n else None)
    stats["by_code_prefix_group"] = dict(sorted(prefix_groups.items()))
    stats["board_membership_certified"] = False
    affected = stats.get("by_symbol", {})
    stats["affected_symbols"] = len(affected)
    stats["by_symbol_top100"] = dict(
        sorted(affected.items(), key=lambda item: (-sum(item[1].values()), item[0]))[:100]
    )
    stats.pop("by_symbol", None)
    stats["security_master_certified"] = False
    stats["universe_filter_is_code_pattern_not_listing_verification"] = (universe == "a-share-candidate")
    stats["duplicate_keys_across_batches_not_exhaustively_checked"] = False
    stats["parquet_cross_batch_key_dedup_applied"] = True
    stats["parquet_key_coverage_exact_when_scan_complete"] = bool(
        paths and not stats["pq_year_metadata_only_no_h5_rows"]
        and stats["scan_complete"])
    stats["source_units_certified"] = False
    stats["safe_to_automatically_union"] = False
    stats["pq_only_candidate_rows_from_year_file_metadata_are_not_exact_keys"] = bool(
        stats["pq_year_metadata_only_no_h5_rows"]
    )
    return dict(stats)


def render_markdown(report):
    lines = [
        "# H5 与 Parquet 全量覆盖、差集、重叠K线核对报告",
        "", f"状态：**{report['status']}**。原始文件未修改。未认证的单位/时间映射只用于定位，不自动合并。",
        f"证券范围：**{report.get('universe_mode', 'all')}**；a-share-candidate仅是股票代码前缀过滤，尚非正式证券类型认证。",
        "", "| 周期 | 年份 | H5行 | Parquet行* | 交集键 | H5独有 | Parquet独有 | 量价差异 | 09:30候选 | 来源首末时间与状态 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"
    ]
    order = {p: i for i, p in enumerate(report["requested_periods"])}
    sections = sorted(report["results"].values(), key=lambda s: (order.get(s["period"], 99), s["year"]))
    for s in sections:
        span = (
            f"H5 {s.get('h5_earliest','—')}至{s.get('h5_latest','—')}; "
            f"P {s.get('pq_earliest','—')}至{s.get('pq_latest','—')}"
        )
        status = "完整" if s["scan_complete"] else "不完整:"+",".join(s["issues"])
        if s.get("pq_year_metadata_only_no_h5_rows"):
            status += "; 仅Parquet文件元数据"
        cells = [
            s["period"], str(s["year"]), str(s.get("h5_rows", 0)),
            str(s.get("pq_rows", 0)), str(s.get("matched_keys", 0)),
            str(s.get("h5_only_rows", 0)), str(s.get("pq_only_rows", 0)),
            str(s.get("value_mismatch_rows", 0)), str(s.get("pq_0930_extra_candidate_rows", 0)),
            span+"; "+status
        ]
        lines.append("| "+" | ".join(cells)+" |")
    if report.get("universe_mode") == "a-share-candidate":
        lines.extend(["", "## 证券范围过滤统计", "",
                      "| 年份/周期 | H5排除的非候选行数 | Parquet排除的非候选行数 | Parquet仅Footer未过滤 |",
                      "|---|---:|---:|---|"])
        for item in sections:
            lines.append(
                f"| {item['year']}/{item['period']} | "
                f"{item.get('h5_excluded_non_equity_rows',0)} | "
                f"{item.get('pq_excluded_non_equity_rows',0)} | "
                f"{'是（无从按股票过滤）' if item.get('pq_footer_row_count_not_equity_filtered') else '否'} |"
            )
    lines.extend([
        "", "*Parquet仅使用年度文件元数据统计的行数是候选覆盖量，不等于逐股票/分钟已核实的差集。",
        "", "## 时间重叠以外的数据与不一致K线（每类至多24个示例）"
    ])
    for s in sections:
        if not any(s.get(k) for k in (
            "h5_only_rows", "pq_only_rows", "value_mismatch_rows", "opening_candidate_mismatch_rows"
        )):
            continue
        lines.extend(["", f"### {s['period']} / {s['year']}"])
        for category, label in (
            ("h5_only", "H5独有"),
            ("pq_only", "Parquet独有"),
            ("value_mismatch", "相同键量价不一致"),
            ("opening_candidate_mismatch", "开盘09:31口径待确认")
        ):
            amount = s.get(category+"_rows", 0)
            if not amount:
                continue
            samples = ", ".join(
                entry["symbol"]+"@"+entry["bar_end"]+
                ("("+",".join(entry["different_fields"])+")" if entry.get("different_fields") else "")
                for entry in s.get(category+"_examples", [])[:8]
            )
            lines.append(f"- **{label}**：{amount} 条。示例：{samples or '无'}")
    lines.extend([
        "", "## 建议的后续并集流程（尚未执行）", "",
        "1. 核对原始文件结构和年度分区扫描完整性。",
        "2. 确认证券历史代码、价格复权、开盘/午间时标和量额单位的转换规则。",
        "3. 将唯一来源的已认证K线收录为只读补齐候选，所有冲突保留人工可追溯裁决。",
        "4. 只向新的输出目录生成H5/Parquet并集副本，校验行数及量额聚合，保留原库回滚。",
        "", "已知候选：5min Parquet起始时标+5分钟；1min的09:30单列；"
        "部分H5午间13:00可疑；H5金额×1000；H5 day 成交量×100。",
        "上述候选在采购源规则确认前都不可直接用于改写原始K线。", ""
    ])
    return "\n".join(lines)


def resolve_module_artifact_paths(out=None, scratch=None, module_dir=None):
    """Keep CLI-created reports and temporary files inside H5ParquetReconciler.

    Relative paths always resolve against the module, not the shell CWD.
    Explicit absolute paths outside this module fail closed. Existing reports
    moved to the module root remain resumable via --out filename.json.
    """
    module = Path(module_dir or MODULE_DIR).resolve()

    def inside_module(user_path, purpose):
        candidate = Path(user_path)
        # Accept commands copied from an older repo-root README without
        # nesting H5ParquetReconciler/H5ParquetReconciler twice.
        if not candidate.is_absolute():
            parts = candidate.parts
            if parts and parts[0].lower() == module.name.lower():
                parts = parts[1:]
            candidate = module.joinpath(*parts)
        candidate = candidate.resolve()
        if candidate == module or not candidate.is_relative_to(module):
            raise ValueError(
                f"{purpose} must stay inside the H5ParquetReconciler module: "
                f"{candidate}; module root: {module}"
            )
        return candidate

    report = inside_module(
        out if out is not None else Path("reports") / "h5-parquet-audit.json",
        "Report (--out)"
    )
    temp = inside_module(
        scratch if scratch is not None else Path("work") / "_union_scratch",
        "Temporary workspace (--scratch)"
    )
    if report == temp or report.is_relative_to(temp) or temp.is_relative_to(report):
        raise ValueError("Report and temporary workspace must not overlap")
    return report, temp


def resolve_safe_paths(root, out, scratch):
    """Make default scratch a sibling of the report, never source-relative.

    A relative output is resolved against the current directory, as requested
    by the caller. When that directory happens to be inside source_root,
    fail closed with concrete paths instead of silently moving the report.
    """
    root, out = Path(root).resolve(), Path(out).resolve()
    if out == root or out.is_relative_to(root):
        raise ValueError(
            f"Report path is inside source data root: {out}. "
            f"Source root: {root}. Set --out to a location OUTSIDE the source "
            r'directory, e.g. "D:\AStockAuditReports\audit.json".'
        )
    if scratch is None:
        scratch = out.parent / "_union_scratch"
    scratch = Path(scratch).resolve()
    if scratch == root or scratch.is_relative_to(root):
        raise ValueError(
            f"Scratch path is inside source data root: {scratch}. "
            f"Source root: {root}. Set --scratch to a directory OUTSIDE the "
            r'source, e.g. "D:\AStockAuditScratch".'
        )
    return root, out, scratch


def run(root, out, scratch, years, periods, batch_size, resume, universe="all",
        from_date=None, to_date=None, progress=False):
    root, out, scratch = resolve_safe_paths(root, out, scratch)
    if from_date is not None or to_date is not None:
        if len(years)!=1:
            raise ValueError("Bounded --from-date/--to-date audits require exactly one --years value")
        parse_day_range(years[0],from_date,to_date)
    if not (root/"HikyuuData").is_dir() or not (root/"AllCycleAStockData").is_dir():
        raise ValueError("Both HikyuuData and AllCycleAStockData are required")
    if out.exists():
        if not resume:
            raise ValueError("Report exists; use --resume only for the same interrupted audit")
        report = json.loads(out.read_text(encoding="utf-8"))
        if report.get("format") != "AStockDataTools H5-Parquet local coverage/difference report v1":
            raise ValueError("Cannot resume a report from another tool/version")
        if report.get("requested_years") != years or report.get("requested_periods") != periods:
            raise ValueError("Resume request years/periods must match the saved plan")
        if report.get("universe_mode", "all") != universe:
            raise ValueError("Resume universe mode must match the saved plan")
        if (report.get("requested_from_date") != from_date
                or report.get("requested_to_date") != to_date):
            raise ValueError("Resume date window must match the saved plan")
    else:
        report = {
            "format": "AStockDataTools H5-Parquet local coverage/difference report v1",
            "status": "partial",
            "requested_years": years, "requested_periods": periods,
            "universe_mode": universe,
            "requested_from_date": from_date, "requested_to_date": to_date,
            "security_master_certified": False,
            "unit_hypotheses": {
                "H5_prices": "int/1000",
                "H5_amount": "int*1000",
                "H5_day_volume": "int*100",
                "H5_minute_volume": "int",
                "Parquet_5min_bar_time": "start+5min -> H5 end",
                "Parquet_1min_0930": "special opening candidate, not proven missing"
            },
            "unverified_normalizations": True,
            "sources_modified": False,
            "not_covered_periods": ["15min", "30min", "60min", "week", "month", "复权因子"],
            "data_absence_validity": "Metadata-only Parquet coverage is a candidate, not an exact stock/bar set difference",
            "eligible_for_automatic_union": False,
            "v7_benchmark_eligible": False,
            "results": {}
        }
    scratch.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    for period in periods:
        for year in years:
            key = f"{period}/{year}"
            if key in report["results"] and report["results"][key].get("scan_complete"):
                print("SKIP completed", key, flush=True)
                continue
            print("AUDIT", key, "(bounded memory, no raw OHLCV in report)", flush=True)
            result = reconcile_section(root, scratch, period, year, batch_size,
                                       universe,from_date,to_date,progress)
            report["results"][key] = result
            completed = sum(bool(r.get("scan_complete")) for r in report["results"].values())
            report["status"] = "complete" if completed == len(years)*len(periods) else "partial"
            tmp = out.with_name(out.name+".tmp")
            tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
            tmp.replace(out)
            print(
                key, "H5", result["h5_rows"], "Parquet", result["pq_rows"],
                "both", result["matched_keys"], "H5-only", result["h5_only_rows"],
                "PQ-only", result["pq_only_rows"],
                "different", result["value_mismatch_rows"],
                "scan_complete", result["scan_complete"], flush=True
            )
    out.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--years", nargs="+", type=int, default=list(range(2011, 2027)))
    ap.add_argument("--periods", nargs="+", choices=PERIODS, default=list(PERIODS))
    ap.add_argument("--out", type=Path, default=None,
                    help="Report path within H5ParquetReconciler, default reports/h5-parquet-audit.json; relative to module, not CWD")
    ap.add_argument("--scratch", type=Path, default=None,
                    help="Temporary files inside H5ParquetReconciler, default work/_union_scratch")
    ap.add_argument("--batch-size", type=int, default=8192)
    ap.add_argument("--from-date", type=str, default=None, help="Inclusive YYYY-MM-DD, bounded scan")
    ap.add_argument("--to-date", type=str, default=None, help="Inclusive YYYY-MM-DD, bounded scan")
    ap.add_argument("--allow-full-year-minute", action="store_true",
                    help="Opt-in to slow, large temp SQLite full-year 5min/1min scans")
    ap.add_argument("--universe", choices=("all", "a-share-candidate"),
                    default="all",
                    help="all preserves legacy counts; a-share-candidate excludes obvious indices/B shares and pre-2022 BJ retrospective records")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--read-only", required=True, action="store_true")
    options = ap.parse_args(argv)
    if len(set(options.years)) != len(options.years) or any(y < 2000 or y > 2030 for y in options.years):
        ap.error("years must be distinct and between 2000-2030")
    if len(set(options.periods)) != len(options.periods) or not 512 <= options.batch_size <= 65536:
        ap.error("periods must be distinct, batch size in 512..65536")
    if any(p in options.periods for p in ("1min","5min")) and not (
        options.from_date or options.to_date or options.allow_full_year_minute):
        ap.error("Full-year minute scan is expensive. Specify --years YYYY "
                 "--from-date YYYY-MM-DD --to-date YYYY-MM-DD, "
                 "or explicitly --allow-full-year-minute")
    try:
        output, workspace = resolve_module_artifact_paths(options.out, options.scratch)
        report = run(
            options.root, output, workspace, sorted(options.years),
            options.periods, options.batch_size, options.resume, options.universe,
            options.from_date, options.to_date, True
        )
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    print("Saved", output, "Status:", report["status"], "(original source files unchanged)")


if __name__ == "__main__":
    main()
