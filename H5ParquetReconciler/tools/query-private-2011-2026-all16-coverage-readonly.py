#!/usr/bin/env python3
"""Bounded *private only* DAY coverage probe against SHA-pinned all16 version.

Returns only source-classified bar COUNTS, footer costs and query timing.
Never exports licensed OHLCVA, stock symbols, exact requested dates,
or individual dates to SAFE. No active pointer/market/source/H5 writes.

Strictly 1..31 inclusive days, canonical A-share symbol, and bounded
Parquet row groups. Query is NOT approval for production queries.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sqlite3
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,HERE/path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


V=load("private_all16_coverage_version_verifier",
       "certify-private-2011-2026-physical-version-readonly.py")
M=V.M
PHYS=M.PHYS
FORMAT="AStockDataTools private all16 DAY SHA-pinned bounded coverage query v1"
KNOWN_CLASSES={
    "purchased_parquet",
    "private_h5_whole_date_candidate",
    "private_h5_mixed_stockday_candidate",
}
YEAR_DIR=re.compile(r"work/unified_parquet/physical_years/physical_(20(?:1[1-9]|2[0-6]))_[0-9a-f]{12,32}\Z")
MAX_SAFE=1000000


def parameters(symbol,first,last,max_candidate_rows):
    source=PHYS.ST.CORE
    canonical=source.symbol_id(symbol)
    if (type(symbol) is not str or canonical is None
            or canonical!=symbol.upper()):
        raise ValueError("Only canonical A-share symbol input accepted")
    try:
        begin=date.fromisoformat(str(first))
        end=date.fromisoformat(str(last))
    except (TypeError,ValueError):
        raise ValueError("Require ISO8601 inclusive query dates") from None
    if (begin>end or not 1<=(end-begin).days+1<=31
            or begin.year<2011 or end.year>2026):
        raise ValueError("Only bounded private 2011..2026 windows of <=31 days")
    if (any(not source.is_a_share_candidate(canonical,y)
            for y in range(begin.year,end.year+1))):
        raise ValueError("Requested code not in known historical A-share symbol class")
    if (type(max_candidate_rows) is not int
            or not 1<=max_candidate_rows<=3000000):
        raise ValueError("Unsafe private rowgroup candidate scan budget")
    return canonical,begin,end


def version(path,expected_sha256):
    if (type(expected_sha256) is not str
            or not re.fullmatch("[0-9a-f]{64}",expected_sha256)):
        raise ValueError("Pinned exact private 16-year version SHA is required")
    p=V.safe_file(path)
    if hashlib.sha256(p.read_bytes()).hexdigest()!=expected_sha256:
        raise ValueError("Private 16-year version SAFE SHA differs")
    doc=json.loads(p.read_bytes())
    if (doc.get("format")!=V.FORMAT
            or doc.get("status")!=
              "all16_private_annual_physical_shards_sha_and_stockday_years_verified_not_activated"
            or doc.get("year_count")!=16
            or doc.get("years")!=list(range(2011,2027))
            or doc.get("purchased_original_records")!=14115707
            or doc.get("verified_h5_only_gap_records")!=22274
            or doc.get("private_total_stockday_records")!=14137981
            or doc.get("per_year_private_manifest_sha_and_independent_audit_bound") is not True
            or doc.get("per_year_private_sqlite_index_integrity_rechecked_readonly") is not True
            or doc.get("cross_year_stockday_key_ranges_disjoint") is not True
            or type(doc.get("annual")) is not dict
            or set(doc["annual"])!={str(y) for y in range(2011,2027)}
            or any(doc.get(k) is not False for k in (
                "original_market_files_written",
                "private_physical_parquet_or_sqlite_written",
                "private_or_production_active_pointer_modified",
                "candidate_source_units_certified",
                "ready_for_production_query","ready_for_automatic_market_merge",
                "ready_for_h5_mirror"))):
        raise ValueError("Version SAFE not all16 private and independently SHA-bound")
    if sum(x.get("total_rows",0) for x in doc["annual"].values())!=14137981:
        raise ValueError("Private annual rows fail whole-version conservation")
    return doc


def entries(year,folder,manifest):
    """Return only approved normalized Parquet files for requested year."""
    expected={("purchased" if year<2026 else f"2026-{m:02d}.parquet")
              for m in (range(1,10) if year==2026 else (1,))}
    if year==2016:
        expected.add("h5_gap_2016")
    if year==2026:
        expected.add("h5_gap_2026")
    parts=manifest.get("partition_files")
    if type(parts) is not dict or set(parts)!=expected:
        raise ValueError("Year private physical partition set changed")
    for key,part in sorted(parts.items()):
        if key=="purchased":
            relative="purchased/day.parquet"
            source="purchased_parquet"
        elif key=="h5_gap_2016":
            relative="candidate/h5-gap-2016.parquet"
            source="private_h5_mixed_stockday_candidate"
        elif key=="h5_gap_2026":
            relative="candidate/h5-gap-2026.parquet"
            source="mixed_whole_h5_candidates"
        else:
            relative=f"purchased/month={key[5:7]}/day.parquet"
            source="purchased_parquet"
        if (type(part) is not dict
                or part.get("relative_file")!=relative
                or part.get("source_kind")!=source
                or type(part.get("rows")) is not int
                or part["rows"]<=0
                or not re.fullmatch("[0-9a-f]{64}",str(part.get("sha256")))):
            raise ValueError("Private year partition descriptor is untrusted")
        yield key,folder/relative,part



def exclude_by_exact_symbol_statistics(statistics,canonical):
    """Fail open unless footer explicitly guarantees non-truncated bounds.

    Many Arrow releases do not expose is_min_max_exact; never assume that
    ordinary min/max string stats are sufficient for a negative result.
    """
    if statistics is None:
        return False
    return (type(canonical) is str
            and getattr(statistics,"has_min_max",False) is True
            and getattr(statistics,"is_min_max_exact",False) is True
            and type(getattr(statistics,"min",None)) is str
            and type(getattr(statistics,"max",None)) is str
            and (canonical<statistics.min or canonical>statistics.max))


def query(version_doc,version_sha,symbol,first,last,max_candidate_rows=1200000,
          private_row_callback=None):
    started=time.perf_counter()
    if private_row_callback is not None and not callable(private_row_callback):
        raise ValueError("Private row handler must be callable and local-only")
    canonical,begin,end=parameters(symbol,first,last,max_candidate_rows)
    import pyarrow as pa
    import pyarrow.parquet as pq
    timestamp_low=int(datetime(begin.year,begin.month,begin.day,
                               tzinfo=PHYS.ST.CORE.UTC8).timestamp()*1000)
    after=end+timedelta(days=1)
    timestamp_high=int(datetime(after.year,after.month,after.day,
                                tzinfo=PHYS.ST.CORE.UTC8).timestamp()*1000)
    schema=PHYS.schema(pa)
    counter=Counter()
    metadata=Counter()
    seen=set()
    years=list(range(begin.year,end.year+1))
    pending=[]
    source_indexes=[]
    timings={}
    phase_start=time.perf_counter()
    # Footer + all selected private file SHA preflight BEFORE reading keys.
    for year in years:
        node=version_doc["annual"][str(year)]
        rel=node.get("private_relative_directory")
        if (type(rel) is not str or YEAR_DIR.fullmatch(rel) is None
                or int(YEAR_DIR.fullmatch(rel).group(1))!=year
                or type(node.get("total_rows")) is not int
                or node["total_rows"]<0):
            raise ValueError("Untrusted all16 year path/count in version")
        folder=M.MODULE/rel
        mf=folder/"manifest.json"
        db=folder/"stockday-unique.sqlite3"
        if (any(x.is_symlink() for x in
                (M.MODULE/"work",M.WORK,M.ROOT,folder,mf,db))
                or not folder.is_dir()
                or folder.resolve().parent!=M.ROOT.resolve()
                or not mf.is_file() or not db.is_file()
                or M.ST.sha(mf)!=node.get("physical_manifest_sha256")
                or M.ST.sha(db)!=node.get("private_stockday_index_sha256")):
            raise ValueError("Selected private year manifest/SQLite SHA changed")
        manifest=json.loads(mf.read_bytes())
        if (manifest.get("year")!=year
                or manifest.get("total_private_physical_rows")!=node["total_rows"]):
            raise ValueError("Selected private year manifest content differs")
        source_indexes.append((year,db))
        for key,path,part in entries(year,folder,manifest):
            if (path.is_symlink() or path.parent.is_symlink()
                    or not path.is_file()
                    or not 0<path.stat().st_size<=M.PHYS.MAX_PART_BYTES
                    or M.ST.sha(path)!=part["sha256"]):
                raise ValueError("Private selected partition bytes differ from SHA")
            with pq.ParquetFile(path,memory_map=False,pre_buffer=False) as pf:
                if (pf.schema_arrow!=schema
                        or pf.metadata.num_rows!=part["rows"]):
                    raise ValueError("Private queried Arrow footer differs")
                metadata["physical_parquet_partitions_sha_checked"]+=1
                for group in range(pf.metadata.num_row_groups):
                    info=pf.metadata.row_group(group)
                    metadata["physical_rowgroups_checked"]+=1
                    ts_stats=info.column(0).statistics
                    if (ts_stats is not None and
                            ts_stats.has_min_max and
                            (ts_stats.max<timestamp_low or
                             ts_stats.min>=timestamp_high)):
                        metadata["physical_rowgroups_pruned"]+=1
                        continue
                    # Only trust symbol stats for exact min/max values.
                    # Missing, truncated, or unknown statistics never
                    # exclude a RowGroup. The column is the canonical
                    # stock symbol (third column of fixed Arrow schema).
                    sym_stats=info.column(2).statistics
                    if exclude_by_exact_symbol_statistics(sym_stats,canonical):
                        metadata["physical_rowgroups_pruned_by_exact_symbol_stats"]+=1
                        continue
                    metadata["candidate_rows_upper_bound"]+=info.num_rows
                    pending.append((path,group,year,key))
    timings["sha_footer_and_rowgroup_preflight_seconds"]=round(
        time.perf_counter()-phase_start,6)
    if metadata["candidate_rows_upper_bound"]>max_candidate_rows:
        raise ValueError("Requested private window exceeds bounded read budget")
    phase_start=time.perf_counter()
    # Scan only FOUR index/source columns. Apply all four key comparisons
    # by Arrow compute before converting to Python. For many symbols,
    # this avoids boxing >1 million nonmatching rows as Python strings.
    # Reuse a ParquetFile per private partition instead of reopening each
    # individual RowGroup (187 opens in the original 2025-26 smoke test).
    import pyarrow.compute as pc
    day_first=begin.isoformat()
    day_last=end.isoformat()
    by_file={}
    for path,group,year,key in pending:
        by_file.setdefault(path,[]).append((group,year,key))
    for path,groups in by_file.items():
        with pq.ParquetFile(path,memory_map=False,pre_buffer=False) as pf:
            for group,year,key in groups:
                table=pf.read_row_group(group,
                    columns=(["ts","trading_date","symbol","value_source"]
                             if private_row_callback is None else None),
                    use_threads=False)
                metadata["physical_rowgroups_loaded"]+=1
                if any(x.null_count for x in table.columns):
                    raise ValueError("Private normalized stockday key/source contains null")
                mask=pc.and_(
                    pc.and_(
                        pc.greater_equal(table.column("ts"),timestamp_low),
                        pc.less(table.column("ts"),timestamp_high)),
                    pc.and_(
                        pc.equal(table.column("symbol"),canonical),
                        pc.and_(
                            pc.greater_equal(table.column("trading_date"),day_first),
                            pc.less_equal(table.column("trading_date"),day_last))))
                selected=table.filter(mask)
                metadata["physical_key_rows_selected_by_arrow"]+=selected.num_rows
                selected_rows=(
                    ((r["ts"],r["trading_date"],r["symbol"],r["value_source"],r)
                     for r in selected.to_pylist())
                    if private_row_callback is not None else
                    ((ts,day,sym,kind,None) for ts,day,sym,kind in zip(
                        selected.column("ts").to_pylist(),
                        selected.column("trading_date").to_pylist(),
                        selected.column("symbol").to_pylist(),
                        selected.column("value_source").to_pylist())))
                for ts,day,sym,kind,raw in selected_rows:
                    if (kind not in KNOWN_CLASSES
                            or (key=="purchased" or key.startswith("2026-"))
                               and kind!="purchased_parquet"
                            or key=="h5_gap_2016"
                               and kind!="private_h5_mixed_stockday_candidate"
                            or key=="h5_gap_2026" and kind=="purchased_parquet"):
                        raise ValueError("Unexpected normalized private purchased/H5 provenance")
                    identity=(year,day,sym)
                    if identity in seen:
                        raise ValueError("Duplicate private stockday in bounded version query")
                    # Optional *programmatic-only* private data consumer:
                    # exact original Float64 check; no local row is placed
                    # in the ordinary aggregate SAFE returned by query().
                    if private_row_callback is not None:
                        restored=dict(raw)
                        restored["symbol"]=raw["source_symbol"]
                        month=(int(key[5:7]) if key.startswith("2026-")
                               else None)
                        if PHYS.normalise(restored,kind,year,month)!=raw:
                            raise ValueError("Private row original Float64/provenance validation failed")
                        private_row_callback(raw)
                    seen.add(identity)
                    counter[kind]+=1
    timings["arrow_key_filter_seconds"]=round(
        time.perf_counter()-phase_start,6)
    phase_start=time.perf_counter()
    sql_total=0
    sql_kinds=Counter()
    for year,idx in source_indexes:
        con=sqlite3.connect(idx.resolve().as_uri()+"?mode=ro&immutable=1",uri=True)
        try:
            pairs=con.execute(
                "SELECT kind,COUNT(*) FROM stockday WHERE year=? AND "
                "symbol=? AND trading_date BETWEEN ? AND ? GROUP BY kind",
                (year,canonical,begin.isoformat(),end.isoformat())).fetchall()
        finally:
            con.close()
        for kind,n in pairs:
            if kind not in KNOWN_CLASSES or n<0:
                raise ValueError("Unexpected private SQLite source class")
            sql_kinds[kind]+=n
            sql_total+=n
    if sql_total!=len(seen) or sql_kinds!=counter:
        raise ValueError("Private Parquet coverage and SHA-bound SQLite keys disagree")
    timings["sqlite_count_crosscheck_seconds"]=round(
        time.perf_counter()-phase_start,6)
    return {
        "format":FORMAT,
        "status":"private_all16_bounded_day_coverage_keys_and_provenance_verified_only",
        "source_all16_private_version_sha256":version_sha,
        "query_years":years,
        "private_query_symbol_and_exact_dates_not_exported":True,
        "matched_stockday_rows":len(seen),
        "by_source_counts":dict(sorted(counter.items())),
        "sqlite_rows_matched":sql_total,
        "sha_checked_private_partitions":metadata["physical_parquet_partitions_sha_checked"],
        "rowgroups_metadata_checked":metadata["physical_rowgroups_checked"],
        "rowgroups_pruned":metadata["physical_rowgroups_pruned"],
        "rowgroups_pruned_by_exact_symbol_stats":
            metadata["physical_rowgroups_pruned_by_exact_symbol_stats"],
        "rowgroups_loaded":metadata["physical_rowgroups_loaded"],
        "candidate_rows_upper_bound":metadata["candidate_rows_upper_bound"],
        "matched_key_rows_vectorized_by_arrow":
            metadata["physical_key_rows_selected_by_arrow"],
        "parquet_file_handles_for_rowgroups":len(by_file),
        "phase_timings_seconds":timings,
        "bounded_window_days_max":31,
        "elapsed_seconds":round(time.perf_counter()-started,6),
        "all_original_licensed_OHLCVA_values_read":
            private_row_callback is not None,
        "local_licensed_OHLCVA_values_exported_to_safe":False,
        "original_market_source_opened":False,
        "private_or_production_active_pointer_modified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "ready_for_h5_mirror":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version-safe",type=Path,required=True)
    p.add_argument("--version-sha256",required=True)
    p.add_argument("--symbol",required=True)
    p.add_argument("--start",required=True)
    p.add_argument("--end",required=True)
    p.add_argument("--max-candidate-rows",type=int,default=1200000)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--private-coverage-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        target=Path(a.out)
        if (M.REPORTS.is_symlink() or target.is_symlink()
                or target.exists() or target.suffix!=".json"
                or target.resolve().parent!=M.REPORTS.resolve()):
            raise ValueError("Coverage SAFE must be a NEW aggregate-only module report")
        version_doc=version(a.version_safe,a.version_sha256)
        result=query(version_doc,a.version_sha256,
                     a.symbol,a.start,a.end,a.max_candidate_rows)
        with target.open("x",encoding="utf-8",newline="\n") as fp:
            json.dump(result,fp,indent=2,sort_keys=True)
            fp.write("\n")
        print("PASS: SHA-bound private 16-year bounded DAY key/source coverage query")
        print("Private matching stockday keys:",result["matched_stockday_rows"])
        print("Only aggregate module report:",a.out)
        print("OHLCVA/stock symbols/date window were NOT exported in receipt")
    except Exception:
        p.error("Refused private all16 bounded DAY query: source SHA, schema, budget or SQLite key mismatch")


if __name__=="__main__":
    main()
