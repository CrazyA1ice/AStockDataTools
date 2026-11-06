#!/usr/bin/env python3
"""Read-only root-cause drilldown of H5 historical private daily VWAP exceptions.

Inspect 1990..2010 pre-verified private parquet WITHOUT modifying any source.
Focus exception records by year/month, venue/code prefix, security concentration
and possible x10/x100 ratio hypotheses. Never infer historical units or approve
production. Omit raw prices, trades, precise dates and source paths.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "pre2011_full_original_private_readonly_inventory_for_attribution",
    HERE/"audit-original-h5-pre2011-private-21-year-day-readonly.py")
FULL=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FULL)

UTC8=timezone(timedelta(hours=8))
BATCH=16384
# Multipliers applied ONLY to the diagnosed implied price, NOT to source data.
ALTERNATIVE_MULTIPLIERS=(("0.01",0.01),("0.1",0.1),("10",10.0),
                         ("100",100.0),("1000",1000.0))
DIRECTION=("below_low","above_high")
TOP=12
MAX_YEARS_PER_RUN=7


def _symbol_alias(symbol):
    # Nonreversible presentation not claimed: A-share code space is small.
    # This avoids casual exposure of raw security identifiers in public logs.
    return hashlib.sha256(symbol.encode("ascii")).hexdigest()[:12]


def _symbol_prefix(symbol):
    code,venue=symbol.split(".")
    market={"XSHG":"SH","XSHE":"SZ","XBSE":"BJ"}[venue]
    return market+code[:3]


def _yearly(year,folder,source_state):
    import numpy as np
    import pyarrow.parquet as pq

    parquet,manifest=FULL._check_manifest(year,folder,*source_state)
    expected,_,expected_symbols,expected_days=FULL._expected(year)
    pf=pq.ParquetFile(str(parquet))
    schema=FULL.ANNUAL._candidate_schema()
    if (pf.schema_arrow!=schema or pf.metadata.num_rows!=expected
            or not 1<=pf.metadata.num_row_groups<=10000):
        raise ValueError("Private historical anomaly attribution schema/count invalid")
    totals=Counter()
    by_month=defaultdict(Counter)
    by_prefix=defaultdict(Counter)
    by_symbol=defaultdict(Counter)
    by_day=defaultdict(Counter)
    day_candidate=Counter()
    day_positive=Counter()
    day_prefix_candidate=Counter()
    day_prefix_positive=Counter()
    day_prefix_outliers=defaultdict(Counter)
    factors=Counter()
    by_prefix_factors=defaultdict(Counter)
    checked=0
    for batch in pf.iter_batches(batch_size=BATCH,
            columns=["ts","symbol","low","high","close","volume","amount"],
            use_threads=False):
        if batch.num_rows<1 or checked+batch.num_rows>expected or any(
                batch.column(i).null_count for i in range(7)):
            raise ValueError("Private historical anomaly attribution batch invalid")
        dates=batch.column(0).to_numpy(zero_copy_only=False)
        syms=batch.column(1).to_pylist()
        low,high,close,volume,amount=[
            batch.column(i).to_numpy(zero_copy_only=False)
            for i in range(2,7)]
        if (np.any((dates+28800000)%86400000!=0)
                or any(not np.all(np.isfinite(v))
                       for v in (low,high,close,volume,amount))
                or np.any(low<=0) or np.any(high<low)
                or np.any(close<low-1e-8) or np.any(close>high+1e-8)
                or np.any(volume<0) or np.any(amount<0)):
            raise ValueError("Anomaly attribution encountered invalid daily OHLCVA/key")
        positive=(volume>0)&(amount>0)
        for key,n in zip(*np.unique(dates,return_counts=True)):
            day_candidate[int(key)]+=int(n)
        if np.any(positive):
            for key,n in zip(*np.unique(dates[positive],return_counts=True)):
                day_positive[int(key)]+=int(n)
        # For each selected historical session, retain the denominator
        # by market/code prefix; never guess unit factors or write rows.
        for ts,sym,is_positive in zip(dates,syms,positive):
            if not isinstance(sym,str):
                raise ValueError("Noncanonical symbol encountered in source denominator")
            import re
            if not re.fullmatch(r"\d{6}\.(XSHG|XSHE|XBSE)",sym):
                raise ValueError("Invalid daily security key in market denominator")
            prefix=_symbol_prefix(sym)
            group=(int(ts),prefix)
            day_prefix_candidate[group]+=1
            if is_positive:
                day_prefix_positive[group]+=1
        totals["positive_volume_and_amount"]+=int(np.count_nonzero(positive))
        totals["both_zero"]+=int(np.count_nonzero((volume==0)&(amount==0)))
        totals["only_volume_zero"]+=int(np.count_nonzero((volume==0)&(amount>0)))
        totals["only_amount_zero"]+=int(np.count_nonzero((volume>0)&(amount==0)))
        # Full 21-year SHA and source gates are rechecked for each annual file;
        # selected records are grouped only if exception vs candidate price range.
        indices=np.flatnonzero(positive)
        if len(indices):
            implied=amount[indices]/volume[indices]
            lo=low[indices]
            hi=high[indices]
            tolerance=np.maximum(0.01,hi*1e-8)
            under=implied<lo-tolerance
            over=implied>hi+tolerance
            totals["inside_bar"]+=int(len(indices)-np.count_nonzero(under|over))
            totals["below_low"]+=int(np.count_nonzero(under))
            totals["above_high"]+=int(np.count_nonzero(over))
            for sub_index,flag_low,flag_high,raw_vwap in zip(
                    indices,under,over,implied):
                if not flag_low and not flag_high:
                    continue
                s=syms[int(sub_index)]
                if not isinstance(s,str):
                    raise ValueError("Source code was not canonical text")
                import re
                if not re.fullmatch(r"\d{6}\.(XSHG|XSHE|XBSE)",s):
                    raise ValueError("Anomaly attribution source code invalid")
                dt=datetime.fromtimestamp(int(dates[int(sub_index)])/1000,UTC8)
                if dt.year!=year:
                    raise ValueError("Anomaly attribution timestamp outside year")
                month=f"{year:04d}-{dt.month:02d}"
                direction="below_low" if flag_low else "above_high"
                by_month[month][direction]+=1
                by_prefix[_symbol_prefix(s)][direction]+=1
                by_symbol[s][direction]+=1
                by_day[int(dates[int(sub_index)])][direction]+=1
                day_prefix_outliers[
                    (int(dates[int(sub_index)]),_symbol_prefix(s))][direction]+=1
                # Independent scale hypotheses on ONLY the outlier records.
                # Several factors can fit a wide bar; no auto-picking or writes.
                candidates=[]
                low_price=float(low[int(sub_index)])
                high_price=float(high[int(sub_index)])
                eps=max(0.01,high_price*1e-8)
                for label,f in ALTERNATIVE_MULTIPLIERS:
                    scaled=float(raw_vwap)*f
                    if low_price-eps<=scaled<=high_price+eps:
                        candidates.append(label)
                        factors[label]+=1
                prefix=_symbol_prefix(s)
                for factor in candidates:
                    by_prefix_factors[prefix][factor]+=1
                if not candidates:
                    factors["none_fit"]+=1
                    by_prefix_factors[prefix]["none_fit"]+=1
                elif len(candidates)>1:
                    factors["multiple_fit"]+=1
                    by_prefix_factors[prefix]["multiple_fit"]+=1
                else:
                    factors["one_fit"]+=1
                    by_prefix_factors[prefix]["one_fit"]+=1
        checked+=batch.num_rows
    expected_positive=totals["positive_volume_and_amount"]
    outliers=totals["below_low"]+totals["above_high"]
    if (checked!=expected or
            sum(totals[k] for k in ("positive_volume_and_amount",
               "both_zero","only_amount_zero","only_volume_zero"))!=checked
            or totals["inside_bar"]+outliers!=expected_positive
            or sum(factors[k] for k in ("none_fit","one_fit","multiple_fit"))!=outliers
            or sum(sum(item.values()) for item in by_symbol.values())!=outliers
            or sum(sum(item.values()) for item in by_month.values())!=outliers
            or sum(sum(item.values()) for item in by_prefix.values())!=outliers
            or sum(sum(item.values()) for item in by_day.values())!=outliers
            or sum(day_candidate.values())!=checked
            or sum(day_positive.values())!=expected_positive
            or sum(day_prefix_candidate.values())!=checked
            or sum(day_prefix_positive.values())!=expected_positive
            or sum(sum(item.values()) for item in day_prefix_outliers.values())!=outliers
            or set(by_day)-set(day_candidate)
            or sum(counter["none_fit"] for counter in by_prefix_factors.values())!=factors["none_fit"]
            or sum(counter["one_fit"] for counter in by_prefix_factors.values())!=factors["one_fit"]
            or sum(counter["multiple_fit"] for counter in by_prefix_factors.values())!=factors["multiple_fit"]
            or FULL.P90._digest(parquet)!=manifest["private_parquet_sha256"]):
        raise ValueError("Anomaly attribution full annual count/SHA/conservation failed")
    group_symbols=sorted(by_symbol.items(),
                         key=lambda pair:(-sum(pair[1].values()),pair[0]))
    busiest_days=sorted(by_day.items(),
                       key=lambda pair:(-sum(pair[1].values()),pair[0]))
    top_days=[]
    for native_ts,counts in busiest_days[:TOP]:
        dt=datetime.fromtimestamp(native_ts/1000,UTC8)
        anomalies=sum(counts.values())
        possible=day_positive[native_ts]
        if not 0<anomalies<=possible<=day_candidate[native_ts]:
            raise ValueError("Invalid same-day anomalous stockday concentration")
        prefix_stats=[]
        for (ts,prefix),day_count in sorted(day_prefix_candidate.items()):
            if ts!=native_ts:
                continue
            eligible=day_prefix_positive[(ts,prefix)]
            anomalous=day_prefix_outliers[(ts,prefix)]
            affected=sum(anomalous.values())
            if not 0<=affected<=eligible<=day_count:
                raise ValueError("Invalid market/code-prefix session denominators")
            prefix_stats.append({
                "code_prefix":prefix,
                "candidate_stockdays":day_count,
                "positive_volume_amount":eligible,
                "outliers":affected,
                "below_low":anomalous["below_low"],
                "above_high":anomalous["above_high"],
            })
        if (sum(x["candidate_stockdays"] for x in prefix_stats)!=day_candidate[native_ts]
                or sum(x["positive_volume_amount"] for x in prefix_stats)!=possible
                or sum(x["outliers"] for x in prefix_stats)!=anomalies):
            raise ValueError("Market/session breakdown did not conserve stockdays")
        top_days.append({
            "prefix_diagnostic":prefix_stats,
            "month":f"{year:04d}-{dt.month:02d}",
            "day_sha256_prefix12":hashlib.sha256(
                dt.strftime("%Y%m%d").encode("ascii")).hexdigest()[:12],
            "candidate_stockdays_that_session":day_candidate[native_ts],
            "positive_volume_amount_that_session":possible,
            "outliers_that_session":anomalies,
            "below_low":counts["below_low"],
            "above_high":counts["above_high"],
            "outlier_share_among_positive_pct_2dp":round(
                anomalies*100.0/possible,2),
        })
    return {
        "year":year,"candidate_stockdays_checked":checked,
        "positive_volume_and_amount":expected_positive,
        "vwap_inside_bar":totals["inside_bar"],
        "vwap_below_low":totals["below_low"],
        "vwap_above_high":totals["above_high"],
        "outliers_total":outliers,
        "zero_cases":{k:totals[k] for k in (
            "both_zero","only_volume_zero","only_amount_zero")},
        "outliers_by_month":{k:dict(v) for k,v in sorted(by_month.items())},
        "outliers_by_code_prefix":{k:dict(v) for k,v in sorted(by_prefix.items())},
        "outlier_multipliers_by_code_prefix":{k:dict(sorted(v.items())) for k,v in sorted(by_prefix_factors.items())},
        "number_of_sessions_with_outliers":len(by_day),
        "top_anomalous_sessions":top_days,
        "candidate_multipliers_fitting_outliers":dict(sorted(factors.items())),
        "unique_symbols_with_outliers":len(by_symbol),
        "top_anomalous_symbols":[
            {"symbol_sha256_prefix12":_symbol_alias(s),
             "code_prefix":_symbol_prefix(s),
             "outlier_rows":sum(k.values()),
             "below_low":k["below_low"],
             "above_high":k["above_high"]}
            for s,k in group_symbols[:TOP]],
        "source_state_and_private_sha_verified":True,
        "manual_unit_inference_required":True,
    }


def analyze(root,first=1990,last=1996):
    if (not isinstance(first,int) or isinstance(first,bool)
            or not isinstance(last,int) or isinstance(last,bool)
            or not 1990<=first<=last<=2010
            or last-first+1>MAX_YEARS_PER_RUN):
        raise ValueError("Anomaly attribution accepts at most 7 contiguous 1990-2010 years")
    original=Path(root).resolve()
    source=FULL._source_gate(original)
    folders=FULL._private_paths()
    years=[]
    grand=Counter()
    factor_sum=Counter()
    for year in range(first,last+1):
        print(f"PRIVATE_H5_VWAP_ATTRIBUTION_VERIFYING={year}",flush=True)
        row=_yearly(year,folders[year],source)
        years.append(row)
        grand.update({
            "candidate_stockdays_checked":row["candidate_stockdays_checked"],
            "positive_volume_and_amount":row["positive_volume_and_amount"],
            "vwap_inside_bar":row["vwap_inside_bar"],
            "vwap_below_low":row["vwap_below_low"],
            "vwap_above_high":row["vwap_above_high"],
            "outliers_total":row["outliers_total"],
        })
        factor_sum.update(row["candidate_multipliers_fitting_outliers"])
        print("PRIVATE_H5_VWAP_ATTRIBUTION_YEAR="+json.dumps(
            row,sort_keys=True,separators=(",",":")),flush=True)
    if FULL._source_gate(original)!=source:
        raise ValueError("Original H5/PQ source changed after private anomaly attribution")
    expected=sum(FULL._expected(y)[0] for y in range(first,last+1))
    if grand["candidate_stockdays_checked"]!=expected:
        raise ValueError("Attribution target year range did not conserve candidates")
    result={
        "state":"pre2011_private_h5_vwap_outlier_readonly_attribution_not_unit_certification",
        "first_year":first,"last_year":last,"years_verified":len(years),
        "aggregate":dict(grand),
        "candidate_multipliers_fitting_outliers":dict(factor_sum),
        "factors_are_competing_hypotheses_not_auto_repair":True,
        "all_source_stats_and_private_sha_rechecked":True,
        "original_h5_redecoded_again_by_attribution":False,
        "h5_volume_amount_price_units_certified":False,
        "official_adjustment_semantics_certified":False,
        "historical_security_master_certified":False,
        "source_or_private_files_modified":False,
        "production_activated":False,
        "ready_for_production_merge":False,
    }
    print("PRIVATE_H5_VWAP_ATTRIBUTION_SUMMARY="+json.dumps(
        result,sort_keys=True,separators=(",",":")),flush=True)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--from-year",type=int,default=1990)
    p.add_argument("--through-year",type=int,default=1996)
    args=p.parse_args(argv)
    analyze(args.source_root,args.from_year,args.through_year)


if __name__=="__main__":
    main()
