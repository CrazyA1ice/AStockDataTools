#!/usr/bin/env python3
"""Bounded 4-session cache-coverage census for seven Nov25 QMT zero-bar symbols.

Only one get_market_data_ex call, no QMT history download; never writes A-stock
state. The connected xtquant client may internally mutate its own logs/cache.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date, datetime
import json
from pathlib import Path
import sys

from audit_market_qmt_cache_readonly import RUN_DATE, RUN_SHA, TriageError, source_modules
from audit_market_opening_auction_readonly import verify_dependencies
from audit_market_quarantine_readonly import audit

STOCKS = tuple('SZ300' + str(i) for i in range(119,126))
DAYS = ('2026-11-20','2026-11-23','2026-11-24','2026-11-25')
FIELDS = ('open','high','low','close','volume','amount')


def analyze_existing_cache(payload, u):
    if not isinstance(payload, dict):
        raise TriageError('QMT_BATCH_NOT_DICT')
    records = []
    statuses = Counter()
    for symbol in STOCKS:
        code = symbol[2:] + '.' + symbol[:2]
        frame = payload.get(code)
        result = {'symbol': symbol, 'status':'', 'rows_by_day':{d:0 for d in DAYS},
                  'nov25_complete_grid_in_cache':False, 'validation_note':None,
                  'data_repaired':False}
        if frame is None:
            result['status'] = 'QMT_STOCK_KEY_MISSING'
        else:
            try:
                rows = u.P.normalize_frame(frame, code, date(2026,11,20), date(2026,11,25))
                day_rows = {d:[] for d in DAYS}
                for row in rows:
                    d = row['datetime_cn'][:10]
                    if d not in day_rows:
                        raise TriageError('QMT_UNEXPECTED_DATE_' + code)
                    day_rows[d].append(row)
                result['rows_by_day'] = {d:len(day_rows[d]) for d in DAYS}
                latest = day_rows[RUN_DATE]
                if not rows:
                    result['status'] = 'QMT_WINDOW_EMPTY'
                elif not latest:
                    result['status'] = 'OLDER_CACHE_PRESENT_NOV25_EMPTY'
                else:
                    grid = sorted((datetime.fromisoformat(x['datetime_cn']).hour,
                                   datetime.fromisoformat(x['datetime_cn']).minute)
                                  for x in latest)
                    native = sorted(u.P.GRID)
                    complete = len(grid) in (240,241) and grid == (native if len(grid)==241 else native[1:])
                    result['nov25_complete_grid_in_cache'] = complete
                    result['status'] = ('NOV25_CACHED_FULL_GRID_NOT_VALIDATED' if complete
                                        else 'NOV25_CACHED_PARTIAL_GRID_NOT_VALIDATED')
            except (ValueError,RuntimeError,TypeError,KeyError,OSError) as exc:
                result['status'] = 'QMT_CACHE_FRAME_INVALID'
                result['validation_note'] = type(exc).__name__ + ': ' + str(exc)[:160]
        statuses[result['status']] += 1
        records.append(result)
    return {'status':'SEVEN_SYMBOL_QMT_EXISTING_CACHE_CENSUS_NOT_REPAIR',
            'date_window':list(DAYS), 'original_run_sha256':RUN_SHA,
            'original_seven_quarantines_retained':True,
            'history_download_called':False,'project_market_files_modified':False,
            'qmt_client_internal_side_effects_unknown':True,
            'counts_by_status':dict(sorted(statuses.items())),'stocks':records}


def run_audit(root, *, confirm=False, xtdata=None, updater=None, forensic_audit=audit):
    if not confirm:
        raise TriageError('EXPLICIT_SEVEN_SYMBOL_CACHE_QUERY_REQUIRED')
    root = Path(root)
    verify_dependencies(root)  # before importing production modules
    u = updater if updater is not None else source_modules(root)
    if not hasattr(u,'P'):
        raise TriageError('PRODUCTION_MODULE_NOT_LOADED')
    report = forensic_audit(root,RUN_DATE,RUN_SHA,verify_parquet=True)
    absent = tuple(sorted(r['symbol'] for r in report['stocks']
                          if r['category']=='QMT_RAW_ONE_MINUTE_MISSING'))
    if (report['accepted']!=5206 or report['quarantined']!=9
            or absent != STOCKS):
        raise TriageError('ORIGINAL_SEVEN_QUARANTINES_CHANGED')
    daily = u._reference_for_day(root.parent,date(2026,11,25))
    if len(daily)!=5215 or any(s not in daily for s in STOCKS):
        raise TriageError('OFFICIAL_DAY_UNIVERSE_CHANGED')
    if xtdata is None:
        from xtquant import xtdata
    codes = [s[2:]+'.'+s[:2] for s in STOCKS]
    data = xtdata.get_market_data_ex(
        field_list=list(FIELDS),stock_list=codes,period='1m',
        start_time='20261120',end_time='20261125',count=-1,
        dividend_type='none',fill_data=False)
    return analyze_existing_cache(data,u)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module-root',type=Path,required=True)
    p.add_argument('--confirm-seven-symbol-cache-query',action='store_true')
    a=p.parse_args(argv)
    try:
        result=run_audit(a.module_root,confirm=a.confirm_seven_symbol_cache_query)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (TriageError,ValueError,RuntimeError,OSError,TypeError,KeyError,ImportError) as exc:
        print('MARKET_SEVEN_CACHE_CENSUS_REVIEW_REQUIRED: '+str(exc)[:220]);return 3

if __name__=='__main__': sys.exit(main())
