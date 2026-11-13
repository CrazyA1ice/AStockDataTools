#!/usr/bin/env python3
"""Real eltdx Rust 7709 OHLCVA minute probe against a SHA-pinned QMT snapshot.

Educational/non-commercial source compatibility research only (eltdx license).
Read-only production, no modifications to licensed monthly Parquet/H5.
Unlike historical intraday trend APIs, bars.get(period="1m") gives actual
OHLCVA candles. Pages are bounded to the precise historical window. This
probe can also run on an empty CI machine using --remote-only (no QMT).
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq

import local_layout as L
import qmt_1m_pipeline as P
import qmt_tdx_1m_depth as D

FORMAT = "eltdx_real_1min_ohlcva_vs_qmt_20261113_v1"
START = date(2026, 10, 14)
END = date(2026, 11, 12)
ANCHORS = ("600000.SH", "000001.SZ", "688001.SH")
# eltdx's own 2026 server pool, rather than our previous pytdx legacy endpoints.
HOSTS = ("116.205.183.150:7709", "116.205.171.132:7709",
         "111.230.186.52:7709", "129.204.230.128:7709",
         "116.205.163.254:7709", "110.41.2.72:7709",
         "111.229.247.189:7709", "43.139.95.83:7709")
PAGE_SIZE = 800
WORK = P.BASE / "eltdx_1m_probe"


def eltdx_code(code):
    name = L.normal_symbol(code)
    return ("sh" if name.startswith("SH") else "sz") + name[-6:]


def raw_val(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def canon_bar(bar, code):
    """Use eltdx's unadjusted original bar and raw wire volume for diagnostics.

    Stock volume_lots is volume_wire_value / 100 in eltdx; the wire value is
    preserved here. Neither quantity is implicitly mapped to QMT units.
    """
    stamp = raw_val(bar, "time")
    if isinstance(stamp, datetime):
        dt = stamp if stamp.tzinfo else stamp.replace(tzinfo=P.CN)
    else:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=P.CN)
    dt = dt.astimezone(P.CN)
    volume = raw_val(bar, "volume_wire_value")
    if volume is None:
        lots = raw_val(bar, "volume_lots")
        if lots is None:
            raise ValueError("eltdx bar has no wire or lots volume")
        volume = float(lots) * 100
    result = {
        "ts": int(dt.timestamp() * 1000),
        "symbol": L.normal_symbol(code),
        **{k: float(raw_val(bar, k)) for k in ("open", "high", "low", "close")},
        "volume": float(volume),
        "amount": float(raw_val(bar, "amount"))
    }
    vals = result
    if (not all(math.isfinite(vals[k]) for k in D.FIELDS)
        or min(vals[k] for k in D.OHLC) <= 0
        or vals["high"] < max(vals["open"], vals["close"]) - 0.01
        or vals["low"] > min(vals["open"], vals["close"]) + 0.01
        or vals["volume"] < 0 or vals["amount"] < 0):
        raise ValueError("invalid one-minute OHLCVA returned by eltdx")
    return result


def page_rows(series, code):
    if not hasattr(series, "bars") or not hasattr(series, "count"):
        raise ValueError("eltdx returned non-KlineSeries payload")
    raw = list(series.bars)
    if len(raw) != series.count or len(raw) > PAGE_SIZE:
        raise ValueError("eltdx KlineSeries count/page mismatch")
    rows = [canon_bar(x, code) for x in raw]
    if len({x["ts"] for x in rows}) != len(rows):
        raise ValueError("duplicate timestamps within an eltdx page")
    return sorted(rows, key=lambda x: x["ts"])


def fetch_history(client, code, start=START, end=END, max_pages=16):
    """Page until older than requested start, not until server history exhausted."""
    if start > end:
        raise ValueError("invalid historical date interval")
    got = {}
    pages = 0
    earliest = None
    latest = None
    page_lengths = []
    # Offset advances by number actually returned (eltdx's own semantics).
    offset = 0
    while pages < max_pages:
        series = client.bars.get(eltdx_code(code), period="1m", start=offset,
                                 count=PAGE_SIZE, adjust=None, bar_time="start",
                                 include_raw=False)
        bars = page_rows(series, code)
        pages += 1
        page_lengths.append(len(bars))
        if not bars:
            break
        first = datetime.fromtimestamp(bars[0]["ts"]/1000,P.CN).date()
        last = datetime.fromtimestamp(bars[-1]["ts"]/1000,P.CN).date()
        earliest = first if earliest is None else min(earliest, first)
        latest = last if latest is None else max(latest, last)
        for bar in bars:
            key = bar["ts"]
            if key in got:
                prev = got[key]
                if any(not math.isclose(prev[field],bar[field],rel_tol=1e-10,abs_tol=1e-7)
                       for field in D.FIELDS):
                    raise ValueError("conflicting eltdx page overlap")
            else:
                got[key] = bar
        if first < start:
            break
        offset += len(bars)
    if not got:
        raise ValueError("eltdx source returned no actual 1-minute Kline")
    if earliest is None or earliest > start:
        raise ValueError(f"eltdx 1-minute history too shallow for {start}: earliest={earliest} pages={pages}")
    trimmed = [v for t,v in sorted(got.items())
               if start <= datetime.fromtimestamp(t/1000,P.CN).date() <= end]
    if not trimmed:
        raise ValueError("eltdx returned no bars in QMT's target dates")
    byday=Counter(datetime.fromtimestamp(x["ts"]/1000,P.CN).date().isoformat() for x in trimmed)
    # At least the 3 existing anchors should have several complete market days.
    healthy=sum(n>=200 for n in byday.values())
    complete_days=sum(n>=235 for n in byday.values())
    if healthy < 3:
        raise ValueError("eltdx returned fewer than three dense trading days")
    return trimmed, {"host_pages":pages,"page_lengths":page_lengths,
                     "source_earliest_day":str(earliest),"source_latest_day":str(latest),
                     "target_day_counts":dict(sorted(byday.items())),
                     "dense_days":healthy,"complete_minute_days":complete_days,
                     "complete_22_day_window":complete_days==22,
                     "target_rows":len(trimmed),
                     "bar_time":"start","adjust":"none",
                     "volume_source_field":"volume_wire_value",
                     "source":"eltdx Rust 7709 real 1m Kline OHLCVA"}


def read_qmt_source(stage, code):
    path=stage/"source_parquet"/(code.replace(".","_")+".parquet")
    receipt=stage/"receipts"/(code.replace(".","_")+".json")
    if (not receipt.is_file() or not path.is_file() or receipt.is_symlink()
            or path.is_symlink()):
        return None,"MISSING_QMT_ACCEPTED_PRIVATE_RECEIPT"
    doc=json.loads(receipt.read_bytes())
    if (doc.get("symbol")!=code or doc.get("status")!="private_ohlcva_source_verified"
            or L.hash_file(path)!=doc.get("sha256")):
        raise ValueError("QMT private source SHA/receipt verification failure")
    table=pq.read_table(path)
    if table.schema!=P.PRIVATE_SCHEMA or table.num_rows!=doc["rows"]:
        raise ValueError("QMT original Arrow schema/row count mismatch")
    return table.to_pylist(), doc["sha256"]


def compare_rows(qmt, tdx):
    qb=defaultdict(list); tb=defaultdict(list)
    for row in qmt:
        qb[datetime.fromtimestamp(row["ts"]/1000,P.CN).date().isoformat()].append(row)
    for row in tdx:
        tb[datetime.fromtimestamp(row["ts"]/1000,P.CN).date().isoformat()].append(row)
    return {day:D.score_day(qb.get(day,[]),tb.get(day,[]))
            for day in sorted(set(qb)|set(tb))}


def save_private(folder,code,tdx_rows,meta,compare):
    folder=Path(folder)
    path=folder/"source_parquet"/(code.replace(".","_")+".parquet")
    receipt=folder/"receipts"/(code.replace(".","_")+".json")
    path.parent.mkdir(parents=True,exist_ok=True)
    receipt.parent.mkdir(parents=True,exist_ok=True)
    if (path.is_symlink() or receipt.is_symlink()
            or receipt.exists()):
        raise ValueError("eltdx source receipt exists or redirected")
    table=pa.Table.from_pylist(tdx_rows,schema=P.PRIVATE_SCHEMA)
    if path.exists():
        prior=pq.read_table(path)
        if not prior.equals(table,check_metadata=False):
            raise ValueError("Existing orphan eltdx private data differs")
    else:
        temp=path.with_suffix(".parquet.part")
        if temp.is_symlink():
            raise ValueError("eltdx temporary source link rejected")
        pq.write_table(table,temp,compression="zstd")
        if not pq.read_table(temp).equals(table,check_metadata=False):
            raise ValueError("eltdx Parquet roundtrip mismatch")
        D.R.retry_private_atomic(temp,path)
    evidence={"format":FORMAT,"stock":code,"source_sha256":L.hash_file(path),
              "rows":len(tdx_rows),"meta":meta,"day_comparison":compare,
              "market_files_modified":False,"production_merge_authorized":False}
    P.safe_save(receipt,P.canonical(evidence))
    return evidence


def connect_host(host, factory=None, timeout=3.5):
    if factory is not None:
        return factory(host)
    from eltdx import TdxClient
    return TdxClient(hosts=[host],timeout=timeout,pool_size=1,server_count=1,
                     heartbeat_interval=None,probe_hosts=False)


def verified_cache(folder, code, stage, remote_only):
    """Restart from an exact SHA-bound private eltdx snapshot, never re-download."""
    folder=Path(folder)
    receipt=folder/"receipts"/(code.replace(".","_")+".json")
    path=folder/"source_parquet"/(code.replace(".","_")+".parquet")
    if not receipt.exists():
        return None
    if receipt.is_symlink() or path.is_symlink() or not path.is_file():
        raise ValueError("eltdx cached evidence redirected or missing")
    evidence=json.loads(receipt.read_bytes())
    if (evidence.get("format")!=FORMAT or evidence.get("stock")!=code
            or evidence.get("source_sha256")!=L.hash_file(path)):
        raise ValueError("eltdx existing private evidence failed SHA/identity check")
    pf=pq.ParquetFile(path)
    try:
        if pf.metadata.num_rows!=evidence.get("rows") or pf.schema_arrow!=P.PRIVATE_SCHEMA:
            raise ValueError("eltdx cached Parquet schema/row count changed")
    finally:
        pf.close()
    previous=evidence.get("meta",{}).get("qmt_sha256")
    if not remote_only:
        _,current=read_qmt_source(stage,code)
        if current!=previous:
            raise ValueError("QMT source SHA changed since eltdx crosscheck; avoid stale reuse")
    return evidence


def probe(start=START,end=END,symbols=ANCHORS,hosts=HOSTS,*,max_hosts=6,
          max_pages=16,remote_only=False,work=WORK,client_factory=None,log=print):
    if end>=datetime.now(P.CN).date():
        raise ValueError("Only already-closed trading dates can be audited")
    folder=Path(work)/f"{start:%Y%m%d}_{end:%Y%m%d}"
    stage=P.BASE/f"{start:%Y%m%d}_{end:%Y%m%d}"
    state={"format":FORMAT,"start":str(start),"end":str(end),
           "sdk":"eltdx/Rust/7709","production_merge_authorized":False,
           "market_files_modified":False,"stocks":{},
           "qmt_comparison_enabled":not remote_only}
    for code in symbols:
        code = D.P.normalize_code(code)
        result={"status":"SOURCE_UNAVAILABLE","attempts":[]}
        log("ELTDX_SOURCE_START "+code)
        try:
            previous=verified_cache(folder,code,stage,remote_only)
            if previous is not None:
                meta=previous["meta"]
                result={"status":"REAL_1MIN_AVAILABLE_AND_PRIVATE_STAGED",
                        "cached":True,"source_bars":previous["rows"],
                        "source_dense_days":meta["dense_days"],
                        "complete_22_day_window":meta.get("complete_22_day_window",False),
                        "endpoint":meta["endpoint"],
                        "source_sha256":previous["source_sha256"],
                        "comparison_days":len(previous["day_comparison"]),
                        "matching_minute_days":sum(
                            item.get("status")=="MATCHED_1MIN_OHLCVA"
                            for item in previous["day_comparison"].values()),
                        "qmt_comparison_available":bool(meta.get("qmt_sha256"))}
                state["stocks"][code]=result
                log("ELTDX_SOURCE_CACHED "+json.dumps({"stock":code,**result},ensure_ascii=False))
                continue
        except Exception as exc:
            # A corrupted snapshot must not be silently replaced.
            result["status"]="PRIVATE_CACHE_REJECTED"
            result["attempts"].append(type(exc).__name__+": "+str(exc)[:180])
            state["stocks"][code]=result
            log("ELTDX_PRIVATE_CACHE_REJECT "+code+" "+result["attempts"][-1])
            continue
        for host in hosts[:max_hosts]:
            try:
                client=connect_host(host,client_factory)
                with client:
                    rows,meta=fetch_history(client,code,start,end,max_pages)
                meta["endpoint"]=host
                qmt_sha=None
                comparison={}
                if not remote_only:
                    qr,qmt_sha=read_qmt_source(stage,code)
                    if qr is not None:
                        comparison=compare_rows(qr,rows)
                    else:
                        comparison={"_status":qmt_sha}
                        qmt_sha=None
                saved=save_private(folder,code,rows,{**meta,"qmt_sha256":qmt_sha},comparison)
                stats=Counter(x["status"] for x in comparison.values() if isinstance(x,dict) and "status" in x)
                result={"status":"REAL_1MIN_AVAILABLE_AND_PRIVATE_STAGED",
                        "source_bars":len(rows),"source_dense_days":meta["dense_days"],
                        "complete_22_day_window":meta["complete_22_day_window"],
                        "endpoint":host,"source_sha256":saved["source_sha256"],
                        "comparison_days":len(comparison),
                        "matching_minute_days":stats.get("MATCHED_1MIN_OHLCVA",0),
                        "difference_days":stats.get("MINUTE_SOURCE_DIFFERENCE_REVIEW",0),
                        "time_grid_difference_days":stats.get("TDX_INCOMPLETE_OR_DIFFERENT_MINUTE_GRID",0),
                        "qmt_comparison_available":qmt_sha is not None}
                log("ELTDX_SOURCE_RESULT "+json.dumps({"stock":code,**result},sort_keys=True,ensure_ascii=False))
                break
            except Exception as exc:
                issue=f"{host}: {type(exc).__name__}: {str(exc)[:200]}"
                result["attempts"].append(issue)
                log("ELTDX_ENDPOINT_REJECT "+code+" "+issue)
        state["stocks"][code]=result
    good=sum(x["status"]=="REAL_1MIN_AVAILABLE_AND_PRIVATE_STAGED"
             for x in state["stocks"].values())
    full=sum(x.get("complete_22_day_window",False) for x in state["stocks"].values())
    state["summary"]={"requested":len(symbols),"real_minute_success":good,
                      "complete_22_day_stocks":full,
                      "failed":len(symbols)-good,
                      "qmt_minute_compared_stocks":sum(x.get("qmt_comparison_available",False) for x in state["stocks"].values()),
                      "market_files_modified":False}
    folder.mkdir(parents=True,exist_ok=True)
    P.safe_save(folder/"latest_summary.json",P.canonical(state))
    log("ELTDX_DEEP_1MIN_SUMMARY="+json.dumps(state["summary"],sort_keys=True,ensure_ascii=False))
    return state


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start",type=date.fromisoformat,default=START)
    parser.add_argument("--end",type=date.fromisoformat,default=END)
    parser.add_argument("--symbols",default=",".join(ANCHORS))
    parser.add_argument("--remote-only",action="store_true")
    parser.add_argument("--max-hosts",type=int,default=6)
    parser.add_argument("--max-pages",type=int,default=16)
    args=parser.parse_args(argv)
    symbols=tuple(D.P.normalize_code(x.strip()) for x in args.symbols.split(","))
    if (args.start!=START or args.end!=END or not 1<=len(symbols)<=6 or
            not 1<=args.max_hosts<=len(HOSTS) or not 1<=args.max_pages<=35):
        parser.error("Only certified 2026-10-14..2026-11-12 sample window and bounded requests supported")
    result=probe(args.start,args.end,symbols,max_hosts=args.max_hosts,
                 max_pages=args.max_pages,remote_only=args.remote_only)
    return 0 if result["summary"]["complete_22_day_stocks"]>0 else 2


if __name__=="__main__":
    sys.exit(main())
