#!/usr/bin/env python3
"""Read-only live probe: does the public minute K-line endpoint really page back?

The returned 600-minute horizon is NOT assumed to cover 2026-10-14 to
2026-11-11. This separates the date specified in "end" from the actual
earliest/latest bars in the source response; API may silently ignore "end".
Does not modify ANY production Parquet/H5, only logs counts/actual dates.
"""
import json
from datetime import date
import time
import urllib.parse
from minute_probe import BASE,fetch,parse_bars,endpoint

TRIALS=(
    ("5min","SH600000","2026-09-30"),
    ("15min","SH600000","2026-09-30"),
    ("30min","SH600000","2026-09-30"),
    ("60min","SH600000","2026-09-30"),
    ("5min","SH600000","2026-10-13"),
    ("5min","SH600000","2026-10-20"),
    ("5min","SH600000","2026-11-11"),
)

def run(requester=fetch,pause=.3,logger=print):
    outputs=[]
    for period,symbol,day in TRIALS:
        url=endpoint(period,symbol,end=date.fromisoformat(day))
        logger(f"CHECK_MINUTE_HISTORY_WINDOW {period} {symbol} end={day}")
        try:
            _,doc=requester(url)
            items=parse_bars(doc,period,symbol)
            days=sorted(set(x["date"] for x in items))
            output={"period":period,"symbol":symbol,"requested_end":day,
                    "bars":len(items),"first":days[0],"last":days[-1],
                    "requested_end_present":day in days,
                    "contains_2026_09_30":"2026-09-30" in days,
                    "contains_2026_10_13":"2026-10-13" in days}
        except Exception as exc:
            output={"period":period,"symbol":symbol,"requested_end":day,
                    "error":str(exc)[:300],"bars":0}
        outputs.append(output)
        logger("MINUTE_HISTORY_PROBE="+json.dumps(output,sort_keys=True))
        if pause>0:time.sleep(pause)
    p=urllib.parse.urlparse(endpoint("5min","SH600000"))
    args=urllib.parse.parse_qs(p.query)
    args["klt"]=["1"]
    args["end"]=["20261013"]
    one=BASE+"?"+urllib.parse.urlencode(args,doseq=True)
    logger("CHECK_KLT1_TRUE_OHLCVA_2026_10_13")
    try:
        _,doc=requester(one)
        meta=doc.get("data") or {}
        values=meta.get("klines") or []
        outcome={"period":"klt1","requested_end":"2026-10-13",
                 "raw_kline_count":len(values),
                 "first_record":(str(values[0])[:150] if values else None),
                 "last_record":(str(values[-1])[:150] if values else None)}
    except Exception as exc:
        outcome={"period":"klt1","requested_end":"2026-10-13",
                 "error":str(exc)[:300],"raw_kline_count":0}
    outputs.append(outcome)
    logger("MINUTE_KLT1_SOURCE_PROBE="+json.dumps(outcome,sort_keys=True))
    return outputs

if __name__=="__main__":
    run()
