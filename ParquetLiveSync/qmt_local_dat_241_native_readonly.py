#!/usr/bin/env python3
"""Read ONLY QMT main terminal's already-downloaded native 1m .DAT via xtdata.

No xtdatacenter.init, no MiniQMT launch, no subscriptions, no QMT downloads,
no .DAT binary guessing, no output file and no production Parquet/H5 writes.
Never read tick period 0. Explicit 'data_dir' = exact QMT main DATADIR.
For the original SHA-pinned three-stock Oct 14-16 QMT reference, compare after
native extraction, NOT used to synthesize/modify native candidate. File hashes
before/after are checked for any QMT DAT mutation during this probe.
"""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta,timezone
import hashlib
import json
import math
from pathlib import Path

import pyarrow.parquet as pq
import local_layout as L
import qmt_1m_pipeline as P
import qmt_eltdx_1m_probe as X
import qmt_eltdx_auction_241_probe as A
import qmt_eltdx_opening_tick_alignment as J

FORMAT="qmt_main_native_xtdata_local_1m_to_sha241_readonly_v1"
CODES=("600000.SH","000001.SZ","688001.SH")
TARGET_DAYS=(date(2026,10,14),date(2026,10,15),date(2026,10,16),date(2026,11,13))
CN=timezone(timedelta(hours=8))
FIELDS=("open","high","low","close","volume","amount")
MAX_ROWS_PER_STOCK=14000


def path_for(root,code):
    number,market=code.split(".")
    if code not in CODES:
        raise ValueError("Only original 3 SHA-backed anchor stocks")
    return Path(root)/market/"60"/(number+".DAT")


def fingerprint(path):
    path=Path(path)
    if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink():
        raise ValueError("Redirected QMT source path")
    stat=path.stat()
    if not path.is_file() or stat.st_size<=0 or stat.st_size>128*1024*1024:
        raise ValueError("Unexpected QMT native 1m file size")
    sha=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            sha.update(block)
    if (path.stat().st_size!=stat.st_size
        or path.stat().st_mtime_ns!=stat.st_mtime_ns):
        raise ValueError("QMT .DAT changed during SHA scan")
    return {"sha256":sha.hexdigest(),"bytes":stat.st_size,
            "modified_ns":stat.st_mtime_ns}


def parse_timestamp(raw):
    if isinstance(raw,datetime):
        return raw.replace(tzinfo=CN) if raw.tzinfo is None else raw.astimezone(CN)
    s=str(raw).strip()
    try:
        if s.isdigit():
            if len(s)==13:
                return datetime.fromtimestamp(int(s)/1000,CN)
            if len(s)==10:
                return datetime.fromtimestamp(int(s),CN)
            if len(s)==14 and s.startswith("20"):
                return datetime.strptime(s,"%Y%m%d%H%M%S").replace(tzinfo=CN)
            if len(s)==12 and s.startswith("20"):
                return datetime.strptime(s,"%Y%m%d%H%M").replace(tzinfo=CN)
        parsed=datetime.fromisoformat(s)
        return parsed.replace(tzinfo=CN) if parsed.tzinfo is None else parsed.astimezone(CN)
    except (ValueError,OverflowError,OSError) as exc:
        raise ValueError("Unsupported QMT data frame timestamp") from exc


def make_bar(stamp,values):
    dt=parse_timestamp(stamp)
    row={"ts":int(dt.timestamp()*1000)}
    row.update({k:float(values[k]) for k in FIELDS})
    if (not all(math.isfinite(row[k]) for k in FIELDS)
        or any(row[k]<=0 for k in FIELDS[:4])
        or row["volume"]<0 or row["amount"]<0
        or row["high"]<max(row["open"],row["low"],row["close"])-.0002
        or row["low"]>min(row["open"],row["high"],row["close"])+.0002):
        raise ValueError("Invalid QMT native bar OHLCVA")
    return row


def normalize(loaded,code):
    """Support canonical xtdata field->DataFrame and code->DataFrame shapes."""
    if not isinstance(loaded,dict) or not loaded:
        return [],"EMPTY_OR_UNSUPPORTED_SHAPE"
    rows=[]
    if all(k in loaded for k in FIELDS):
        # xtdata.get_local_data -> {field: pandas.DataFrame(index=stock, cols=time)}
        fields=loaded
        missing=[]
        for f in FIELDS:
            frame=fields[f]
            if not hasattr(frame,"loc") or code not in frame.index:
                missing.append(f)
        if missing:
            return [],"FIELD_DF_MISSING_STOCK_OR_FRAME"
        index=list(fields["open"].columns)
        if any(list(fields[k].columns)!=index for k in FIELDS):
            raise ValueError("Native 1m field time indexes are inconsistent")
        for column in index:
            values={k:fields[k].loc[code,column] for k in FIELDS}
            # 'time' DataFrame sometimes has the true epoch-ms as cell.
            stamp=(fields["time"].loc[code,column]
                   if "time" in fields and hasattr(fields["time"],"loc")
                   and code in fields["time"].index else column)
            rows.append(make_bar(stamp,values))
        mode="XT_FIELD_BY_STOCK_TIMES"
    elif code in loaded and hasattr(loaded[code],"columns"):
        # Some compatible SDKs -> {stock: DataFrame(index=time, columns=fields)}
        frame=loaded[code]
        if any(k not in frame.columns for k in FIELDS):
            raise ValueError("Native per-stock DataFrame missing OHLCVA")
        for idx,record in frame.iterrows():
            stamp=record["time"] if "time" in frame.columns else idx
            rows.append(make_bar(stamp,record))
        mode="XT_STOCK_FRAME"
    else:
        return [],"UNKNOWN_DATA_SHAPE"
    if len(rows)>MAX_ROWS_PER_STOCK:
        raise ValueError("Unexpectedly many native 1m bars for bounded window")
    rows.sort(key=lambda r:r["ts"])
    if len({r["ts"] for r in rows})!=len(rows):
        raise ValueError("Duplicate QMT native source minute timestamps")
    return rows,mode


def inspect_day(bars,day,qmt=None):
    data=[r for r in bars if datetime.fromtimestamp(r["ts"]/1000,CN).date()==day]
    ticks=[datetime.fromtimestamp(r["ts"]/1000,CN) for r in data]
    labels=[d.strftime("%H:%M") for d in ticks]
    stat={
        "day":str(day),"bars":len(data),"first":labels[0] if labels else None,
        "last":labels[-1] if labels else None,
        "first_five_labels":labels[:5],
        "has_0930_auction_label":"09:30" in labels,
        "has_0931_regular_label":"09:31" in labels,
        "format_class":(
            "QMT_241_LABELS" if len(data)==241 and "09:30" in labels and "09:31" in labels else
            "TDX_STYLE_240_LABELS" if len(data)==240 and "09:30" not in labels and "09:31" in labels else
            "DAY_NOT_IN_LOCAL_DAT" if not data else "OTHER_GRID"),
        "all_timestamp_minute_unique":len(set(labels))==len(labels),
        "source_values_not_printed":True,
        "production_merge_authorized":False}
    if qmt is not None and day<=date(2026,10,16):
        original=A.day_rows(qmt,day)
        if len(original)!=241:
            raise ValueError("SHA-pinned QMT private reference missing a 241 day")
        if stat["format_class"]=="QMT_241_LABELS":
            bytime={r["ts"]:r for r in data}
            matches={k:0 for k in FIELDS}
            for reference in original:
                if reference["ts"] not in bytime:
                    continue
                native=bytime[reference["ts"]]
                for k in FIELDS:
                    matches[k]+=int(J.strict_fit(native[k],reference[k],k))
            stat["reference_validation"]={
                "identical_time_labels_to_private_qmt":
                    [r["ts"] for r in data]==[r["ts"] for r in original],
                "strict_field_matches":matches,
                "baseline_bars":len(original),
                "source_is_original_qmt_vendor_not_external_independent":True}
        else:
            stat["reference_validation"]={
                "status":"NOT_A_SEPARATE_241_BAR_CANDIDATE",
                "baseline_bars":len(original)}
    return stat


def verify_reference(code):
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    q,sha=X.read_qmt_source(stage,code)
    if not q or sha.startswith("MISSING"):
        raise ValueError("Missing SHA-pinned original QMT 241 reference for "+code)
    return q,sha


def read_xtdata(code,root,reader=None):
    if reader is None:
        try:
            from xtquant import xtdata
        except (ImportError, OSError) as exc:
            return [],"XTQUANT_NOT_INSTALLED_OR_DLL_UNAVAILABLE",type(exc).__name__
        reader=xtdata.get_local_data
    try:
        # Only local read. No download/subscription/xtdatacenter init.
        response=reader(
            field_list=list(FIELDS)+["time"],stock_list=[code],
            period="1m",start_time="20261014000000",end_time="20261113235959",
            count=-1,dividend_type="none",fill_data=False,
            data_dir=str(root))
    except Exception as exc:
        return [],"XT_LOCAL_READ_UNAVAILABLE",type(exc).__name__+":"+str(exc)[:160]
    rows,mode=normalize(response,code)
    return rows,mode,None


def run(*,root,codes=CODES,days=TARGET_DAYS,reader=None,reference_loader=verify_reference,logger=print):
    root=Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("QMT datadir is missing or redirected")
    if (not codes or len(codes)>3 or len(set(codes))!=len(codes)
        or any(c not in CODES for c in codes)):
        raise ValueError("Only original 3 stock anchors")
    if (not days or len(days)>len(TARGET_DAYS)
        or any(d not in TARGET_DAYS for d in days) or len(set(days))!=len(days)):
        raise ValueError("Only original October and November reference days")
    outcomes=Counter()
    details=[]
    for code in codes:
        source=path_for(root,code)
        old=fingerprint(source)
        # Reference is verified before the candidate is scored; its values
        # are never passed as inputs to the QMT native extractor.
        ref,ref_sha=reference_loader(code)
        bars,mode,error=read_xtdata(code,root,reader=reader)
        new=fingerprint(source)
        if old!=new:
            raise ValueError("QMT native one-minute DAT mutated during read")
        if error:
            outcome={"stock":code,"status":mode,"reason":error,
                     "original_dat_sha256":old["sha256"],
                     "market_files_modified":False,"production_merge_authorized":False}
        else:
            checks=[inspect_day(bars,d,ref) for d in days]
            counts=Counter(r["format_class"] for r in checks)
            outcome={
                "stock":code,"status":"LOCAL_READ_COMPLETED" if bars else mode,
                "read_shape":mode,
                "native_bar_count":len(bars),
                "native_date_range":[str(datetime.fromtimestamp(bars[0]["ts"]/1000,CN).date()),
                                     str(datetime.fromtimestamp(bars[-1]["ts"]/1000,CN).date())] if bars else None,
                "days":checks,"day_grid_counts":dict(counts),
                "original_dat_sha256":old["sha256"],
                "original_qmt_reference_sha256":ref_sha,
                "source_is_native_QMT_vendor":True,
                "market_files_modified":False,"production_merge_authorized":False}
        details.append(outcome)
        outcomes[outcome["status"]]+=1
        logger("QMT_NATIVE_1M_STOCK="+json.dumps(outcome,ensure_ascii=False,sort_keys=True))
    summary={"format":FORMAT,"files_checked":len(codes),
             "statuses":dict(outcomes),"no_download_calls":True,
             "no_tick_folder_read":True,
             "market_files_modified":False,"production_merge_authorized":False}
    logger("QMT_NATIVE_1M_SUMMARY="+json.dumps(summary,ensure_ascii=False,sort_keys=True))
    return summary


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root",default=r"D:\software\JHQMT\datadir")
    args=ap.parse_args()
    run(root=args.root)
