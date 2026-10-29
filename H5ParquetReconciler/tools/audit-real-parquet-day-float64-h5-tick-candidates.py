#!/usr/bin/env python3
"""Bounded, READ-ONLY purchased Parquet day float64 quantization hypothesis.

One explicit day/month Parquet, one date, two A-share symbols, <=150000
source rows. Never creates H5, never mutates the paid source, never exports
OHLCVA or individual raw timestamps, and NEVER certifies physical units.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

HERE=Path(__file__).resolve().parent


def import_local(name,relative):
    spec=importlib.util.spec_from_file_location(name,HERE/relative)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FOOTER=import_local("real_day_footer_source","probe-parquet-arrow-footer-schema-readonly.py")
AUDIT=FOOTER.AUDIT
FORMAT="AStockDataTools bounded real Parquet day float64 H5 tick hypotheses v1"
PREVIOUS_FORMAT="AStockDataTools Parquet int64 footer date-timebase candidates v1"
SYMBOLS=("SH600000","SZ000001")
FIELDS=("open","high","low","close","amount","volume")
NEEDED=("ts","symbol","open","high","low","close","amount","volume")
SCALINGS={"open":1000,"high":1000,"low":1000,"close":1000,
          "amount":10,"volume":1}
LIMITS={"open":(1<<32)-1,"high":(1<<32)-1,
        "low":(1<<32)-1,"close":(1<<32)-1,
        "amount":(1<<64)-1,"volume":(1<<64)-1}
MAX_ROWS=150000
UTC8=timezone(timedelta(hours=8))
# Source symbol spellings: exact, conservative A-share aliases.
ALIASES={"SH600000":frozenset(("SH600000","600000.XSHG","600000.SH",
                                "SH.600000","XSHG600000")),
         "SZ000001":frozenset(("SZ000001","000001.XSHE","000001.SZ",
                                "SZ.000001","XSHE000001"))}


def check_prior(path,month):
    doc=json.loads(AUDIT._path(path,True).read_text(encoding="utf-8"))
    if (type(doc) is not dict or doc.get("format")!=PREVIOUS_FORMAT
            or doc.get("sample_month")!=month
            or doc.get("three_periods_int64_date_footer_checked") is not True
            or doc.get("all_three_periods_unique_epoch_ms_footer_candidate") is not True
            or doc.get("date_raw_calendar_encoding_certified") is not False
            or doc.get("licensed_parquet_to_h5_mapping_certified") is not False
            or doc.get("ready_for_full_market_mirror") is not False
            or doc.get("footer_only_no_market_rows_loaded") is not True
            or type(doc.get("periods")) is not dict
            or set(doc["periods"])!=set(("day","5min","1min"))):
        raise ValueError("Existing epoch_ms candidate SAFE proof missing")
    for period in ("day","5min","1min"):
        row=doc["periods"][period]
        if (type(row) is not dict or row.get("period")!=period
                or row.get("date_arrow_storage_family")!="int64"
                or row.get("unique_epoch_ms_candidate_from_footer_only") is not True
                or row.get("full_nonempty_row_group_minmax_coverage") is not True
                or row.get("date_raw_calendar_encoding_certified") is not False):
            raise ValueError("Previous period date-stat evidence incomplete")
    return doc


def tick_hypothesis(value,field):
    """Hypothetical Hikyuu-driver units only; no physical unit conversion.

    Decimal(str(float)) captures the *shortest printed float*; it does NOT
    recover the upstream decimal source. Decimal.from_float records the exact
    binary64 representation, which often differs from the printed decimal.
    No rounded integer is written or exposed.
    """
    if type(value) is not float or not math.isfinite(value) or value<0:
        raise ValueError("Nonfinite, nonfloat or negative Parquet OHLCVA")
    scale=Decimal(SCALINGS[field])
    printed=Decimal(str(value))*scale
    maximum=Decimal(LIMITS[field])
    if printed>maximum:
        return {"range_ok":False,"shortest_decimal_tick_exact":False,
                "binary_float_tick_exact":False,"would_require_rounding":False,
                "half_tick_boundary":False}
    integral=printed.to_integral_value(rounding=ROUND_HALF_EVEN)
    binary=Decimal.from_float(value)*scale
    return {
        "range_ok":True,
        "shortest_decimal_tick_exact":printed==integral,
        "binary_float_tick_exact":binary==binary.to_integral_value(),
        "would_require_rounding":printed!=integral,
        "half_tick_boundary":abs(printed-integral)==Decimal("0.5"),
    }


def _make_field_summary():
    return {k:{"sampled_values":0,"shortest_decimal_tick_exact_count":0,
                "binary_float_tick_exact_count":0,
                "would_require_rounding_count":0,
                "half_tick_boundary_count":0,"range_overflow_count":0}
            for k in FIELDS}


def summarize_bars(bars):
    if type(bars) is not dict or set(bars)!=set(SYMBOLS):
        raise ValueError("Require exactly two selected securities")
    per_field=_make_field_summary()
    for symbol in SYMBOLS:
        row=bars[symbol]
        if type(row) is not dict or set(row)!=set(FIELDS):
            raise ValueError("Require six original float64 fields per symbol")
        for field in FIELDS:
            result=tick_hypothesis(row[field],field)
            dst=per_field[field]
            dst["sampled_values"]+=1
            dst["shortest_decimal_tick_exact_count"]+=int(
                result["shortest_decimal_tick_exact"])
            dst["binary_float_tick_exact_count"]+=int(
                result["binary_float_tick_exact"])
            dst["would_require_rounding_count"]+=int(
                result["would_require_rounding"])
            dst["half_tick_boundary_count"]+=int(
                result["half_tick_boundary"])
            dst["range_overflow_count"]+=int(not result["range_ok"])
    return per_field


def _range_ms(trading_day):
    if (type(trading_day) is not str or not re.fullmatch(
            r"20[0-9]{2}-(0[1-9]|1[0-2])-[0-3][0-9]",trading_day)):
        raise ValueError("Date must be ISO yyyy-mm-dd")
    d=date.fromisoformat(trading_day)
    start=datetime(d.year,d.month,d.day,tzinfo=UTC8)
    end=start+timedelta(days=1)
    return int(start.timestamp()*1000),int(end.timestamp()*1000)


def _read_bounded_daily(path,trading_day,pa,pq,pc):
    first=FOOTER.footer_guard(path)
    pf=None
    try:
        pf=pq.ParquetFile(str(path),memory_map=False,pre_buffer=False)
        schema=pf.schema_arrow
        if (not set(NEEDED).issubset(schema.names)
                or len(schema.names)>512
                or not pa.types.is_int64(schema.field("ts").type)
                or not pa.types.is_string(schema.field("symbol").type)
                or any(not pa.types.is_float64(schema.field(f).type)
                       for f in FIELDS)):
            raise ValueError("Expected verified int64 ts and float64 OHLCVA schema")
        groups=pf.metadata.num_row_groups
        if groups<1 or groups>32:
            raise ValueError("Day Parquet rowgroup budget exceeded")
        total=sum(pf.metadata.row_group(i).num_rows for i in range(groups))
        if total<1 or total>MAX_ROWS:
            raise ValueError("Day Parquet row count exceeds 150000 budget")
        low,high=_range_ms(trading_day)
        aliases={a:symbol for symbol,spellings in ALIASES.items()
                 for a in spellings}
        alias_values=pa.array(sorted(aliases),type=pa.string())
        selected={}
        scanned=0
        for group in range(groups):
            # Date-bound metadata pruning is a conservative optimization only.
            rowgroup=pf.metadata.row_group(group)
            if rowgroup.num_rows<0:
                raise ValueError("Invalid row group")
            for batch in pf.iter_batches(row_groups=[group],
                                         batch_size=16384,
                                         columns=list(NEEDED),
                                         use_threads=False):
                scanned+=batch.num_rows
                if scanned>MAX_ROWS:
                    raise ValueError("Day row scan budget exceeded")
                names={n:batch.column(i) for i,n in enumerate(NEEDED)}
                mask=pc.and_(pc.is_in(names["symbol"],
                                     value_set=alias_values),
                             pc.and_(pc.greater_equal(names["ts"],low),
                                     pc.less(names["ts"],high)))
                for item in batch.filter(mask).to_pylist():
                    symbol=aliases.get(item["symbol"])
                    if symbol is None:
                        raise ValueError("Unrecognized matched security")
                    if symbol in selected:
                        raise ValueError("Duplicate selected stock-day")
                    if type(item["ts"]) is not int:
                        raise ValueError("Timestamp is not int64")
                    row={f:item[f] for f in FIELDS}
                    if not all(type(v) is float and math.isfinite(v)
                               for v in row.values()):
                        raise ValueError("Invalid selected float64 row")
                    selected[symbol]=row
        if set(selected)!=set(SYMBOLS):
            raise ValueError("Missing required two day bars")
        return selected,scanned,groups
    except Exception:
        # Avoid PyArrow exception strings disclosing source file paths/values.
        raise ValueError("Cannot safely inspect bounded selected daily rows") from None
    finally:
        if pf is not None:
            pf.close()
        if FOOTER.footer_guard(path)!=first:
            raise ValueError("Source Parquet file changed during daily analysis")


def run(root,day_relative,trading_day,previous_timebase_safe,out):
    destination=AUDIT._path(out,False)
    month=trading_day[:7]
    _range_ms(trading_day)
    if not re.fullmatch(r"20[0-9]{2}-(0[1-9]|1[0-2])",month):
        raise ValueError("Invalid month")
    if str(day_relative).replace("\\","/")!="day/"+month+".parquet":
        raise ValueError("Selected day file must match requested month")
    check_prior(previous_timebase_safe,month)
    source=FOOTER.selected_file(root,day_relative,"day")
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyarrow.compute as pc
    rows,scanned,groups=_read_bounded_daily(source,trading_day,pa,pq,pc)
    summary=summarize_bars(rows)
    safe={
        "format":FORMAT,
        "sample_trading_day":trading_day,
        "sample_security_count":len(rows),
        "scanned_source_rows_bounded":scanned,
        "scanned_row_group_count":groups,
        "field_hypotheses":summary,
        "price_candidate_hikyuu_driver_ticks_per_unit":1000,
        "amount_candidate_hikyuu_driver_ticks_per_unit":10,
        "volume_candidate_hikyuu_driver_ticks_per_unit":1,
        "shortest_float_text_is_not_original_vendor_decimal":True,
        "binary64_exact_repr_differs_from_shortest_decimal_possible":True,
        "units_assumed_hikyuu_decoded_not_parquet_verified":True,
        "no_native_h5_integer_records_encoded_or_written":True,
        "no_h5_or_market_sqlite_opened":True,
        "source_parquet_read_only":True,
        "no_original_market_file_modified":True,
        "raw_ohlcva_or_timestamp_values_in_safe":False,
        "licensed_parquet_physical_units_certified":False,
        "source_time_label_semantics_certified":False,
        "real_float64_to_h5_precision_mapping_certified":False,
        "licensed_parquet_to_h5_mapping_certified":False,
        "ready_for_full_market_mirror":False,
    }
    with destination.open("x",encoding="utf-8") as f:
        json.dump(safe,f,ensure_ascii=False,indent=2)
        f.write("\n")
    return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--day-relative",required=True)
    p.add_argument("--trading-day",required=True)
    p.add_argument("--previous-timebase-safe",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--read-only-one-day-precision",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        safe=run(a.source_root,a.day_relative,a.trading_day,
                 a.previous_timebase_safe,a.out)
        print("SAFE bounded float64 tick hypotheses:",a.out)
        print("Selected fictional identifiers (real traded day bars):",
              safe["sample_security_count"])
        print("Rows scanned under hard limit:",safe["scanned_source_rows_bounded"])
        print("Physical units and real H5 mapping certified: NO")
        print("Production H5/market files modified: NO")
    except (ValueError,TypeError,OSError,ImportError,json.JSONDecodeError) as err:
        p.error(str(err) if type(err) is ValueError
                else "Bounded real Parquet precision pilot failed")


if __name__=="__main__":
    main()
