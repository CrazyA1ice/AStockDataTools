#!/usr/bin/env python3
"""2026-10-16/688001.SH research-only Hugging Face historical Level-2 probe.

Phase 1 (default): use Hugging Face repo metadata ONLY; 0 market-data bytes.
Phase 2 (--sample): authorized access only, remote Parquet *row-group pruning*
with strict compressed-column and row-group budgets; validate trade extrema
against original private SHA-bound QMT 241 + eltdx 240. Do not download 2GB
day files, do not write to market Parquet/H5, do not persist source payloads,
do not print token, prices, volumes or raw trade rows.

Dataset license is RESEARCH-USE-ONLY, not authorization for commercial or
production market-data backfill. A matching high is evidence not certification
of exchange tick completeness, trade time order, or exchange-supplied turnover.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
import math
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

FORMAT="qmt241_hf_gated_l2_688001_20261016_private_readonly_v1"
REPO="venvoo/china-a-share-l2-level2-limit-order-book-tick-data"
DAY="20261016"
CODE="688001.SH"
NEEDED=("逐笔成交.parquet","行情.parquet")
MAX_ROW_GROUPS_PER_STREAM=4
MAX_SELECTED_COMPRESSED_BYTES=48*1024*1024
MAX_ROWS_PER_STREAM=500000


def token():
    # Hugging Face CLI stores a secret locally. Never print its contents.
    value=os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
    if value:
        return value.strip()
    try:
        from huggingface_hub import get_token
        return get_token()
    except ImportError:
        return None


def report_access(fetch=None,logger=print):
    """Short Hugging Face API tree listing; works anonymously or with local token."""
    if fetch is None:
        fetch=_read_api
    cred=token()
    url=("https://huggingface.co/api/datasets/"+REPO+
         "/tree/main/"+DAY+"?recursive=false&expand=false")
    try:
        payload=fetch(url,cred)
        entries=json.loads(payload)
        if not isinstance(entries,list):
            raise ValueError("Unexpected Hugging Face tree response")
        present=sorted({x.get("path","").split("/")[-1] for x in entries
                        if isinstance(x,dict) and x.get("type")=="file"})
        found=sorted(set(present)&set(NEEDED))
        status=("TARGET_DAY_BOTH_STREAM_FILES_LISTED" if len(found)==2 else
                "TARGET_DAY_PARTIAL_STREAMS" if found else
                "TARGET_DAY_FILES_NOT_LISTED")
        result={"status":status,"target_day":DAY,"symbol":CODE,
                "streams_listed":found,"streams_missing":sorted(set(NEEDED)-set(found)),
                "credentials_present":bool(cred),
                "data_rows_downloaded":0,
                "source_license":"research-use-only",
                "production_merge_authorized":False}
    except urllib.error.HTTPError as err:
        result={"status":("HF_DATASET_ACCESS_REQUIRES_APPROVAL"
                          if err.code in (401,403) else "HF_METADATA_HTTP_ERROR"),
                "http_status":err.code,"target_day":DAY,
                "credentials_present":bool(cred),"data_rows_downloaded":0,
                "production_merge_authorized":False}
    except Exception as err:
        result={"status":"HF_METADATA_UNAVAILABLE",
                "error_type":type(err).__name__,"target_day":DAY,
                "credentials_present":bool(cred),"data_rows_downloaded":0,
                "production_merge_authorized":False}
    logger("HF_241_L2_ACCESS_PREFLIGHT="+json.dumps(result,ensure_ascii=False,sort_keys=True))
    return result


def _read_api(url,credential):
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme!="https" or parsed.hostname!="huggingface.co":
        raise ValueError("Hugging Face metadata endpoint only")
    headers={"Accept":"application/json","User-Agent":"qmt241-l2-research-probe"}
    if credential:
        headers["Authorization"]="Bearer "+credential
    req=urllib.request.Request(url,headers=headers)
    with urllib.request.urlopen(req,timeout=15) as r:
        final=urllib.parse.urlparse(r.geturl())
        if final.scheme!="https" or final.hostname!="huggingface.co":
            raise ValueError("Unapproved API redirect")
        blob=r.read(128*1024+1)
        if len(blob)>128*1024:
            raise ValueError("Oversized Hugging Face day listing")
        return blob.decode("utf-8")


def choose_groups(meta,columns,*,symbol=CODE):
    """Never read row group if min/max wind_code stats are missing."""
    if "wind_code" not in columns:
        raise ValueError("Parquet has no stock selector")
    i=columns.index("wind_code")
    out=[]
    for number in range(meta.num_row_groups):
        group=meta.row_group(number)
        column=group.column(i)
        stats=column.statistics
        if stats is None or not stats.has_min_max:
            raise ValueError("Missing trusted stock row-group min/max; refuse bulk fetch")
        low=stats.min.decode() if isinstance(stats.min,bytes) else str(stats.min)
        high=stats.max.decode() if isinstance(stats.max,bytes) else str(stats.max)
        if low<=symbol<=high:
            out.append(number)
    if len(out)>MAX_ROW_GROUPS_PER_STREAM:
        raise ValueError("Too many matching row groups for bounded remote study")
    return out


def compressed_budget(meta,indices,names,*,max_bytes=MAX_SELECTED_COMPRESSED_BYTES):
    """Validate conservative remote column compressed read footprint."""
    total=0
    all_cols=list(meta.schema.names)
    for row_i in indices:
        group=meta.row_group(row_i)
        if group.num_rows>MAX_ROWS_PER_STREAM:
            raise ValueError("Individual row group exceeds research row cap")
        for col_name in names:
            if col_name not in all_cols:
                raise ValueError("Missing expected vendor Level-2 column")
            size=group.column(all_cols.index(col_name)).total_compressed_size
            if size is None or size<0:
                raise ValueError("Unavailable column compressed size")
            total+=size
    if total>max_bytes:
        raise ValueError("Stock-column query exceeds bounded compressed budget")
    return total


def clock(raw):
    value=str(int(raw)).zfill(9)
    if len(value)!=9:
        raise ValueError("Invalid L2 HHMMSSmmm time")
    hh,mm,ss,ms=(int(value[:2]),int(value[2:4]),
                 int(value[4:6]),int(value[6:]))
    if hh>23 or mm>59 or ss>59 or ms>999:
        raise ValueError("Invalid L2 recorded time")
    return hh*3600000+mm*60000+ss*1000+ms


def trade_evidence(rows,*,code=CODE):
    """Compute from non-cancellation executions, no oracle values as source."""
    records=[]
    all_codes=Counter()
    for x in rows:
        if str(x.get("wind_code","")).upper()!=code:
            continue
        if int(x["date"])!=int(DAY):
            raise ValueError("Wrong trading day in selected row group")
        kind=str(x.get("trade_code","")).strip()
        all_codes[kind]+=1
        # Shanghai trades should not contain Shenzhen 'C' cancellations.
        # For unfamiliar codes, report counts rather than guessing semantics.
        if kind=="C":
            continue
        if kind not in ("0","", "None"):
            raise ValueError("Unrecognized executed-trade code; no guessed reconstruction")
        price=float(x["price"])/10000.0
        volume=float(x["volume"])
        if (not math.isfinite(price) or not math.isfinite(volume)
            or price<=0 or volume<=0):
            raise ValueError("Invalid vendor execution price or shares")
        when=clock(x["time"])
        if 9*3600000+24*60000<=when<9*3600000+32*60000:
            records.append((when,price,volume,x.get("trade_id")))
    regular=[r for r in records
             if 9*3600000+30*60000<=r[0]<9*3600000+31*60000]
    auction=[r for r in records
             if 9*3600000+25*60000<=r[0]<9*3600000+26*60000]
    if not regular:
        return {"status":"NO_0930_REGULAR_TRADES","event_code_counts":dict(all_codes)}
    return {"status":"OBSERVED_0930_REGULAR_TRADES",
            "event_code_counts":dict(all_codes),
            "regular":_summary_bucket(regular),
            "auction":_summary_bucket(auction) if auction else None}


def _summary_bucket(group):
    return {"count":len(group),
            "open_as_returned":group[0][1],
            "high":max(row[1] for row in group),
            "low":min(row[1] for row in group),
            "close_as_returned":group[-1][1],
            "shares":sum(row[2] for row in group),
            "derived_amount":sum(row[1]*row[2] for row in group),
            "nondecreasing_time":all(a[0]<=b[0] for a,b in zip(group,group[1:]))}


def sample(*,logger=print):
    """Only with Hugging Face authorization: read limited remote column groups."""
    credential=token()
    if not credential:
        raise ValueError("Hugging Face token absent; first request dataset access")
    try:
        from huggingface_hub import HfApi,HfFileSystem
        import pyarrow.parquet as pq
        import local_layout as L
        import qmt_1m_pipeline as P
        import qmt_eltdx_1m_probe as X
        import qmt_eltdx_auction_241_probe as A
        import qmt_eltdx_opening_tick_alignment as J
    except ImportError as exc:
        raise ValueError("Install huggingface_hub and pyarrow for remote sample mode") from exc
    folder=X.WORK/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    receipt=X.verified_cache(folder,CODE,stage,remote_only=False)
    q,qsha=X.read_qmt_source(stage,CODE)
    source=folder/"source_parquet"/(CODE.replace(".","_")+".parquet")
    if (not receipt or not q or source.is_symlink()
        or L.hash_file(source)!=receipt["source_sha256"]):
        raise ValueError("Original QMT 241 / eltdx 240 SHA not verified")
    original=pq.read_table(source)
    if original.schema!=P.PRIVATE_SCHEMA:
        raise ValueError("Original 240 source Arrow schema changed")
    qday=A.day_rows(q,date(2026,10,16))
    tday=A.day_rows(original.to_pylist(),date(2026,10,16))
    if len(qday)!=241 or len(tday)!=240:
        raise ValueError("Target QMT/TDX day grid incomplete")
    api=HfApi(token=credential)
    revision=api.dataset_info(REPO).sha
    files={x.path for x in api.list_repo_tree(
        REPO,path_in_repo=DAY,repo_type="dataset",revision=revision)}
    if not all(f"{DAY}/{name}" in files for name in NEEDED):
        raise ValueError("Target-day Level-2 market streams absent")
    fs=HfFileSystem(token=credential)
    fs_path=f"datasets/{REPO}@{revision}/{DAY}/逐笔成交.parquet"
    names=("wind_code","date","time","trade_id","trade_code","price","volume")
    with fs.open(fs_path,"rb",block_size=1024*1024,cache_type="readahead") as remote:
        parquet=pq.ParquetFile(remote,pre_buffer=False)
        groups=choose_groups(parquet.metadata,parquet.schema_arrow.names)
        budget=compressed_budget(parquet.metadata,groups,names)
        rows=[]
        for group in groups:
            table=parquet.read_row_group(group,columns=list(names))
            for item in table.to_pylist():
                if str(item["wind_code"]).upper()==CODE:
                    rows.append(item)
                    if len(rows)>MAX_ROWS_PER_STREAM:
                        raise ValueError("Too many target-stock trade rows")
    evidence=trade_evidence(rows)
    if evidence["status"]=="NO_0930_REGULAR_TRADES":
        output={"status":"NO_0930_REGULAR_TRADES"}
    else:
        b=evidence["regular"]
        qr=qday[1];qa=qday[0];native=tday[0]
        output={
            "status":"TRADE_EXTREMA_CROSSCHECK_RESEARCH_ONLY",
            "regular_trades":b["count"],
            "trade_count_auction":evidence["auction"]["count"] if evidence["auction"] else 0,
            "regular_open_match_qmt":J.strict_fit(b["open_as_returned"],qr["open"],"open"),
            "regular_high_match_qmt":J.strict_fit(b["high"],qr["high"],"high"),
            "regular_low_match_qmt":J.strict_fit(b["low"],qr["low"],"low"),
            "regular_close_match_qmt":J.strict_fit(b["close_as_returned"],qr["close"],"close"),
            "regular_high_differs_tdx_merged":not J.strict_fit(b["high"],native["high"],"high"),
            "regular_volume_matches_qmt_shares":J.strict_fit(
                b["shares"],qr["volume"]*100.0,"volume"),
            "regular_derived_amount_matches_qmt_strict":J.strict_fit(
                b["derived_amount"],qr["amount"],"amount"),
            "auction_matches_qmt_volume":(
                J.strict_fit(evidence["auction"]["shares"],qa["volume"]*100.0,"volume")
                if evidence["auction"] else None),
            "auction_derived_amount_matches_qmt_strict":(
                J.strict_fit(evidence["auction"]["derived_amount"],qa["amount"],"amount")
                if evidence["auction"] else None),
            "trade_records_nondecreasing_clock":b["nondecreasing_time"],
            "trade_sequence_and_completeness_not_independently_certified":True,
            "source_license_research_use_only":True,
            "source_values_not_authorized_for_production_merge":True}
    result={
        "dataset_revision":revision,"day":DAY,"symbol":CODE,
        "selected_trade_row_groups":len(groups),
        "compressed_column_budget_bytes":budget,
        "candidate":output,"raw_market_values_logged":False,
        "market_files_modified":False,"production_merge_authorized":False}
    logger("HF_241_L2_TARGET_SAMPLE="+json.dumps(result,sort_keys=True))
    return result


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--sample",action="store_true",help="Authorized low-footprint remote trade scan")
    args=cli.parse_args()
    access=report_access()
    if args.sample:
        if access["status"]!="TARGET_DAY_BOTH_STREAM_FILES_LISTED":
            raise SystemExit("Hugging Face L2 dataset access unavailable; no market read attempted")
        sample()
