#!/usr/bin/env python3
"""Build a complete standalone Hikyuu DAY H5 from EXISTING native H5 sources.

No Parquet OHLCVA is decoded: the 14,137,981 purchased-first modern DAY rows
are already written, SHA audited and all-native-integer read back in the
immutable full_day_3dc5044a4122/ directory.

COPY each *original* Hikyuu sh/sz/bj_day.h5 file to a NEW isolated directory.
Inside the copies, for canonical purchased A-share symbols only, install
the 2011..2026 Parquet-priority native tables, while PRESERVING the original
pre-2011 native integer records and post-2010 raw-only timestamps absent
from purchased-first mirror. All other symbols, indexes, non-/data groups
and attributes in original H5 remain untouched in the copied files.

This produces a standalone validation candidate, never edits original
D:/stock, never activates production H5, never removes unqualified history.
The integer representation of Parquet-purchased bars is quantized; not a
Float64-exact equivalence or an official source-unit certification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import traceback
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
MIRRORS=MODULE/"work"/"h5_mirror"
KNOWN_2011_2026_MIRROR="3dc5044a4122"
MIRROR_NAME="full_day_"+KNOWN_2011_2026_MIRROR
MODERN_COUNT=14137981
DATE_2011=201101010000
AFTER_END=202610140000
RUN=re.compile(r"[0-9a-f]{12}\Z")
CODE=re.compile(r"(SH|SZ|BJ)[0-9]{6}\Z")
MARKETS=("sh","sz","bj")
FIELDS=("closePrice","datetime","highPrice","lowPrice",
        "openPrice","transAmount","transCount")
VERSION="AStockDataTools native old-H5-preserving purchased-priority full DAY merge v1"
SAFE_STATUS="isolated_full_day_h5_original_history_plus_2011_2026_parquet_native_merged_and_integer_verified"

def sha(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as fd:
        for b in iter(lambda:fd.read(1<<20),b""):
            digest.update(b)
    return digest.hexdigest()

def canonical_dtype(np):
    dtype=np.dtype([
        ("closePrice","<u4"),("datetime","<u8"),("highPrice","<u4"),
        ("lowPrice","<u4"),("openPrice","<u4"),
        ("transAmount","<u8"),("transCount","<u8")])
    if (dtype.itemsize!=40 or dtype.names!=FIELDS
            or tuple(dtype.fields[k][1] for k in FIELDS)!=(0,4,12,16,20,24,32)):
        raise ValueError("Hikyuu native 40-byte DAY layout is not available")
    return dtype

def convert_records(records,dtype,np):
    """Accept 40-byte native TABLE, or an exactly typed field permutation."""
    source=records.dtype
    if source.names is None or set(source.names)!=set(FIELDS):
        raise ValueError("Unrecognized source Hikyuu DAY TABLE fields")
    for name in FIELDS:
        if source.fields[name][0].kind!="u" or (source.fields[name][0].itemsize
                !=dtype.fields[name][0].itemsize):
            raise ValueError("Hikyuu DAY integer signedness/width differs")
    out=np.empty(len(records),dtype=dtype)
    for name in FIELDS:
        out[name]=records[name]
    return out

def ensure_sorted_unique(rows,np,where):
    if len(rows)<2:
        return
    stamps=rows["datetime"]
    if bool(np.any(stamps[1:]<=stamps[:-1])):
        raise ValueError(where+" DAY native time keys not strictly increasing")

def merge_stock(old,modern,np,dtype):
    """Preserve original-only keys, Parquet mirror priority on overlap."""
    old=convert_records(old,dtype,np)
    modern=convert_records(modern,dtype,np)
    ensure_sorted_unique(old,np,"original")
    ensure_sorted_unique(modern,np,"modern purchased-first")
    if len(modern)==0 or (int(modern["datetime"][0])<DATE_2011
            or int(modern["datetime"][-1])>=AFTER_END):
        raise ValueError("2011..2026 purchased-first native mirror time range invalid")
    if len(old) and int(old["datetime"][-1])>=AFTER_END:
        raise ValueError("Original H5 contains records past authorized 2026-10-13 end")
    # Pre-2011 (the original historical Hikyuu native ints) MUST survive.
    # For 2011+ only Parquet mirror wins matching exact native (stock,day) keys.
    keep=np.ones(len(old),dtype=np.bool_)
    if len(old):
        positions=np.searchsorted(modern["datetime"],old["datetime"])
        overlap=(positions<len(modern))
        overlap[overlap]=(modern["datetime"][positions[overlap]]==
                          old["datetime"][overlap])
        if bool(np.any(overlap & (old["datetime"]<DATE_2011))):
            raise ValueError("Historical pre-2011 key overlaps modern purchased mirror")
        keep &= ~overlap
    remaining=old[keep]
    combined=np.concatenate((remaining,modern))
    combined.sort(order="datetime")
    ensure_sorted_unique(combined,np,"full merged")
    old_pre=int(np.count_nonzero(old["datetime"]<DATE_2011))
    extra_modern=int(np.count_nonzero(remaining["datetime"]>=DATE_2011))
    purchased_replacements=int(len(old)-len(remaining))
    if (len(combined)!=len(modern)+len(remaining)
            or old_pre!=int(np.count_nonzero(
                combined["datetime"]<DATE_2011))):
        raise ValueError("Pre-2011 old H5 records were not conserved")
    return combined,{
        "original_historical_pre2011_preserved":old_pre,
        "original_post2010_no_purchased_key_preserved":extra_modern,
        "original_post2010_replaced_by_purchased":purchased_replacements,
        "purchased_first_modern_records":len(modern),
    }

def verified_modern_sources(mirror_safe,mirror_root):
    safe=Path(mirror_safe)
    src=MIRRORS/MIRROR_NAME
    if (REPORTS.is_symlink() or safe.is_symlink()
            or safe.resolve().parent!=REPORTS.resolve()
            or not safe.is_file() or not 0<safe.stat().st_size<=100000
            or src.is_symlink() or src.resolve()!=Path(mirror_root).resolve()
            or not src.is_dir()):
        raise ValueError("Require fixed locally accepted full 2011-2026 native H5 sources")
    doc=json.loads(safe.read_bytes())
    sha_map=doc.get("private_h5_files_sha256")
    if (doc.get("status")!=
            "private_day_native_h5_40byte_tables_written_all_integer_rows_readback_not_activated"
            or doc.get("total_h5_native_integer_records")!=MODERN_COUNT
            or doc.get("total_private_parquet_rows")!=MODERN_COUNT
            or doc.get("year_range")!=[2011,2026]
            or doc.get("native_40byte_table_integer_sha_readback_verified") is not True
            or doc.get("original_hikyuu_h5_files_modified") is not False
            or doc.get("full_mirror_ready_for_production") is not False
            or type(sha_map) is not dict
            or set(sha_map)!={m+"_day.h5" for m in MARKETS}):
        raise ValueError("Private 2011-2026 Hikyuu native mirror SAFE not accepted")
    for name,expected in sha_map.items():
        p=src/name
        if (p.is_symlink() or not p.is_file()
                or type(expected) is not str
                or re.fullmatch("[a-f0-9]{64}",expected) is None
                or sha(p)!=expected):
            raise ValueError("Existing native DAY mirror SHA differs")
    return src,sha_map,sha(safe)

def validate_paths(root,run_id,out):
    market=Path(root)/"HikyuuData"
    safe=Path(out)
    dest=MIRRORS/("complete_day_"+run_id)
    if (type(run_id) is not str or RUN.fullmatch(run_id) is None
            or not market.is_dir() or market.is_symlink()
            or not Path(root).is_dir() or Path(root).is_symlink()
            or any(p.is_symlink() for p in (MODULE/"work",MIRRORS,REPORTS,dest,safe))
            or not REPORTS.is_dir() or safe.resolve().parent!=REPORTS.resolve()
            or safe.exists() or dest.exists()
            or safe.suffix!=".json" or dest.resolve().parent!=MIRRORS.resolve()
            or market.resolve().is_relative_to(MODULE.resolve())
            or MODULE.resolve().is_relative_to(market.resolve())):
        raise ValueError("Unsafe original H5 or isolated output path")
    originals={}
    for m in MARKETS:
        p=market/(m+"_day.h5")
        if p.is_symlink() or not p.is_file():
            raise ValueError("Original Hikyuu DAY source missing")
        originals[m]=p
    return originals,dest,safe

def mirror(root,mirror_safe,mirror_root,run_id,out):
    import numpy as np
    import tables
    dtype=canonical_dtype(np)
    old_files,dest,safe=validate_paths(root,run_id,out)
    modern_dir,sha_map,source_safe_sha=verified_modern_sources(
        mirror_safe,mirror_root)
    # External source never opened for writing. Snapshot source stat and
    # full byte SHA before copy and check again on completion.
    old_status={}
    for m,p in old_files.items():
        st=p.stat()
        old_status[m]=(st.st_size,st.st_mtime_ns,sha(p))
    MIRRORS.mkdir(parents=True,exist_ok=True)
    dest.mkdir(exist_ok=False)
    stats=Counter()
    original_non_mirror_stocks=0
    modern_tables=0
    native_rows=0
    try:
        for m in MARKETS:
            name=m+"_day.h5"
            destination=dest/name
            shutil.copyfile(old_files[m],destination)
            with tables.open_file(str(modern_dir/name),"r") as new, \
                    tables.open_file(str(destination),"a") as target:
                if not hasattr(new.root,"data") or not hasattr(target.root,"data"):
                    raise ValueError("Native DAY H5 /data table group missing")
                existing={n._v_name:n for n in target.root.data
                          if isinstance(n,tables.Table)}
                shadow={n._v_name:n for n in new.root.data
                        if isinstance(n,tables.Table)}
                if any(CODE.fullmatch(n) is None or not n.startswith(m.upper())
                       for n in shadow):
                    raise ValueError("Modern mirror has invalid A-share table names")
                original_non_mirror_stocks+=len(set(existing)-set(shadow))
                for sym in sorted(shadow):
                    fresh=shadow[sym].read()
                    modern_rows=convert_records(fresh,dtype,np)
                    modern_tables+=1
                    try:
                        previous=existing[sym].read()
                    except KeyError:
                        previous=np.empty(0,dtype=dtype)
                    combined,counts=merge_stock(previous,modern_rows,np,dtype)
                    for key,value in counts.items():
                        stats[key]+=int(value)
                    # Fresh TABLE is built in the COPIED H5, then the old
                    # same-symbol node is replaced. The original is untouched.
                    scratch=target.create_table(
                        "/data","_rebuild_"+sym,description=dtype,
                        title=sym,expectedrows=len(combined),
                        filters=tables.Filters(
                            complevel=5,complib="zlib",shuffle=True))
                    for pos in range(0,len(combined),16384):
                        scratch.append(combined[pos:pos+16384])
                    scratch.flush()
                    if int(scratch.nrows)!=len(combined):
                        raise ValueError("Incomplete rebuilt native DAY TABLE")
                    if sym in existing:
                        target.remove_node("/data",sym)
                    target.rename_node(scratch,sym)
                    actual=target.get_node("/data/"+sym)
                    if (actual.dtype!=dtype or
                            int(actual.nrows)!=len(combined)
                            or actual.read().tobytes()!=combined.tobytes()):
                        raise ValueError("Full original+Parquet native DAY record mismatch")
                    native_rows+=len(combined)
                target.flush()
            if sha(modern_dir/name)!=sha_map[name]:
                raise ValueError("Audited original 16-year native mirror changed")
            if (old_files[m].stat().st_size,old_files[m].stat().st_mtime_ns,
                    sha(old_files[m]))!=old_status[m]:
                raise ValueError("Original Hikyuu native DAY source changed")
            print("DONE_ISOLATED_H5_DAY_MARKET="+m.upper()+
                  " MODERN_TABLES="+str(len(shadow)),flush=True)
        if stats["purchased_first_modern_records"]!=MODERN_COUNT:
            raise ValueError("Native day modern 16-year row total not conserved")
        output={
            "format":VERSION,
            "status":SAFE_STATUS,
            "source_original_hikyuu_h5_before_and_after_full_sha_checked":True,
            "source_modern_native_h5_full_sha256_verified":True,
            "modern_source_safe_sha256":source_safe_sha,
            "modern_purchased_first_2011_2026_rows":int(stats[
                "purchased_first_modern_records"]),
            "preserved_original_native_1990_2010_rows_in_overlapping_A_share_stocks":
                int(stats["original_historical_pre2011_preserved"]),
            "original_h5_2011_plus_only_native_keys_preserved":int(stats[
                "original_post2010_no_purchased_key_preserved"]),
            "original_h5_2011_plus_same_keys_overridden_from_parquet":int(stats[
                "original_post2010_replaced_by_purchased"]),
            "other_original_H5_stock_tables_retained_unmodified":int(
                original_non_mirror_stocks),
            "modern_native_stock_tables":int(modern_tables),
            "new_native_records_in_rebuilt_tables":int(native_rows),
            "native_full_table_readback_in_copied_h5":True,
            "new_h5_files_sha256":{
                p.name:sha(p) for p in sorted(dest.glob("*_day.h5"))},
            "three_native_hikyuu_day_files":3,
            "historical_original_native_rows_discarded":0,
            "original_hikyuu_h5_or_purchased_parquet_modified":False,
            "production_h5_active_replacement_performed":False,
            "numeric_parquet_to_native_H5_vendor_equivalence_certified":False,
            "native_hikyuu_cpp_full_market_read_verified":False,
            "ready_for_production_h5_swap":False,
            "written_ohlcva_or_stock_keys_in_safe":False,
        }
        safe.write_text(json.dumps(output,indent=2,sort_keys=True)+"\n",
                        encoding="utf-8")
        print("PASS_ISOLATED_HIKYUU_FULL_DAY_ORIGINAL_PLUS_PARQUET_MIRROR="+
              json.dumps({
                  "status":SAFE_STATUS,
                  "new_native_h5_files":3,
                  "private_modern_day_rows":MODERN_COUNT,
                  "original_market_modified":False,
                  "new_h5_directory":str(dest),
                  "safe_report":str(safe),
              },sort_keys=True),flush=True)
        return output
    except Exception:
        # Failed isolated output is deliberately retained for diagnosis.
        # No successful SAFE exists and the original market stays unchanged.
        print("INCOMPLETE_ISOLATED_DAY_H5; ORIGINAL_MARKET_UNCHANGED",
              flush=True)
        raise

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--modern-day-safe",type=Path,required=True)
    p.add_argument("--modern-day-h5-root",type=Path,required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--write-isolated-complete-day",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        mirror(a.root,a.modern_day_safe,a.modern_day_h5_root,a.run_id,a.out)
    except (OSError,ValueError,TypeError,KeyError,ImportError,RuntimeError) as exc:
        last=traceback.extract_tb(exc.__traceback__)[-1]
        p.error("Complete native DAY H5 copied-file merge REFUSED ["+
                type(exc).__name__+"/"+last.name+":"+str(last.lineno)+
                "]; original Hikyuu H5 never opened for writing")

if __name__=="__main__":
    main()
