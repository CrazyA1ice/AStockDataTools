#!/usr/bin/env python3
"""One-time versioned correction of OLD SHA-verified 2026-10-13 private H5
minute Parquet time labels. Reads already staged native integers/Float64:
1min OLD candidate key = native H5 END - 1minute; corrected key = END.
5min keeps native END - 5minutes. No D:/stock access, no re-scan of H5.

Creates NEW work/unified_parquet/minute_gap_staging/<id>/{1min,5min}/date
and NEW aggregate SAFE. Does not modify the old 1.598m Parquet, existing
6.4m mirror, vendor sources or pointers. Correction is NOT certification
of native/purchased vendor time semantics.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import shutil
import traceback
from datetime import datetime,timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
WORK=MODULE/"work"/"unified_parquet"/"minute_gap_staging"
VERSION="AStockDataTools versioned H5 minute END-label rekey from old candidate Parquet v1"

def load(tag,name):
    spec=importlib.util.spec_from_file_location(tag,HERE/name)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

M=load("minute_rekey_source_mirror","mirror-h5-origin-private-minute-parquet-to-native-h5.py")
S=M.STAGE

def sha(path):
    return M.sha(path)

def rekey(old_safe,run_id,out):
    import pyarrow as pa
    import pyarrow.parquet as pq
    if type(run_id) is not str or M.RUN.fullmatch(run_id) is None:
        raise ValueError("Require fresh isolated 12hex migration run id")
    dest=WORK/run_id
    report=Path(out)
    if (any(p.is_symlink() for p in (
            MODULE/"work",WORK,REPORTS,dest,report))
            or dest.exists() or report.exists()
            or dest.resolve().parent!=WORK.resolve()
            or report.resolve().parent!=REPORTS.resolve()
            or report.suffix!=".json"):
        raise ValueError("Migration only writes NEW private Parquet and reports")
    old,day,sources=M.selected_source(old_safe)
    if (old.get("format")!=S.FORMAT
            or set(old.get("period_results",{}))!=set(S.PERIODS)):
        raise ValueError("Old H5 minute SAFE not recognized")
    periods=old["period_results"]
    for period,expected in (("1min",1),("5min",5)):
        record=periods[period]
        if (record.get("h5_time_convention_source_end_to_candidate_parquet_start_minutes")
                !=expected
                or record.get("standardized_minute_key_contract") is not None
                or record.get("minute_time_alignment_vendor_certified") is not False):
            raise ValueError("Only old unaligned end-minus-1 minute H5 staging may migrate")
    work=WORK/run_id
    new_records={}
    work.mkdir(parents=True,exist_ok=False)
    try:
        for period in S.PERIODS:
            original,meta=sources[period]
            p=work/period/(day.isoformat()+".parquet")
            p.parent.mkdir()
            if period=="5min":
                with original.open("rb") as oldfile,p.open("xb") as newfile:
                    shutil.copyfileobj(oldfile,newfile,1024*1024)
                if sha(p)!=meta["private_parquet_sha256"]:
                    raise ValueError("Unchanged 5min Parquet copy lost source SHA")
            else:
                expected={}
                for native in S.session_stamps(day,period):
                    label=datetime.strptime(str(native),"%Y%m%d%H%M").replace(
                        tzinfo=S.CORE.UTC8)
                    expected[native]=int(label.timestamp()*1000)
                fields=S.schema(pa)
                count=0
                with pq.ParquetFile(original,memory_map=False,pre_buffer=False) as reader:
                    if (reader.schema_arrow!=fields
                            or reader.metadata.num_rows!=meta["private_parquet_rows"]):
                        raise ValueError("Old H5 1min source rows/schema disagree")
                    with pq.ParquetWriter(p,fields,compression="zstd") as writer:
                        for batch in reader.iter_batches(
                                batch_size=32768,use_threads=False):
                            native=batch.column(
                                batch.schema.get_field_index("h5_native_datetime")
                            ).to_pylist()
                            older=batch.column(
                                batch.schema.get_field_index("ts")
                            ).to_pylist()
                            shifted=[]
                            for label,prior in zip(native,older):
                                new=expected.get(label)
                                if (new is None or type(prior) is not int
                                        or prior!=new-60000):
                                    raise ValueError("Old H5 1min label does not match -1-minute provenance")
                                shifted.append(new)
                            batch=batch.set_column(
                                batch.schema.get_field_index("ts"),
                                pa.field("ts",pa.int64(),nullable=False),
                                pa.array(shifted,type=pa.int64()))
                            writer.write_batch(batch,row_group_size=32768)
                            count+=batch.num_rows
                if count!=meta["private_parquet_rows"]:
                    raise ValueError("H5 1min rekey row conservation failed")
            with pq.ParquetFile(p,memory_map=False,pre_buffer=False) as reader:
                if (reader.metadata.num_rows!=meta["private_parquet_rows"]
                        or reader.schema_arrow!=S.schema(pa)):
                    raise ValueError("Rekey destination source schema/rows disagree")
                # Full H5 native timestamp and normalized identity check.
                num=0
                offset=0 if period=="1min" else 5
                for batch in reader.iter_batches(
                        batch_size=32768,use_threads=False,
                        columns=["ts","h5_native_datetime","symbol","period"]):
                    vals=batch.to_pydict()
                    for ts,native,symbol,period_value in zip(
                            vals["ts"],vals["h5_native_datetime"],
                            vals["symbol"],vals["period"]):
                        d=datetime.strptime(str(native),"%Y%m%d%H%M").replace(
                            tzinfo=S.CORE.UTC8)
                        if (ts!=int((d-timedelta(minutes=offset)).timestamp()*1000)
                                or period_value!=period
                                or not symbol.startswith(("SH","SZ","BJ"))):
                            raise ValueError("Rekey native H5 minute full readback mismatches")
                        num+=1
                if num!=meta["private_parquet_rows"]:
                    raise ValueError("Rekey readback lost minute bars")
            new=dict(meta)
            new["private_parquet_relative_file"]=p.relative_to(MODULE).as_posix()
            new["private_parquet_sha256"]=sha(p)
            new["h5_time_convention_source_end_to_candidate_parquet_start_minutes"]=offset
            new["standardized_minute_key_contract"]=(
                "native_1min_end_equals_purchased_1min_end" if period=="1min"
                else "native_5min_end_minus_5_equals_purchased_5min_start")
            new_records[period]=new
            print("Rekey/copy actual private H5 minute Parquet:",
                  period,"rows:",num,flush=True)
        receipt={
            "format":S.FORMAT,
            "source_day":day.isoformat(),
            "period_results":new_records,
            "source_legacy_stage_safe_sha256":sha(Path(old_safe)),
            "h5_1min_stored_native_end_key_preserved":True,
            "h5_5min_stored_native_end_minus_five_key_preserved":True,
            "original_market_files_modified":False,
            "production_or_private_pointer_modified":False,
            "all_private_outputs_written_not_merged":True,
        }
        payload=json.dumps(receipt,sort_keys=True,indent=2)+"\n"
        with report.open("x",encoding="utf-8",newline="\n") as fp:
            fp.write(payload)
        return receipt
    except Exception:
        print("Original staged Parquet unchanged; incomplete NEW rekey files retained",
              flush=True)
        raise

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-stage-safe",type=Path,required=True)
    parser.add_argument("--run-id",required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--rekey-private-h5-minute-parquet",action="store_true",required=True)
    a=parser.parse_args(argv)
    try:
        doc=rekey(a.old_stage_safe,a.run_id,a.out)
        print("PASS: H5-origin 1min native END labels normalized to purchased 1min keys")
        print("1min rows:",doc["period_results"]["1min"]["private_parquet_rows"])
        print("5min rows:",doc["period_results"]["5min"]["private_parquet_rows"])
        print("Original vendor and previous private files unchanged; SAFE:",a.out)
    except Exception as ex:
        loc=traceback.extract_tb(ex.__traceback__)[-1]
        parser.error("Private minute end-label rekey incomplete ["+
                     type(ex).__name__+"/"+loc.name+":"+str(loc.lineno)+
                     "]; original vendor/previous private snapshots unchanged")

if __name__=="__main__":
    main()
