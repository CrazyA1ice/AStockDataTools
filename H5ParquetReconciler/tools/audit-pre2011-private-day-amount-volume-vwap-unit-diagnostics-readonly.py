#!/usr/bin/env python3
"""1990..2010 historical H5 private day: read-only turnover/volume/price diagnostic.

Only measures internally implied traded price = amount / volume for existing
private candidate bars and checks if it falls within that bar's [low,high].
This is diagnostic evidence about candidate scales, NOT vendor physical-unit
certification, security-master, adjusted/unadjusted interpretation or a
production gate. Never rewrites even a private candidate or creates reports.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "historical_private_21_year_independent_quality_source",
    HERE/"audit-original-h5-pre2011-private-21-year-day-readonly.py")
FULL=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FULL)

START=1990
END=2010
ROW_BATCH=16384
SCALES=(("0.01",0.01),("0.1",0.1),("1",1.0),
        ("10",10.0),("100",100.0),("1000",1000.0))
CATEGORIES=(
    "positive_volume_and_amount",
    "both_zero",
    "only_volume_zero",
    "only_amount_zero",
    "vwap_inside_bar",
    "vwap_below_low",
    "vwap_above_high",
    "ratio_not_near_candidate",
)


def _zero_counts():
    result={name:0 for name in CATEGORIES}
    result["ratio_near_factors_within_5pct"]={label:0 for label,_ in SCALES}
    return result


def _check_year(year,path,source_state):
    import numpy as np
    import pyarrow.parquet as pq

    original,info=FULL._check_manifest(year,path,*source_state)
    expected=FULL._expected(year)[0]
    pf=pq.ParquetFile(str(original))
    schema=FULL.ANNUAL._candidate_schema()
    if (pf.schema_arrow!=schema or pf.metadata.num_rows!=expected
            or not 1<=pf.metadata.num_row_groups<=10000):
        raise ValueError("Yearly internal price-volume-amount schema/rows invalid")
    counters=_zero_counts()
    checked=0
    for batch in pf.iter_batches(
            batch_size=ROW_BATCH,
            columns=["low","high","close","volume","amount"],
            use_threads=False):
        if (batch.num_rows<1 or checked+batch.num_rows>expected
                or any(batch.column(i).null_count for i in range(5))):
            raise ValueError("Incomplete or null trade-unit diagnostic annual batch")
        low,high,close,volume,amount=[
            batch.column(i).to_numpy(zero_copy_only=False)
            for i in range(5)]
        if (not all(np.all(np.isfinite(x)) for x in
                    (low,high,close,volume,amount))
                or np.any(low<=0) or np.any(high<=0) or np.any(close<=0)
                or np.any(high<low) or np.any(close<low-1e-8)
                or np.any(close>high+1e-8)
                or np.any(volume<0) or np.any(amount<0)):
            raise ValueError("Unsafe OHLCVA input for candidate trade-unit diagnostics")
        positive=(volume>0)&(amount>0)
        bothzero=(volume==0)&(amount==0)
        onlyvolume=(volume==0)&(amount>0)
        onlyamount=(volume>0)&(amount==0)
        counters["positive_volume_and_amount"]+=int(np.count_nonzero(positive))
        counters["both_zero"]+=int(np.count_nonzero(bothzero))
        counters["only_volume_zero"]+=int(np.count_nonzero(onlyvolume))
        counters["only_amount_zero"]+=int(np.count_nonzero(onlyamount))
        if np.any(positive):
            implied=amount[positive]/volume[positive]
            lo=low[positive]
            hi=high[positive]
            cl=close[positive]
            tolerance=np.maximum(0.01,hi*1e-8)
            below=implied<lo-tolerance
            above=implied>hi+tolerance
            inside=~(below|above)
            counters["vwap_below_low"]+=int(np.count_nonzero(below))
            counters["vwap_above_high"]+=int(np.count_nonzero(above))
            counters["vwap_inside_bar"]+=int(np.count_nonzero(inside))
            ratios=implied/cl
            if not np.all(np.isfinite(ratios)):
                raise ValueError("Unbounded price/volume/amount candidate ratio")
            near=np.zeros(len(ratios),dtype=bool)
            for label,factor in SCALES:
                match=np.abs(ratios/factor-1)<=0.05
                counters["ratio_near_factors_within_5pct"][label]+=int(
                    np.count_nonzero(match))
                near|=match
            counters["ratio_not_near_candidate"]+=int(np.count_nonzero(~near))
        checked+=batch.num_rows
    if (checked!=expected
            or sum(counters[x] for x in (
                "positive_volume_and_amount","both_zero",
                "only_volume_zero","only_amount_zero"))!=expected
            or counters["vwap_inside_bar"]+counters["vwap_below_low"]+
               counters["vwap_above_high"]!=counters["positive_volume_and_amount"]
            or FULL.P90._digest(original)!=info["private_parquet_sha256"]):
        raise ValueError("Historical trade-unit annual candidate/manifest drift")
    return {"year":year,"private_candidate_stockdays_checked":checked,**counters}


def analyze(root,first=1990,last=2010):
    if (type(first) is not int or type(last) is not int
            or not START<=first<=last<=END):
        raise ValueError("Select exact inclusive 1990-2010 diagnostic year bounds")
    original=Path(root).resolve()
    before=FULL._source_gate(original)
    private=FULL._private_paths()
    total=_zero_counts()
    count=0
    years=[]
    for year in range(first,last+1):
        print(f"PRIVATE_H5_UNIT_DIAGNOSTIC_VERIFYING={year}",flush=True)
        result=_check_year(year,private[year],before)
        count+=result["private_candidate_stockdays_checked"]
        for name in CATEGORIES:
            total[name]+=result[name]
        for factor in total["ratio_near_factors_within_5pct"]:
            total["ratio_near_factors_within_5pct"][factor]+=result[
                "ratio_near_factors_within_5pct"][factor]
        years.append(result)
        print("PRIVATE_H5_UNIT_YEAR="+json.dumps(
            result,sort_keys=True,separators=(",",":")),flush=True)
    if FULL._source_gate(original)!=before:
        raise ValueError("Original H5/PQ file states drifted during unit diagnostic")
    if first==1990 and last==2010 and count!=FULL.EXPECTED_ALL_STOCKDAYS:
        raise ValueError("Full historical candidate trade-unit total did not conserve")
    result={
        "state":"private_h5_day_candidate_vwap_unit_consistency_diagnostic_only",
        "first_year":first,"last_year":last,
        "years_checked":len(years),"candidate_stockdays_checked":count,
        "aggregate":total,
        "all_years_source_sha_bound_and_private_sha_rechecked":True,
        "ratio_is_amount_divided_by_volume_times_close":True,
        "vwap_is_amount_divided_by_volume":True,
        "price_tolerance_yuan_abs_floor":0.01,
        "ratio_candidate_factor_5pct_bands_are_hypotheses":True,
        "detected_outliers_are_not_auto_removed":True,
        "h5_physical_amount_and_volume_units_certified":False,
        "official_adjustment_semantics_certified":False,
        "official_historical_security_master_certified":False,
        "production_merge_authorized":False,
        "source_market_files_modified":False,
        "historical_private_candidate_files_modified":False,
        "private_report_file_written":False,
    }
    print("PRIVATE_H5_UNIT_DIAGNOSTIC_SUMMARY="+json.dumps(
        result,sort_keys=True,separators=(",",":")),flush=True)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--from-year",type=int,default=START)
    p.add_argument("--through-year",type=int,default=END)
    a=p.parse_args(argv)
    analyze(a.source_root,a.from_year,a.through_year)


if __name__=="__main__":
    main()
