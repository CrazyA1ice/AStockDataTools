#!/usr/bin/env python3
"""Exactly seven/one-day QMT cache refresh, only after explicit opt-in.

Default invocation is a NO-QMT-IO plan. With explicit --approve-qmt-cache-write,
may change the QMT client's own datadir, never project Parquet/H5/receipts.
After downloading, validate original 241/240 minutes IN MEMORY only.
Do not automatically retry, stage, repair, merge, clear quarantine or send.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

from audit_market_qmt_cache_readonly import RUN_SHA, TriageError, source_modules
from audit_market_quarantine_readonly import audit
from audit_market_opening_auction_readonly import verify_dependencies
from audit_market_qmt_seven_coverage_readonly import (
    STOCKS, DAYS, analyze_existing_cache,
)

DAY = date(2026, 11, 25)
FIELDS = ('open','high','low','close','volume','amount')


class RefreshError(ValueError):
    pass


def plan():
    return {
        'status':'SEVEN_ONE_DAY_QMT_CACHE_REFRESH_PLAN_ONLY_NO_QMT_CALLS',
        'symbols':list(STOCKS), 'day':DAY.isoformat(),
        'qmt_downloads_authorized':False, 'qmt_download_calls':0,
        'market_files_modified':False, 'qmt_datadir_may_change_if_approved':True,
        'production_merge_authorized':False,
        'original_quarantines_retained':True, 'data_quality_cleared':False,
    }


def _demand(predicate, name):
    if not predicate:
        raise RefreshError(name)


def _preflight(u, evidence, root):
    absent=tuple(sorted(r['symbol'] for r in evidence['stocks']
                        if r['category']=='QMT_RAW_ONE_MINUTE_MISSING'))
    _demand(evidence['quarantined']==9 and evidence['accepted']==5206
            and evidence['expected']==5215 and absent==STOCKS,
            'ORIGINAL_NINE_STOCK_QUARANTINE_EVIDENCE_CHANGED')
    reference=u._reference_for_day(root.parent, DAY)
    _demand(len(reference)==5215 and all(s in reference for s in STOCKS),
            'INDEPENDENT_OFFICIAL_DAY_SOURCE_CHANGED')
    calibration=u.S._json(u.P.BASE / 'calibration' / 'latest.json')
    ledger=u.S._json(u.S.STATE_FILE)
    _demand(calibration.get('calibration_passed') is True
            and len(calibration.get('providers',{}))==3
            and ledger.get('qmt_calibration_sha256')==u.P.sha_bytes(u.P.canonical(calibration)),
            'PAID_MINUTE_CALIBRATION_SHA_CHANGED')
    return reference,calibration


def _ensure_target_is_still_absent(payload, u):
    coverage=analyze_existing_cache(payload,u)
    for stock in coverage['stocks']:
        _demand(stock['status']=='OLDER_CACHE_PRESENT_NOV25_EMPTY'
                and stock['rows_by_day']['2026-11-25']==0
                and all(stock['rows_by_day'][d]==241 for d in DAYS[:-1]),
                'CACHED_NOV25_OR_PREVIOUS_DAY_COVERAGE_CHANGED_'+stock['symbol'])
    return coverage


def refresh(root, *, approve=False, xtdata=None, updater=None,
            source_audit=audit, source_pins=verify_dependencies):
    """No history writes unless approved; strictly bounded to 7 stock-days."""
    if not approve:
        return plan()
    root=Path(root)
    source_pins(root)  # verify converter dependencies BEFORE QMT
    u=updater if updater is not None else source_modules(root)
    if not hasattr(u,'P'):
        raise RefreshError('PINNED_MARKET_UPDATER_UNAVAILABLE')
    evidence=source_audit(root,DAY.isoformat(),RUN_SHA,verify_parquet=True)
    reference,calib=_preflight(u,evidence,root)
    if xtdata is None:
        from xtquant import xtdata
    codes=[s[2:]+'.'+s[:2] for s in STOCKS]
    # Read-only review is performed BEFORE changing the QMT-owned cache.
    cached=xtdata.get_market_data_ex(
        field_list=list(FIELDS),stock_list=codes,period='1m',
        start_time='20261120',end_time='20261125',count=-1,
        dividend_type='none',fill_data=False)
    _ensure_target_is_still_absent(cached,u)
    finished=[]
    for code in codes:
        try:
            xtdata.download_history_data(
                code,period='1m',start_time='20261125',end_time='20261125')
        except Exception as exc:
            # Provider may have changed QMT cache for preceding symbols;
            # never auto-rollback provider files or retry on failure.
            raise RefreshError('QMT_CACHE_ONLY_PARTIAL_STOP_'+str(len(finished))+
                               '_COMPLETED_NEXT_'+code+'_'+type(exc).__name__) from exc
        finished.append(code)
    after=xtdata.get_market_data_ex(
        field_list=list(FIELDS),stock_list=codes,period='1m',
        start_time='20261125',end_time='20261125',count=-1,
        dividend_type='none',fill_data=False)
    _demand(isinstance(after,dict),'POST_DOWNLOAD_QMT_RESPONSE_INVALID')
    results=[]
    for s,code in zip(STOCKS,codes):
        result={'symbol':s,'status':'','rows':0,'original_quarantine_retained':True,
                'production_write_authorized':False}
        try:
            raw=u.P.normalize_frame(after.get(code),code,DAY,DAY)
            result['rows']=len(raw)
            if len(raw) not in (240,241):
                result['status']='CACHE_REFRESH_NO_FULL_NATIVE_DAY'
            else:
                ready=u.normal_qmt_day(raw,code,DAY,reference[s],calib)
                _demand(ready.num_rows==240,'CALIBRATED_DAY_NOT_240')
                result['status']='CACHE_DAY_VALIDATED_IN_MEMORY_ONLY'
        except (ValueError,TypeError,RuntimeError,OSError,KeyError) as exc:
            result['status']='CACHE_REFRESH_REJECTED_BY_ORIGINAL_VALIDATOR'
            result['reason']=type(exc).__name__+': '+str(exc)[:160]
        results.append(result)
    return {
        'status':'QMT_CACHE_ONLY_SEVEN_SINGLE_DAY_ATTEMPT_FINISHED_NOT_MARKET_REPAIR',
        'day':DAY.isoformat(), 'original_run_sha256':RUN_SHA,
        'downloaded_qmt_owned_cache_symbols':finished,
        'qmt_history_download_calls':len(finished),
        'all_seven_passed_current_market_validator':all(
            x['status']=='CACHE_DAY_VALIDATED_IN_MEMORY_ONLY' for x in results),
        'stocks':results,
        'market_files_modified':False, 'project_candidate_parquet_written':False,
        'original_quarantines_retained':True, 'production_merge_authorized':False,
        'data_quality_cleared':False, 'qmt_datadir_was_requested_to_change':True,
    }


def main(argv=None, *, action=refresh):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module-root',type=Path,required=True)
    p.add_argument('--approve-qmt-cache-write-exact-seven-nov25',action='store_true')
    a=p.parse_args(argv)
    try:
        result=action(a.module_root,approve=a.approve_qmt_cache_write_exact_seven_nov25)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))
        return 0 if not a.approve_qmt_cache_write_exact_seven_nov25 or result['all_seven_passed_current_market_validator'] else 3
    except Exception as exc:
        print('QMT_SEVEN_ONE_DAY_CACHE_REVIEW_REQUIRED: '+type(exc).__name__+': '+str(exc)[:150])
        return 3


if __name__=='__main__':
    raise SystemExit(main())
