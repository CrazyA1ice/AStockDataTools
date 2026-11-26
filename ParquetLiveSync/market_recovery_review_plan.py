#!/usr/bin/env python3
"""Versioned read-only review plan; never recovered market data or approval."""
from __future__ import annotations
import argparse
from datetime import date
from hashlib import sha256
import json
import math
from pathlib import Path
import re

FORMAT = 'astock_market_recovery_review_plan_v1'
STATUS = 'EVIDENCE_PINNED_REVIEW_PLAN_ONLY_NO_MINUTE_PAYLOAD'
R_FORMAT = 'astock_market_quarantine_readiness_readonly_v1'
R_STATUS = 'QUARANTINE_EVIDENCE_MATRIX_NO_REPAIR_AUTHORITY'
HEX = re.compile(r'^[a-fA-F0-9]{64}$')
SYMBOL = re.compile(r'^(SH|SZ|BJ)[0-9]{6}$')
SOURCE = re.compile(r'^[A-Za-z0-9_.:-]{1,64}$')
PERIODS = frozenset(('1min','5min','15min','30min','60min','day','week','month'))
MISSING_DAY = frozenset(('OUTSIDE_THIS_DAY_ADAPTER_WINDOW',
                         'DAY_NOT_REGISTERED_IN_OVERLAY',
                         'TARGET_NOT_IN_DAY_EXPORT',
                         'TARGET_NOT_ACTIVE_IN_DAY_EXPORT'))
DAY_VALID = 'LOCAL_TDX_DAY_CONTENT_VERIFIED_PROVIDER_UNAUTHENTICATED'
NEXT = frozenset(('REPLAY_NATIVE_MINUTE_FIRST_TRADE_WITH_SEPARATE_APPROVAL',
                  'CHECK_NATIVE_MINUTE_SOURCE_COVERAGE_WITH_SEPARATE_APPROVAL'))
MAX_CASES = 128
MAX_PRIOR_BYTES = 4 * 1024 * 1024
REQUIRED_BLOCKERS = frozenset((
    'ORIGINAL_PRODUCER_QUARANTINE_RETAINED',
    'QMT_NATIVE_MINUTE_BYTES_NOT_INDEPENDENTLY_VERIFIED',
    'TDX_PROVIDER_IDENTITY_NOT_AUTHENTICATED',
    'OFFICIAL_EXCHANGE_STOCK_DAY_UNIVERSE_NOT_CERTIFIED',
    'PAID_MINUTE_SOURCE_CALIBRATION_NOT_INDEPENDENTLY_VERIFIED',
    'SIX_FIELD_NATIVE_MINUTE_VS_DAY_NOT_REVALIDATED',
    'EIGHT_PERIOD_AGGREGATION_NOT_REVALIDATED',
    'TRANSACTIONAL_MARKET_COMMIT_NOT_AUTHORIZED',
))

class PlanError(ValueError):
    pass

def demand(ok, why):
    if not ok:
        raise PlanError(why)

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')

def digest(value):
    return sha256(canonical(value)).hexdigest()

def valid_sha(v):
    return type(v) is str and bool(HEX.fullmatch(v))

def validate_day(d):
    demand(type(d) is str and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', d)),
           'INVALID_TRADING_DAY')
    try:
        demand(date.fromisoformat(d).isoformat() == d, 'INVALID_TRADING_DAY')
    except ValueError as exc:
        raise PlanError('INVALID_TRADING_DAY') from exc

def _pinned_readiness(report):
    demand(type(report) is dict and report.get('format') == R_FORMAT and
           report.get('status') == R_STATUS, 'UNRECOGNIZED_READINESS_FORMAT')
    hash_ = report.get('review_sha256')
    demand(valid_sha(hash_) and digest({k:v for k,v in report.items()
                                      if k != 'review_sha256'}) == hash_.lower(),
           'READINESS_DIAGNOSTIC_SHA_CHANGED')
    for k in ('native_qmt_minute_data_verified',
              'independent_official_stock_day_universe_certified',
              'provider_identity_authenticated', 'production_merge_authorized',
              'qmt_history_download_authorized','project_market_files_written',
              'original_producer_quarantines_cleared','market_quality_cleared'):
        demand(report.get(k) is False, 'READINESS_UNSUPPORTED_AUTHORITY_' + k)
    demand(report.get('qmt_history_download_calls') == 0 and
           report.get('readiness_overall') == 'BLOCKED_REVIEW_ONLY_NO_REPAIR',
           'READINESS_UNEXPECTED_OPERATION')
    window = report.get('window')
    demand(type(window) is list and len(window) == 2, 'INVALID_READINESS_WINDOW')
    for d in window: validate_day(d)
    demand(window[0] <= window[1], 'INVALID_READINESS_WINDOW')
    entries = report.get('entries')
    demand(type(entries) is list and len(entries) <= MAX_CASES and
           type(report.get('original_producer_quarantined_stock_days')) is int and
           report['original_producer_quarantined_stock_days'] == len(entries) and
           report.get('original_quarantined_source_period_records') == len(entries),
           'READINESS_ORIGINAL_QUARANTINE_COUNT_CHANGED')
    demand(valid_sha(report.get('original_backlog_sha256')) and
           type(report.get('original_quality_rule_incidents')) is int and
           report['original_quality_rule_incidents'] >= len(entries),
           'READINESS_ORIGINAL_BACKLOG_EVIDENCE_INVALID')
    distinct = set()
    observed = set()
    evidence_states = {}
    for e in entries:
        demand(type(e) is dict, 'INVALID_READINESS_ENTRY')
        for field in ('trading_day','symbol','period','source_id'):
            demand(type(e.get(field)) is str, 'INVALID_READINESS_SCOPE')
        validate_day(e['trading_day'])
        demand(window[0] <= e['trading_day'] <= window[1] and
               bool(SYMBOL.fullmatch(e['symbol'])) and
               e['period'] in PERIODS and bool(SOURCE.fullmatch(e['source_id'])),
               'INVALID_READINESS_SCOPE')
        scope = (e['trading_day'],e['symbol'],e['period'],e['source_id'])
        demand(scope not in observed, 'DUPLICATE_RECOVERY_SCOPE')
        observed.add(scope)
        distinct.add(scope[:2])
        demand(e.get('producer_original_quarantine') is True and
               e.get('readiness') == 'BLOCKED_REVIEW_ONLY_NO_REPAIR' and
               all(e.get(k) is False for k in (
                   'source_independence_authenticated',
                   'official_stock_day_universe_certified',
                   'minute_market_candidate_approved',
                   'production_merge_authorized',
                   'qmt_history_download_authorized',
                   'producer_quarantine_cleared')),
               'READINESS_ENTRY_AUTHORITY_CHANGED')
        for field in ('original_quality_case_sha256',
                      'producer_receipt_bytes_sha256',
                      'accepted_candidate_parquet_sha256_not_quarantined_raw_data'):
            demand(valid_sha(e.get(field)), 'READINESS_MISSING_EVIDENCE_' + field)
        ids = e.get('original_quality_incident_ids')
        demand(type(ids) is list and ids == sorted(set(ids)) and len(ids) > 0
               and all(valid_sha(x) for x in ids),
               'READINESS_STABLE_INCIDENT_ID_INVALID')
        causes = e.get('existing_quality_detected_rules')
        demand(type(causes) is list and causes == sorted(set(causes)) and
               'PRODUCER_QUARANTINED' in causes,
               'READINESS_OLD_RULES_CHANGED')
        blocked = e.get('unresolved_evidence_requirements')
        demand(type(blocked) is list and len(set(blocked)) == len(blocked) and
               REQUIRED_BLOCKERS.issubset(blocked),
               'RECOVERY_REQUIRED_GATES_MISSING')
        demand(e.get('next_readonly_review') in NEXT, 'UNKNOWN_READONLY_FOLLOWUP')
        if 'OHLCVA_MISMATCH' in causes:
            demand(e['next_readonly_review'] ==
                   'REPLAY_NATIVE_MINUTE_FIRST_TRADE_WITH_SEPARATE_APPROVAL',
                   'INCORRECT_READONLY_REVIEW_FOR_OHLCVA')
        state = e.get('tdx_day_evidence_state')
        proof = e.get('tdx_day_local_evidence')
        if state == DAY_VALID:
            demand(type(proof) is dict and proof.get('state') == DAY_VALID and
                   all(valid_sha(proof.get(k)) for k in (
                       'live_state_bytes_sha256','day_receipt_bytes_sha256',
                       'day_parquet_bytes_sha256',
                       'declared_raw_tdx_zip_sha256_not_verified')) and
                   all(proof.get(k) is False for k in (
                       'provider_identity_authenticated',
                       'official_stock_day_membership_certified',
                       'qmt_minute_data_certified')) and
                   type(proof.get('target_day_open')) in (int,float) and
                   math.isfinite(float(proof['target_day_open'])) and
                   proof['target_day_open'] > 0 and
                   'TDX_DAY_LOCAL_CONTENT_EVIDENCE_NOT_AVAILABLE' not in blocked,
                   'READINESS_TDX_LOCAL_PROOF_INCOMPLETE')
        else:
            demand(state in MISSING_DAY and proof is None and
                   'TDX_DAY_LOCAL_CONTENT_EVIDENCE_NOT_AVAILABLE' in blocked,
                   'READINESS_UNKNOWN_OR_MISSING_DAY_STATE')
        evidence_states[state] = evidence_states.get(state,0)+1
    demand(type(report.get('distinct_quarantined_stock_days')) is int and
           report['distinct_quarantined_stock_days'] == len(distinct) and
           report.get('day_local_evidence_states') == dict(sorted(evidence_states.items())),
           'READINESS_SCOPE_OR_DAY_COUNTS_DISAGREE')
    return entries

def _proposal_identity(scope):
    return digest({'schema': FORMAT,'scope':scope})

def build_review_plan(readiness):
    """Pure deterministic manifest of evidence and blockers; no minute payload."""
    entries = _pinned_readiness(readiness)
    requests = []
    for e in entries:
        scope = {k:e[k] for k in ('trading_day','symbol','period','source_id')}
        evidence = {
            'old_incident_ids': e['original_quality_incident_ids'],
            'original_quality_case_sha256':e['original_quality_case_sha256'],
            'producer_receipt_bytes_sha256':e['producer_receipt_bytes_sha256'],
            'accepted_candidate_parquet_sha256_NOT_quarantined_raw_qmt':
                e['accepted_candidate_parquet_sha256_not_quarantined_raw_data'],
            'tdx_local_day_evidence':e['tdx_day_local_evidence'],
            'tdx_day_evidence_state':e['tdx_day_evidence_state'],
            'detected_rules':e['existing_quality_detected_rules'],
            'missing_requirements':sorted(e['unresolved_evidence_requirements']),
            'next_review_only':e['next_readonly_review'],
        }
        requests.append({
            'scope':scope,
            'review_request_id':_proposal_identity(scope),
            'evidence_revision_sha256':digest(evidence),
            'evidence':evidence,
            'review_disposition':'BLOCKED_MISSING_INDEPENDENT_EVIDENCE',
            'minute_payload_present':False,
            'data_repair_candidate_validated':False,
            'automatic_issue_closure_authorized':False,
            'project_market_write_authorized':False,
        })
    requests.sort(key=lambda x:(x['scope']['trading_day'],x['scope']['symbol'],
                                x['scope']['period'],x['scope']['source_id']))
    plan = {
        'format':FORMAT,'status':STATUS,
        'window':readiness['window'],
        'source_readiness_report_sha256':readiness['review_sha256'],
        'original_backlog_sha256':readiness['original_backlog_sha256'],
        'producer_quarantined_source_period_records':len(requests),
        'review_request_count':len(requests),
        'requests':requests,
        'plan_scope':'REVIEW_ONLY_NOT_NATIVE_MARKET_CANDIDATE',
        'independent_provider_or_market_calendar_authenticated':False,
        'qmt_native_minute_bytes_verified':False,
        'market_candidate_rows_generated':0,
        'production_merge_authorized':False,
        'qmt_history_download_authorized':False,
        'qmt_history_download_calls':0,
        'market_files_written':False,
        'original_producer_quarantines_cleared':False,
        'market_quality_cleared':False,
    }
    plan['plan_sha256'] = digest(plan)
    return plan

def validate_plan(plan):
    """Validate a saved plan against its diagnostic checksum and rule scope."""
    demand(type(plan) is dict and plan.get('format') == FORMAT and
           plan.get('status') == STATUS, 'UNRECOGNIZED_PRIOR_REVIEW_PLAN')
    signature = plan.get('plan_sha256')
    demand(valid_sha(signature) and digest({k:v for k,v in plan.items()
                                         if k != 'plan_sha256'}) == signature.lower(),
           'REVIEW_PLAN_DIGEST_CHANGED')
    demand(all(plan.get(key) is False for key in (
           'independent_provider_or_market_calendar_authenticated',
           'qmt_native_minute_bytes_verified', 'production_merge_authorized',
           'qmt_history_download_authorized', 'market_files_written',
           'original_producer_quarantines_cleared','market_quality_cleared')) and
           plan.get('qmt_history_download_calls') == 0 and
           plan.get('market_candidate_rows_generated') == 0 and
           plan.get('plan_scope') == 'REVIEW_ONLY_NOT_NATIVE_MARKET_CANDIDATE',
           'REVIEW_PLAN_ASSERTS_UNSUPPORTED_AUTHORITY')
    demand(valid_sha(plan.get('source_readiness_report_sha256')) and
           valid_sha(plan.get('original_backlog_sha256')),
           'PRIOR_PLAN_SOURCE_HASH_MISSING')
    window = plan.get('window')
    demand(type(window) is list and len(window) == 2, 'PRIOR_PLAN_WINDOW_INVALID')
    for d in window: validate_day(d)
    demand(window[0] <= window[1], 'PRIOR_PLAN_WINDOW_INVALID')
    request_list = plan.get('requests')
    demand(type(request_list) is list and len(request_list) <= MAX_CASES and
           type(plan.get('review_request_count')) is int and
           plan['review_request_count'] == len(request_list) and
           plan.get('producer_quarantined_source_period_records') == len(request_list),
           'REVIEW_PLAN_SCOPE_COUNT_INVALID')
    keys = set()
    for req in request_list:
        demand(type(req) is dict and type(req.get('scope')) is dict and
               set(req['scope']) == {'trading_day','symbol','period','source_id'},
               'REVIEW_PLAN_ENTRY_SCOPE_INVALID')
        sc = req['scope']
        validate_day(sc['trading_day'])
        demand(window[0] <= sc['trading_day'] <= window[1], 'PRIOR_PLAN_SCOPE_OUTSIDE_WINDOW')
        demand(bool(SYMBOL.fullmatch(sc['symbol'])) and
               sc['period'] in PERIODS and bool(SOURCE.fullmatch(sc['source_id'])),
               'REVIEW_PLAN_ENTRY_SCOPE_INVALID')
        request_id = _proposal_identity(sc)
        demand(req.get('review_request_id') == request_id and
               request_id not in keys and
               req.get('review_disposition') == 'BLOCKED_MISSING_INDEPENDENT_EVIDENCE' and
               all(req.get(k) is False for k in (
                   'minute_payload_present', 'data_repair_candidate_validated',
                   'automatic_issue_closure_authorized','project_market_write_authorized')),
               'REVIEW_PLAN_CANDIDATE_OR_SCOPE_CHANGED')
        keys.add(request_id)
        evidence = req.get('evidence')
        demand(type(evidence) is dict and req.get('evidence_revision_sha256') ==
               digest(evidence) and type(evidence.get('missing_requirements')) is list and
               REQUIRED_BLOCKERS.issubset(evidence['missing_requirements']) and
               type(evidence.get('old_incident_ids')) is list and
               len(evidence['old_incident_ids']) > 0 and
               all(valid_sha(x) for x in evidence['old_incident_ids']),
               'REVIEW_PLAN_EVIDENCE_CHANGED')
    return plan

def compare_plans(previous, current):
    """Review differences only; even absent scopes are NOT considered resolved."""
    validate_plan(previous)
    validate_plan(current)
    old = {r['review_request_id']:r for r in previous['requests']}
    new = {r['review_request_id']:r for r in current['requests']}
    comparisons = []
    for key in sorted(old.keys() | new.keys()):
        if key not in new:
            state = 'NOT_IN_CURRENT_REVIEW_SCOPE_NOT_RESOLVED'
        elif key not in old:
            state = 'NEW_SCOPE_REQUIRES_REVIEW'
        elif old[key]['evidence_revision_sha256'] == new[key]['evidence_revision_sha256']:
            state = 'UNCHANGED_EVIDENCE_STILL_QUARANTINED'
        else:
            state = 'EVIDENCE_REVISION_CHANGED_REQUIRES_REVIEW'
        r = new.get(key,old.get(key))
        comparisons.append({'review_request_id':key,'scope':r['scope'],
                            'comparison_state':state,'previous_evidence_sha256':
                            old[key]['evidence_revision_sha256'] if key in old else None,
                            'current_evidence_sha256':
                            new[key]['evidence_revision_sha256'] if key in new else None,
                            'producer_quarantine_closed':False})
    return {
        'format':FORMAT+'_comparison','previous_plan_sha256':previous['plan_sha256'],
        'current_plan_sha256':current['plan_sha256'],
        'changes':comparisons,
        'counts':{state:sum(c['comparison_state']==state for c in comparisons)
                  for state in sorted({c['comparison_state'] for c in comparisons})},
        'previous_producer_quarantine_closure_authorized':False,
        'new_producer_quarantine_closure_authorized':False,
        'market_files_written':False,
    }

def _unique_pairs(pairs):
    result = {}
    for k,v in pairs:
        demand(k not in result,'PRIOR_PLAN_DUPLICATE_JSON_KEY')
        result[k]=v
    return result

def read_prior(root, relative, expected_sha):
    """Read a manually supplied prior plan, limited to already existing bytes."""
    demand(valid_sha(expected_sha),'PRIOR_EXPECTED_FILE_SHA_INVALID')
    root=Path(root)
    demand(root.is_dir() and not root.is_symlink(),'PRIOR_REVIEW_ROOT_INVALID')
    import market_quality_source_proofs as P
    path=P._secure_relative(root,relative)
    first,size=P._hash_stable_file(path)
    demand(0 < size <= MAX_PRIOR_BYTES and first == expected_sha.lower(),
           'PRIOR_PLAN_FILE_SHA_OR_SIZE_MISMATCH')
    raw=path.read_bytes()
    last,last_size=P._hash_stable_file(path)
    demand(last == first == sha256(raw).hexdigest() and last_size==size==len(raw),
           'PRIOR_PLAN_BYTES_CHANGED_DURING_READ')
    try:
        old=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=_unique_pairs)
    except PlanError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise PlanError('PRIOR_PLAN_JSON_INVALID') from exc
    return validate_plan(old)

def inspect(module_root, start_day, end_day, *,max_stock_days=64,
            readiness_reader=None):
    """Only live IO is in existing read-only readiness audit; never writes."""
    if readiness_reader is None:
        import market_quarantine_recovery_readiness as R
        readiness_reader=R.inspect
    readiness=readiness_reader(module_root,start_day,end_day,
                               max_stock_days=max_stock_days)
    return build_review_plan(readiness)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module-root',type=Path,required=True)
    parser.add_argument('--start-day',required=True)
    parser.add_argument('--end-day',required=True)
    parser.add_argument('--max-stock-days',type=int,default=64)
    parser.add_argument('--summary-only',action='store_true')
    parser.add_argument('--prior-root',type=Path)
    parser.add_argument('--prior-relative')
    parser.add_argument('--prior-file-sha256')
    args=parser.parse_args(argv)
    try:
        supplied=[args.prior_root,args.prior_relative,args.prior_file_sha256]
        demand(all(x is None for x in supplied) or all(x is not None for x in supplied),
               'PRIOR_REFERENCE_PARAMETERS_MUST_BE_ALL_OR_NONE')
        plan=inspect(args.module_root,args.start_day,args.end_day,
                     max_stock_days=args.max_stock_days)
        out={'plan':plan}
        if all(x is not None for x in supplied):
            out['comparison']=compare_plans(read_prior(args.prior_root,
                         args.prior_relative,args.prior_file_sha256),plan)
        if args.summary_only:
            out['plan']={k:v for k,v in plan.items() if k!='requests'}
            if 'comparison' in out:
                out['comparison']={k:v for k,v in out['comparison'].items()
                                   if k!='changes'}
        print(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False))
        return 0
    except (PlanError,ValueError,OSError,TypeError,KeyError,ImportError,
            RuntimeError) as exc:
        print('MARKET_REVIEW_PLAN_REQUIRES_REVIEW: '+type(exc).__name__)
        return 3

if __name__=='__main__':
    raise SystemExit(main())
