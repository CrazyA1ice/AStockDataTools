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
from collections import Counter
from datetime import datetime, timedelta, timezone
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
    return db


def update_bounds(stats, origin, low, high):
    lk, hk = origin+"_earliest", origin+"_latest"
    if stats.get(lk) is None or low < stats[lk]:
        stats[lk] = low
    if stats.get(hk) is None or high > stats[hk]:
        stats[hk] = high


def store_h5(db, root, period, year, stats):
    import h5py

    total = 0
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
            for symbol in group.keys():
                if not re.fullmatch(market.upper() + r"\d{6}", symbol):
                    continue
                ds = group.get(symbol)
                if not isinstance(ds, h5py.Dataset) or not set(H5_FIELDS).issubset(ds.dtype.names or ()):
                    stats["h5_schema_errors"] += 1
                    continue
                left, right = h5_year_slice(ds, year)
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


def pq_metadata_only(paths, stats):
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


def check_batch(db, rows, stats, period):
    if not rows:
        return
    db.execute("DELETE FROM p")
    db.executemany("INSERT INTO p VALUES(?,?,?,?,?,?,?,?)", rows)
    ndup = db.execute(
        "SELECT sum(n-1) FROM (SELECT count(*) AS n FROM p GROUP BY s,t HAVING n>1)"
    ).fetchone()[0]
    stats["pq_duplicate_keys_within_batch"] += int(ndup or 0)
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
                count_difference(stats, "pq_only", sym, t)
                example(stats, "pq_only", sym, t)
            continue
        stats["matched_keys"] += 1
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
            count_difference(stats, category, sym, t)
            if any(x in differing for x in ("open", "high", "low", "close")):
                stats["price_mismatch_rows"] += 1
            if any(x in differing for x in ("volume", "amount")):
                stats["quantity_mismatch_rows"] += 1
            example(stats, category, sym, t, differing)
    db.execute("UPDATE h SET seen=1 WHERE (s,t) IN (SELECT s,t FROM p)")
    db.commit()


def scan_parquet(db, paths, period, year, stats, batch_size):
    import pyarrow.parquet as pq

    for file in paths:
        try:
            pf = pq.ParquetFile(str(file))
            if not set(NEEDED).issubset(pf.schema_arrow.names):
                stats["schema_errors"] += 1
                continue
            for batch in pf.iter_batches(batch_size=batch_size, columns=list(NEEDED), use_threads=True):
                times = batch.column(0).to_pylist()
                symbols = batch.column(1).to_pylist()
                cols = [batch.column(i).to_pylist() for i in range(2, 8)]
                selected = []
                for i, (time, raw) in enumerate(zip(times, symbols)):
                    stats["pq_rows"] += 1
                    sym = symbol_id(raw)
                    if sym is None:
                        stats["unknown_pq_symbols"] += 1
                        continue
                    try:
                        t = pq_stamp(time, period)
                        if t // 100000000 != year:
                            stats["pq_rows_outside_filename_year"] += 1
                            continue
                        vals = [float(col[i]) for col in cols]
                        if not all(math.isfinite(v) for v in vals):
                            stats["nonfinite_parquet_rows"] += 1
                            continue
                    except (TypeError, ValueError, OverflowError, OSError):
                        stats["timestamp_or_value_errors"] += 1
                        continue
                    selected.append((sym, t, *vals))
                    update_bounds(stats, "pq", t, t)
                check_batch(db, selected, stats, period)
        except (OSError, ValueError, RuntimeError, TypeError) as exc:
            stats["parquet_file_read_errors"] += 1
            example(stats, "scan_error", file.name, 0, [type(exc).__name__])


def h5_remaining(db, stats):
    for sym, t in db.execute("SELECT s,t FROM h WHERE seen=0 ORDER BY t"):
        if t % 10000 == 1300 and stats["period"] in ("1min", "5min"):
            stats["h5_1300_noon_label_suspect_rows"] += 1
        stats["h5_only_rows"] += 1
        count_difference(stats, "h5_only", sym, t)
        example(stats, "h5_only", sym, t)


def reconcile_section(root, scratch, period, year, batch_size):
    stats = Counter()
    stats.update({
        "period": period, "year": year,
        "h5_rows": 0, "pq_rows": 0, "matched_keys": 0,
        "h5_only_rows": 0, "pq_only_rows": 0,
        "pq_0930_extra_candidate_rows": 0,
        "value_mismatch_rows": 0, "opening_candidate_mismatch_rows": 0,
        "price_mismatch_rows": 0, "quantity_mismatch_rows": 0
    })
    paths = year_files(root, period, year)
    stats["parquet_year_files"] = len(paths)
    with tempfile.TemporaryDirectory(prefix="h5pq_", dir=str(scratch)) as temporary:
        db = db_open(Path(temporary)/"join.sqlite")
        try:
            count = store_h5(db, root, period, year, stats)
            if not count:
                if paths:
                    pq_metadata_only(paths, stats)
            elif paths:
                scan_parquet(db, paths, period, year, stats, batch_size)
            h5_remaining(db, stats)
        finally:
            db.close()
    issues = [
        k for k in (
            "h5_schema_errors", "schema_errors", "parquet_file_read_errors",
            "timestamp_or_value_errors", "nonfinite_parquet_rows",
            "unknown_pq_symbols", "pq_rows_outside_filename_year",
            "h5_duplicate_keys", "timestamp_errors",
            "pq_duplicate_keys_within_batch", "missing_h5_market_files"
        ) if stats[k]
    ]
    stats["scan_complete"] = not issues
    stats["issues"] = issues
    stats["by_day"] = dict(sorted(stats.get("by_day", {}).items()))
    affected = stats.get("by_symbol", {})
    stats["affected_symbols"] = len(affected)
    stats["by_symbol_top100"] = dict(
        sorted(affected.items(), key=lambda item: (-sum(item[1].values()), item[0]))[:100]
    )
    stats.pop("by_symbol", None)
    stats["duplicate_keys_across_batches_not_exhaustively_checked"] = True
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


def run(root, out, scratch, years, periods, batch_size, resume):
    root, out, scratch = resolve_safe_paths(root, out, scratch)
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
    else:
        report = {
            "format": "AStockDataTools H5-Parquet local coverage/difference report v1",
            "status": "partial",
            "requested_years": years, "requested_periods": periods,
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
            result = reconcile_section(root, scratch, period, year, batch_size)
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
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--scratch", type=Path, default=None,
                    help="Temporary SQLite directory; defaults to _union_scratch beside --out (never under source)")
    ap.add_argument("--batch-size", type=int, default=8192)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--read-only", required=True, action="store_true")
    options = ap.parse_args(argv)
    if len(set(options.years)) != len(options.years) or any(y < 2000 or y > 2030 for y in options.years):
        ap.error("years must be distinct and between 2000-2030")
    if len(set(options.periods)) != len(options.periods) or not 512 <= options.batch_size <= 65536:
        ap.error("periods must be distinct, batch size in 512..65536")
    try:
        report = run(
            options.root, options.out, options.scratch, sorted(options.years),
            options.periods, options.batch_size, options.resume
        )
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    print("Saved", options.out, "Status:", report["status"], "(original source files unchanged)")


if __name__ == "__main__":
    main()
