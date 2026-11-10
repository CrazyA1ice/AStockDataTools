#!/usr/bin/env python3
"""Build/verify a versioned PURCHASED-first eight-cycle source-reference catalog.

Original purchased Parquet stays in place; only footer/file stat identities
(not full commercial file-content hashes) are recorded. Four completed H5
minute private gaps and verified 15/30/60m candidate Parquet files are
referenced by existing byte SHA256 receipts; no K-line values are copied.
NO production query activation, H5 mirror, market index or source writes.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from collections import Counter
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
PERIODS=("1min","5min","15min","30min","60min","day","week","month")
HIGH=("15min","30min","60min")
DAYS={
    "2026-10-08":5546,
    "2026-10-09":5547,
    "2026-10-12":5549,
    "2026-10-13":5549,
}
YEARS=tuple(range(2011,2027))
EXPECTED_STOCKDAYS=sum(DAYS.values())
EXPECTED_HIGH_ROWS=EXPECTED_STOCKDAYS*28
STATUS="purchased_primary_eight_cycle_private_source_references_only_v1"

def _load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

FOOTER=_load("catalog_original_purchased_footer",
             "survey-purchased-all-cycle-footers-readonly.py")
PRIVATE=_load("catalog_sha_verified_oct_highcycle_receipts",
              "stage-next-uncovered-oct-h5-high-cycle-private-parquet.py")
MINUTE=_load("catalog_existing_minute_gap_verified_receipts",
             "query-purchased-primary-minute-with-private-gap-readonly.py")
S=PRIVATE.S

def _json(doc):
    return (json.dumps(doc,ensure_ascii=False,sort_keys=True,
                       separators=(",",":"),allow_nan=False)+"\n").encode("utf-8")

def _sha(path):
    return S._sha(path)

def _safe_file_ref(path, root):
    if (path.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve())):
        raise ValueError("Unsafe catalog source file reference")
    st=path.stat()
    if st.st_size<=0 or st.st_mtime_ns<=0:
        raise ValueError("Invalid source file identity")
    return {
        "relative_path":path.relative_to(root).as_posix(),
        "size_bytes":st.st_size,
        "mtime_ns":st.st_mtime_ns,
    }

def _purchased(root):
    # The existing survey only opens Parquet footers. Do not read the billions
    # of already-purchased OHLCVA bars or re-materialize their partitions.
    inv=FOOTER.inventory(Path(root),YEARS,max_total_files=5000)
    if (inv.get("status")!=
            "read_only_purchased_parquet_footer_envelopes_not_exact_coverage"
            or inv.get("only_original_parquet_file_footers_read") is not True
            or inv.get("original_market_files_modified") is not False
            or inv.get("new_market_or_index_files_written") is not False
            or inv.get("no_ohlcva_rows_read_or_exported") is not True
            or tuple(inv.get("requested_years",()))!=YEARS
            or not set(PERIODS).issubset(inv.get("source_root_period_directories",()))):
        raise ValueError("Original purchased eight-cycle footer inventory gate failed")
    yearly={}
    source_rows={}
    for period in PERIODS:
        annual=inv["period_years"][period]
        if set(annual)!={str(y) for y in YEARS}:
            raise ValueError("Missing purchased period years")
        yearly[period]={}
        for year in YEARS:
            entry=annual[str(year)]
            if (entry["source_files"]<1
                    or not entry["footer_envelope_complete_for_nonempty_row_groups"]
                    or entry["nonempty_row_groups_without_usable_ts_bounds"]!=0
                    or entry["row_groups_with_bounds_outside_filename_year"]!=0):
                raise ValueError("Incomplete purchased footer envelope: "+
                                 period+"/"+str(year))
            yearly[period][str(year)]={
                "source_files":entry["source_files"],
                "footer_rows_not_unique_keys":entry["source_rows_from_parquet_footers"],
                "row_groups":entry["row_groups"],
                "source_file_stat_identity_sha256_not_content_digest":
                    entry["source_file_stat_identity_sha256_not_content_digest"],
            }
        source_rows[period]=sum(
            x["footer_rows_not_unique_keys"] for x in yearly[period].values())
    paths,naming=FOOTER.F.source_files(Path(root),PERIODS,2011,2026)
    if (any(v for v in naming.get(
            "year_ambiguous_or_absent_parquet_filenames_by_period",{}).values())
            or any(v for v in naming.get(
                "symlinked_parquet_files_skipped_by_period",{}).values())):
        raise ValueError("Purchased source catalog cannot ignore ambiguous filenames/symlinks")
    files={}
    for period in PERIODS:
        for year in YEARS:
            relevant=paths[period][year]
            if len(relevant)!=yearly[period][str(year)]["source_files"]:
                raise ValueError("Purchased file metadata count changed during catalog")
            files[period+"|"+str(year)]=[
                _safe_file_ref(file,Path(root)) for file in relevant]
    return {
        "period_years":yearly,
        "original_source_files_by_period_year":files,
        "footer_row_totals_not_exact_unique_keys":source_rows,
        "original_purchased_file_identity_is_stat_not_full_content_sha256":True,
        "original_source_priority_over_H5_for_any_overlap":True,
        "purchased_source_files_copied":False,
        "purchase_source_keywise_coverage_certified_from_footers":False,
    }

def _existing_private():
    records,run_count=PRIVATE.existing_stockdays()
    keys_by_day=Counter(d for d,_ in records)
    if len(records)!=EXPECTED_STOCKDAYS or dict(keys_by_day)!=DAYS:
        raise ValueError("Four-day SHA-verified private 15/30/60 stockday coverage changed")
    stage_root=S._safe_stage_root()
    runs=[]
    counted=Counter()
    for run in sorted(stage_root.iterdir()):
        if not run.is_dir() or run.is_symlink() or S.RUNID.fullmatch(run.name) is None:
            raise ValueError("Unsafe private highcycle stage directory")
        receipt=run/"receipt.json"
        if receipt.is_symlink() or not receipt.is_file():
            raise ValueError("Private stage receipt missing")
        doc=json.loads(receipt.read_text(encoding="utf-8"))
        outputs={}
        for period in HIGH:
            entry=doc["outputs"][period]
            target=run/(period+".parquet")
            if (_sha(target)!=entry["sha256"]
                    or not entry["complete_row_by_row_readback_exact"]):
                raise ValueError("Private highcycle stage output SHA mismatch")
            outputs[period]={
                "relative_file":entry["private_file"],
                "rows":entry["rows"],
                "content_sha256":entry["sha256"],
            }
            counted[period]+=entry["rows"]
        runs.append({
            "run_id":run.name,
            "receipt_relative_file":receipt.relative_to(S.MODULE).as_posix(),
            "receipt_content_sha256":_sha(receipt),
            "source_days":doc["source_days"],
            "verified_stockdays":doc["verified_source_stockdays"],
            "outputs":outputs,
        })
    if (len(runs)!=run_count
            or dict(counted)!={"15min":EXPECTED_STOCKDAYS*16,
                               "30min":EXPECTED_STOCKDAYS*8,
                               "60min":EXPECTED_STOCKDAYS*4}):
        raise ValueError("Physical private highcycle candidate row ledger mismatch")
    minute=[]
    for day in DAYS:
        for period in ("1min","5min"):
            selected=MINUTE._safe_private_file(date.fromisoformat(day),period)
            if selected is None:
                raise ValueError("Missing verified private H5 minute gap source")
            file,entry=selected
            if not file.resolve().is_relative_to(
                    (MODULE/"work"/"unified_parquet").resolve()):
                raise ValueError("Private minute reference outside workspace")
            expected=entry["unified_parquet_sha256"]
            if _sha(file)!=expected:
                raise ValueError("Private minute file changed during catalog")
            minute.append({
                "day":day,"period":period,
                "relative_file":file.relative_to(MODULE).as_posix(),
                "content_sha256":expected,
                "h5_only_complete_stockday_rows":
                    entry["source_rows"]["h5_only_complete_stockday"],
                "purchased_parquet_priority":True,
                "vendor_units_certified":False,
            })
    return {
        "stage_runs":runs,
        "highcycle_sha_verified_run_count":run_count,
        "stockdays_by_date":dict(sorted(keys_by_day.items())),
        "highcycle_candidate_rows_by_period":dict(counted),
        "highcycle_total_candidate_rows":sum(counted.values()),
        "minute_h5_gap_private_references":minute,
        "all_private_candidates_research_only":True,
        "candidate_physical_units_certified":False,
        "candidate_timestamp_labels_certified":False,
        "candidate_corporate_actions_certified":False,
    }

def assemble(root):
    root=Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Original market root unavailable/unsafe")
    purchased=_purchased(root)
    private=_existing_private()
    content={
        "format":"AStockDataTools purchased-primary eight-cycle source catalog v1",
        "status":STATUS,
        "periods":list(PERIODS),
        "purchased_years":[2011,2026],
        "purchased_reference_mode":"original_parquet_file_refs_not_copied",
        "private_highcycle_source_days":list(DAYS),
        "purchased":purchased,
        "private_research_candidates":private,
        "research_query_explicit_opt_in_required":True,
        "production_or_private_active_pointer_modified":False,
        "original_market_files_modified":False,
        "market_OHLCVA_read_or_copied_for_catalog":False,
        "new_market_index_or_parquet_materialized":False,
        "vendor_units_certified":False,
        "timestamp_semantics_certified":False,
        "corporate_actions_certified":False,
        "ready_for_production_merge":False,
        "ready_for_h5_mirror":False,
        "full_historical_stockday_key_coverage_certified":False,
    }
    return content

def seal(payload):
    digest=hashlib.sha256(_json(payload)).hexdigest()
    return {"catalog_sha256":digest,"payload":payload}

def write_private_catalog(sealed):
    # Only private immutable metadata, NOT market materialization.
    root=MODULE/"work"/"unified_parquet"
    if any(x.is_symlink() for x in (MODULE,MODULE/"work",root)):
        raise ValueError("Unsafe private catalog parent")
    target=root/"source_catalog"
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise ValueError("Unsafe private catalog directory")
    target.mkdir(parents=True,exist_ok=True)
    file=target/("catalog_"+sealed["catalog_sha256"]+".json")
    content=_json(sealed)
    if file.exists() or file.is_symlink():
        if file.is_symlink() or not file.is_file() or file.read_bytes()!=content:
            raise ValueError("Existing private catalog file content mismatch")
        return file,False
    with file.open("xb") as f:
        f.write(content)
    if file.read_bytes()!=content:
        raise ValueError("Private catalog immutable write/readback failed")
    return file,True

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--preview-only",action="store_true")
    group.add_argument("--write-private-catalog-only",action="store_true")
    args=p.parse_args(argv)
    try:
        payload=assemble(args.root)
        sealed=seal(payload)
        report={
            "status":STATUS,
            "catalog_sha256":sealed["catalog_sha256"],
            "purchased_years":16,
            "purchased_periods":len(PERIODS),
            "purchased_source_files":sum(
                len(files) for files in payload["purchased"][
                    "original_source_files_by_period_year"].values()),
            "highcycle_private_runs":payload["private_research_candidates"][
                "highcycle_sha_verified_run_count"],
            "highcycle_candidate_stockdays":sum(DAYS.values()),
            "highcycle_candidate_rows":payload["private_research_candidates"][
                "highcycle_total_candidate_rows"],
            "h5_private_minute_refs":len(payload["private_research_candidates"][
                "minute_h5_gap_private_references"]),
            "preview_only":args.preview_only,
            "production_activated":False,
            "ready_for_production_merge":False,
            "original_market_files_modified":False,
            "purchased_parquet_bars_copied":False,
            "vendor_units_certified":False,
        }
        if args.write_private_catalog_only:
            file,created=write_private_catalog(sealed)
            report["catalog_relative_file"]=file.relative_to(MODULE).as_posix()
            report["new_metadata_catalog_written"]=created
        else:
            report["new_metadata_catalog_written"]=False
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
        p.error("Eight-cycle purchased-primary source catalog NOT ACCEPTED: "+
                type(exc).__name__+": "+str(exc))
    print("PURCHASED_PRIMARY_EIGHT_CYCLE_SOURCE_CATALOG="+json.dumps(
        report,ensure_ascii=False,sort_keys=True,separators=(",",":")),flush=True)

if __name__=="__main__":
    main()
