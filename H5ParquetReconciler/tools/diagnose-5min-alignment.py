#!/usr/bin/env python3
"""只读5min对齐诊断：选少量证券，对照0/+5/+10/-5分钟、OHLC以及量额比例。

报告只有计数、比例和不同字段名称，不导出付费行情OHLCV原值。
通过Parquet的symbol行组统计优先跳过不可能含所选证券的行组。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

SOURCE = Path(__file__).with_name("reconcile-local-a-share-h5-parquet.py")
_SPEC = importlib.util.spec_from_file_location("h5_parquet_reconcile_engine", SOURCE)
core = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(core)

DEFAULT_SYMBOLS = ("SH600000", "SZ000636", "SH603181", "SZ300747", "BJ920680")
TIME_SHIFTS = (-5, 0, 5, 10)
UNIT_MULTIPLIERS = (0.001, 0.01, 1, 100, 1000)
FIELDS = ("open", "high", "low", "close", "volume", "amount")


def source_spellings(symbol: str) -> set[str]:
    """Known source label variants, including the vendor's 600000.XSHG format."""
    if len(symbol) != 8 or not symbol[:2] in ("SH", "SZ", "BJ") or not symbol[2:].isdigit():
        raise ValueError("Symbol must be SH/SZ/BJ followed by six digits")
    venue, code = symbol[:2], symbol[2:]
    exchanges = {
        "SH": ("XSHG", "SH", "SHSE", "SSE"),
        "SZ": ("XSHE", "SZ", "SZSE"),
        "BJ": ("XBSE", "BJ", "BJSE", "BSE")
    }
    values = {symbol}
    for label in exchanges[venue]:
        values.update((f"{code}.{label}", f"{code}:{label}", f"{code}-{label}",
                       f"{label}{code}", f"{label}.{code}", f"{label}:{code}"))
    return values


def might_contain_symbols(row_group, aliases: set[str]) -> bool:
    """Conservative pruning: skip only when exact string ranges rule out all aliases."""
    for i in range(row_group.num_columns):
        col = row_group.column(i)
        if col.path_in_schema != "symbol":
            continue
        st = col.statistics
        if st is None or not st.has_min_max:
            return True
        low, high = st.min, st.max
        if isinstance(low, bytes) and isinstance(high, bytes):
            # UTF-8 strings are lexicographically ordered for ASCII ticker aliases.
            low = low.decode("utf-8", "replace")
            high = high.decode("utf-8", "replace")
        if not isinstance(low, str) or not isinstance(high, str) or low > high:
            return True
        return any(low <= raw <= high for raw in aliases)
    return True


def shift_bar_stamp(stamp: int, minutes: int) -> int:
    dt = datetime.strptime(str(stamp), "%Y%m%d%H%M") + timedelta(minutes=minutes)
    return int(dt.strftime("%Y%m%d%H%M"))


def close_enough(a: float, b: float, kind: str) -> bool:
    if kind == "price":
        return abs(a - b) <= 0.005
    if kind == "volume":
        return abs(a - b) <= max(1, 0.00001 * max(abs(a), abs(b)))
    if kind == "amount":
        return abs(a - b) <= max(1000, 0.001 * max(abs(a), abs(b)))
    raise ValueError("Unexpected kind")


def evaluate(h5_rows: dict, parquet_rows: dict, shifts=TIME_SHIFTS):
    """Input: {(symbol, YYYYMMDDHHMM): (O,H,L,C,V,A)}. Output: aggregate-only."""
    output = {}
    for lag in shifts:
        matched = 0
        all_four_prices_equal = 0
        each_price_field_diff = Counter()
        volume_fit = Counter({str(n): 0 for n in UNIT_MULTIPLIERS})
        amount_fit = Counter({str(n): 0 for n in UNIT_MULTIPLIERS})
        matched_by_symbol = Counter()
        for (symbol, ts), p in parquet_rows.items():
            h = h5_rows.get((symbol, shift_bar_stamp(ts, lag)))
            if h is None:
                continue
            matched += 1
            matched_by_symbol[symbol] += 1
            good = True
            for i, field in enumerate(FIELDS[:4]):
                if not close_enough(p[i], h[i], "price"):
                    each_price_field_diff[field] += 1
                    good = False
            if good:
                all_four_prices_equal += 1
            for factor in UNIT_MULTIPLIERS:
                if close_enough(p[4], h[4]*factor, "volume"):
                    volume_fit[str(factor)] += 1
                if close_enough(p[5], h[5]*factor, "amount"):
                    amount_fit[str(factor)] += 1
        output[str(lag)] = {
            "parquet_rows_selected": len(parquet_rows),
            "h5_rows_selected": len(h5_rows),
            "matched_bars": matched,
            "all_ohlc_equal_bars": all_four_prices_equal,
            "all_ohlc_equal_pct_of_matched": round(100*all_four_prices_equal/matched, 3) if matched else None,
            "different_price_field_counts": dict(each_price_field_diff),
            "volume_agreement_by_h5_multiplier": dict(volume_fit),
            "amount_agreement_by_h5_multiplier": dict(amount_fit),
            "matched_bars_by_symbol": dict(matched_by_symbol),
        }
    return output



def percentile(values, probability):
    """Nearest-rank-interpolated percentile on a small *aggregate* diagnostic sample."""
    if not values:
        return None
    sorted_values = sorted(values)
    pos = (len(sorted_values)-1)*probability
    left=int(pos)
    right=min(left+1,len(sorted_values)-1)
    return sorted_values[left] + (sorted_values[right]-sorted_values[left])*(pos-left)


def summarize_values(values, *, digits=5):
    """Do not persist per-row amounts/prices; quantiles only."""
    return {
        "count":len(values),
        "p10":round(percentile(values,0.1),digits) if values else None,
        "median":round(percentile(values,0.5),digits) if values else None,
        "p90":round(percentile(values,0.9),digits) if values else None,
        "max":round(max(values),digits) if values else None
    }


def attribute_differences(h5_rows: dict, parquet_rows: dict, shift=5):
    """Attribute the *matched* normalized bars without exposing original OHLCV.

    Time shift candidates were examined by evaluate(). This diagnostic uses
    the +5-minute working convention; it does not certify that convention.
    """
    result={}
    for sym in sorted({key[0] for key in h5_rows} | {key[0] for key in parquet_rows}):
        hcount=sum(1 for key in h5_rows if key[0]==sym)
        pcount=sum(1 for key in parquet_rows if key[0]==sym)
        fields={key:[] for key in FIELDS[:4]}
        relative_price_errors={key:[] for key in FIELDS[:4]}
        volumes=[]
        amounts=[]
        high_low_equal=all_equal=open_close_diff_high_low_equal=0
        segment_counts={"morning":{"matched":0,"ohlc_equal":0,"open_diff":0,"close_diff":0},
                        "afternoon":{"matched":0,"ohlc_equal":0,"open_diff":0,"close_diff":0},
                        "other":{"matched":0,"ohlc_equal":0,"open_diff":0,"close_diff":0}}
        vol_zeros={"h5_zero":0,"parquet_zero":0,"both_zero":0}
        amt_zeros={"h5_zero":0,"parquet_zero":0,"both_zero":0}
        open_boundary={"comparisons":0,"matches_previous_h5_close":0,
                       "matches_previous_parquet_close":0}
        close_boundary={"comparisons":0,"matches_next_h5_open":0,
                        "matches_next_parquet_open":0}
        matched=0
        for (symbol,t),p in parquet_rows.items():
            if symbol!=sym:
                continue
            bar_end=shift_bar_stamp(t,shift)
            h=h5_rows.get((sym,bar_end))
            if h is None:
                continue
            matched+=1
            clock=t%10000
            segment="morning" if 900 <= clock < 1200 else ("afternoon" if 1300 <= clock <= 1500 else "other")
            segment_counts[segment]["matched"]+=1
            flags=[]
            for i,key in enumerate(FIELDS[:4]):
                bad=not close_enough(p[i],h[i],"price")
                flags.append(bad)
                if bad:
                    err=abs(p[i]-h[i])
                    fields[key].append(err)
                    if max(abs(p[i]),abs(h[i]))>0:
                        relative_price_errors[key].append(err/max(abs(p[i]),abs(h[i])))
            if not any(flags):
                all_equal+=1
                segment_counts[segment]["ohlc_equal"]+=1
            if not flags[1] and not flags[2]:
                high_low_equal+=1
                if flags[0] or flags[3]:
                    open_close_diff_high_low_equal+=1
            if flags[0]:
                segment_counts[segment]["open_diff"]+=1
                previous_h=h5_rows.get((sym,t))
                previous_p=parquet_rows.get((sym,shift_bar_stamp(t,-5)))
                if previous_h is not None and previous_p is not None:
                    open_boundary["comparisons"]+=1
                    if close_enough(p[0],previous_h[3],"price"):
                        open_boundary["matches_previous_h5_close"]+=1
                    if close_enough(h[0],previous_p[3],"price"):
                        open_boundary["matches_previous_parquet_close"]+=1
            if flags[3]:
                segment_counts[segment]["close_diff"]+=1
                next_h=h5_rows.get((sym,shift_bar_stamp(bar_end,5)))
                next_p=parquet_rows.get((sym,shift_bar_stamp(t,5)))
                if next_h is not None and next_p is not None:
                    close_boundary["comparisons"]+=1
                    if close_enough(p[3],next_h[0],"price"):
                        close_boundary["matches_next_h5_open"]+=1
                    if close_enough(h[3],next_p[0],"price"):
                        close_boundary["matches_next_parquet_open"]+=1
            for index,accumulator,zero_stats in (
                (4,volumes,vol_zeros),(5,amounts,amt_zeros)):
                if h[index]==0:
                    zero_stats["h5_zero"]+=1
                if p[index]==0:
                    zero_stats["parquet_zero"]+=1
                if h[index]==0 and p[index]==0:
                    zero_stats["both_zero"]+=1
                if h[index]!=0 and math.isfinite(p[index]/h[index]):
                    accumulator.append(p[index]/h[index])
        result[sym]={
            "h5_bars":hcount,"parquet_bars":pcount,"matched_bars":matched,
            "both_ohlc_equal_bars":all_equal,
            "high_low_equal_bars":high_low_equal,
            "high_low_equal_but_open_or_close_diff":open_close_diff_high_low_equal,
            "price_abs_difference_quantiles":{field:summarize_values(vals, digits=4) for field,vals in fields.items()},
            "price_relative_difference_quantiles":{field:summarize_values(vals, digits=5) for field,vals in relative_price_errors.items()},
            "parquet_over_h5_volume_ratio":summarize_values(volumes,digits=5),
            "parquet_over_h5_amount_ratio":summarize_values(amounts,digits=5),
            "volume_zero_counts":vol_zeros,
            "amount_zero_counts":amt_zeros,
            "intraday_segments":segment_counts,
            "open_cross_boundary_checks":open_boundary,
            "close_cross_boundary_checks":close_boundary,
        }
    return result


def load_h5(root: Path, symbols: tuple[str, ...], day: date):
    import h5py

    lower,upper,_,_ = core.parse_day_range(day.year,day.isoformat(),day.isoformat())
    records = {}
    details = {}
    for sym in symbols:
        source = root/"HikyuuData"/f"{sym[:2].lower()}_5min.h5"
        details[sym] = {"h5_file_present": source.is_file(), "h5_rows": 0}
        if not source.is_file():
            continue
        with h5py.File(source,"r") as hf:
            ds = hf.get(f"data/{sym}")
            if not isinstance(ds,h5py.Dataset):
                continue
            left,right=core.h5_key_slice(ds,lower,upper)
            for x in ds[left:right]:
                t=int(x["datetime"])
                key=(sym,t)
                if key in records:
                    details[sym]["h5_duplicate_keys"]=details[sym].get("h5_duplicate_keys",0)+1
                    continue
                records[key]=(
                    float(x["openPrice"])/1000, float(x["highPrice"])/1000,
                    float(x["lowPrice"])/1000, float(x["closePrice"])/1000,
                    float(x["transCount"]), float(x["transAmount"])*1000)
                details[sym]["h5_rows"]+=1
    return records,details


def load_parquet(root: Path, symbols: tuple[str, ...], day: date, progress: bool,
                 allowed_groups=None):
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    _, _, lower_ms, upper_ms=core.parse_day_range(day.year,day.isoformat(),day.isoformat())
    aliases=set().union(*(source_spellings(sym) for sym in symbols))
    aliases_pa=pa.array(sorted(aliases),type=pa.string())
    records={}
    details=Counter()
    paths=core.year_files(root,"5min",day.year)
    started=time.monotonic()
    for path in paths:
        parquet=pq.ParquetFile(str(path))
        if not set(core.NEEDED).issubset(parquet.schema_arrow.names):
            raise ValueError(f"Parquet missing OHLCV columns: {path.name}")
        details["files"]+=1
        for idx in range(parquet.metadata.num_row_groups):
            details["row_groups_total"]+=1
            if allowed_groups is not None:
                # A completed and verified index lists exact row-groups that
                # contain the requested (symbol, day). Never skip based on an
                # unverified/incomplete index.
                known = allowed_groups.get(str(path.resolve()))
                if known is None:
                    raise ValueError("Indexed Parquet source missing from validated locator")
                if idx not in known:
                    details["row_groups_skipped_by_index"]+=1
                    continue
            rg=parquet.metadata.row_group(idx)
            if not core.row_group_overlaps_timestamp(rg,lower_ms,upper_ms):
                details["row_groups_skipped_by_time"]+=1
                continue
            if not might_contain_symbols(rg,aliases):
                details["row_groups_skipped_by_symbol"]+=1
                continue
            details["row_groups_read"]+=1
            for batch in parquet.iter_batches(row_groups=[idx],batch_size=131072,
                                              columns=list(core.NEEDED),use_threads=True):
                details["source_rows_in_scanned_groups"]+=batch.num_rows
                symarr=batch.column(1)
                try:
                    selected=pc.is_in(symarr,value_set=aliases_pa)
                    selected=pc.and_(selected,pc.greater_equal(batch.column(0),lower_ms))
                    selected=pc.and_(selected,pc.less(batch.column(0),upper_ms))
                    filtered=batch.filter(selected)
                    small=filtered.to_pylist()
                except (pa.ArrowInvalid,pa.ArrowNotImplementedError,TypeError):
                    # Preserve accuracy if a vendor uses dictionary/other Arrow symbol encodings.
                    small=[]
                    for row in batch.to_pylist():
                        if row["symbol"] in aliases and lower_ms<=int(row["ts"])<upper_ms:
                            small.append(row)
                for row in small:
                    sym=core.symbol_id(row["symbol"])
                    if sym not in symbols:
                        continue
                    stamp=core.pq_stamp(row["ts"],"1min")  # SOURCE bar-start; no +5 here
                    key=(sym,stamp)
                    values=tuple(float(row[k]) for k in FIELDS)
                    if not all(math.isfinite(v) for v in values):
                        details["nonfinite_rows"]+=1
                        continue
                    if key in records:
                        details["duplicate_keys"]+=1
                        continue
                    records[key]=values
                details["selected_source_rows"]+=len(small)
            if progress and (details["row_groups_read"]%25 == 0 or idx==parquet.metadata.num_row_groups-1):
                print(f"  Parquet selected-symbol groups read={details['row_groups_read']} "
                      f"skipped_symbol={details['row_groups_skipped_by_symbol']} "
                      f"skipped_time={details['row_groups_skipped_by_time']} "
                      f"selected_bars={len(records)} "
                      f"elapsed={time.monotonic()-started:.1f}s",flush=True)
    return records,dict(details)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path,help="Local source root, e.g. D:/stock")
    parser.add_argument("--date",required=True,help="Trading day: YYYY-MM-DD")
    parser.add_argument("--symbols",nargs="+",default=list(DEFAULT_SYMBOLS),
                        help="Up to 20 selected SH/SZ/BJ six-digit symbols")
    parser.add_argument("--out",type=Path,default=Path("reports")/"5min-alignment-diagnostics.json")
    parser.add_argument("--read-only",action="store_true",required=True)
    args=parser.parse_args(argv)
    try:
        day=date.fromisoformat(args.date)
        symbols=tuple(dict.fromkeys(sym.upper() for sym in args.symbols))
        if not 1<=len(symbols)<=20:
            raise ValueError("Provide 1..20 selected symbols")
        for sym in symbols:
            if core.symbol_id(sym)!=sym:
                raise ValueError(f"Invalid six-digit market ticker: {sym}")
        out,scratch=core.resolve_module_artifact_paths(args.out,None)
        root,_,_=core.resolve_safe_paths(args.root,out,scratch)
        if out.exists():
            raise ValueError(f"Output exists; choose a new report name: {out}")
        h5_rows,h5_details=load_h5(root,symbols,day)
        print(f"H5 selected bars: {len(h5_rows)}",flush=True)
        pq_rows,pq_details=load_parquet(root,symbols,day,True)
        print(f"Parquet selected bars: {len(pq_rows)}",flush=True)
        report={
            "format":"AStockDataTools 5min alignment diagnostics v2",
            "date":day.isoformat(),
            "symbols":list(symbols),
            "source_files_modified":False,
            "source_units_certified":False,
            "safe_to_automatically_union":False,
            "h5":h5_details,
            "parquet":pq_details,
            "lag_minutes_parquet_start_to_h5_end":evaluate(h5_rows,pq_rows),
            "working_shift_plus5_per_symbol_attribution":attribute_differences(h5_rows,pq_rows),
            "notes":[
                "Prices are compared with absolute tolerance 0.005 yuan; these are hypotheses, not certified data conventions.",
                "Volume/amount scaling results count matching rows under each H5 multiplier. No raw OHLCV values are exported.",
                "Parquet timestamps represent raw bar start in this report; lag=5 corresponds to existing audit start+5 rule.",
                "Row-group symbol-statistics pruning is conservative; a missing symbol min/max forces group scan.",
                "Only selected symbols and one day are analyzed. Never extrapolate percentages to all symbols.",
                "Price difference sizes and quantity ratios are aggregate-only quantiles. Ratios exclude zero H5 denominator; the number of excluded zero-volume/amount bars is shown separately.",
                "Cross-boundary open/close tests are exploratory; matching neighboring prices does not establish a canonical bar-construction rule."
            ]
        }
        out.parent.mkdir(parents=True,exist_ok=True)
        temp=out.with_name(out.name+".tmp")
        temp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        temp.replace(out)
        print(f"Saved {out}",flush=True)
    except (OSError,ValueError) as exc:
        parser.error(str(exc))


if __name__=="__main__":
    main()
