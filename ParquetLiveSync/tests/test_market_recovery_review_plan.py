"""Pure read-only versioned recovery plan tests; no QMT/network/market IO."""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import market_recovery_review_plan as P

def fixture(*,day='2026-11-25',symbol='SH605336',state=P.DAY_VALID):
    proof=({
        'state':P.DAY_VALID,
        'live_state_bytes_sha256':'d'*64,
        'day_receipt_bytes_sha256':'e'*64,
        'day_parquet_bytes_sha256':'f'*64,
        'declared_raw_tdx_zip_sha256_not_verified':'0'*64,
        'target_day_open':7.62,
        'provider_identity_authenticated':False,
        'official_stock_day_membership_certified':False,
        'qmt_minute_data_certified':False,
    } if state==P.DAY_VALID else None)
    blockers=sorted(P.REQUIRED_BLOCKERS |
                    ({'TDX_DAY_LOCAL_CONTENT_EVIDENCE_NOT_AVAILABLE'}
                     if proof is None else set()) |
                    {'EXISTING_OHLCVA_REJECTION_NOT_ADMITTED_AS_REPAIR'})
    e={
        'trading_day':day,'symbol':symbol,'period':'1min','source_id':'qmt-daily-stage',
        'producer_original_quarantine':True,
        'original_quality_case_sha256':'1'*64,
        'original_quality_incident_ids':['2'*64,'3'*64],
        'existing_quality_detected_rules':['OHLCVA_MISMATCH','PRODUCER_QUARANTINED'],
        'producer_receipt_bytes_sha256':'4'*64,
        'accepted_candidate_parquet_sha256_not_quarantined_raw_data':'5'*64,
        'tdx_day_local_evidence':proof,'tdx_day_evidence_state':state,
        'readiness':'BLOCKED_REVIEW_ONLY_NO_REPAIR',
        'next_readonly_review':'REPLAY_NATIVE_MINUTE_FIRST_TRADE_WITH_SEPARATE_APPROVAL',
        'unresolved_evidence_requirements':blockers,
        'source_independence_authenticated':False,
        'official_stock_day_universe_certified':False,
        'minute_market_candidate_approved':False,
        'production_merge_authorized':False,
        'qmt_history_download_authorized':False,
        'producer_quarantine_cleared':False,
    }
    r={
      'format':P.R_FORMAT,'status':P.R_STATUS,'window':[day,day],
      'existing_daily_receipts_checked':1,
      'producer_accepted_stock_days_reported_not_independently_recounted':5206,
      'original_producer_quarantined_stock_days':1,
      'original_quarantined_source_period_records':1,
      'distinct_quarantined_stock_days':1,
      'original_quality_rule_incidents':2,
      'original_backlog_sha256':'a'*64,
      'day_local_evidence_states':{state:1},
      'entries':[e],
      'readiness_overall':'BLOCKED_REVIEW_ONLY_NO_REPAIR',
      'native_qmt_minute_data_verified':False,
      'independent_official_stock_day_universe_certified':False,
      'provider_identity_authenticated':False,
      'production_merge_authorized':False,
      'qmt_history_download_authorized':False,
      'qmt_history_download_calls':0,
      'project_market_files_written':False,
      'original_producer_quarantines_cleared':False,
      'market_quality_cleared':False,
    }
    return signed(r)

def signed(r):
    r.pop('review_sha256',None)
    r['review_sha256']=P.digest(r)
    return r

def plan_signed(r):
    r.pop('plan_sha256',None)
    r['plan_sha256']=P.digest(r)
    return r

class ReviewPlanTests(unittest.TestCase):
    def test_base_deterministic_review_and_no_authority(self):
        r=fixture();a=P.build_review_plan(r);b=P.build_review_plan(deepcopy(r))
        self.assertEqual(a,b)
        self.assertEqual(a['review_request_count'],1)
        self.assertEqual(a['source_readiness_report_sha256'],r['review_sha256'])
        self.assertEqual(a['plan_sha256'],P.digest({k:v for k,v in a.items() if k!='plan_sha256'}))
        self.assertFalse(a['production_merge_authorized'])
        self.assertEqual(a['market_candidate_rows_generated'],0)
        self.assertFalse(a['market_files_written'])
        self.assertFalse(a['qmt_native_minute_bytes_verified'])
        self.assertFalse(a['original_producer_quarantines_cleared'])
        self.assertEqual(a['qmt_history_download_calls'],0)

    def test_stable_id_distinct_from_revision_sha(self):
        a=P.build_review_plan(fixture())
        r=fixture();r['entries'][0]['producer_receipt_bytes_sha256']='6'*64;signed(r)
        b=P.build_review_plan(r)
        self.assertEqual(a['requests'][0]['review_request_id'],b['requests'][0]['review_request_id'])
        self.assertNotEqual(a['requests'][0]['evidence_revision_sha256'],b['requests'][0]['evidence_revision_sha256'])

    def test_different_days_symbols_period_sources_have_different_id(self):
        a=P.build_review_plan(fixture())['requests'][0]['review_request_id']
        for field,value in [('trading_day','2019-04-09'),('symbol','SZ300462'),
                            ('period','5min'),('source_id','another-provider')]:
            r=fixture()
            r['entries'][0][field]=value
            if field=='trading_day':r['window']=[value,value]
            signed(r)
            b=P.build_review_plan(r)['requests'][0]['review_request_id']
            self.assertNotEqual(a,b)

    def test_absent_from_current_is_not_closed(self):
        r=fixture();a=P.build_review_plan(r)
        b=deepcopy(a)
        b['requests']=[];b['review_request_count']=0;b['producer_quarantined_source_period_records']=0
        plan_signed(b)
        out=P.compare_plans(a,b)
        self.assertEqual(out['changes'][0]['comparison_state'],
                         'NOT_IN_CURRENT_REVIEW_SCOPE_NOT_RESOLVED')
        self.assertFalse(out['changes'][0]['producer_quarantine_closed'])
        self.assertFalse(out['new_producer_quarantine_closure_authorized'])

    def test_new_scope_is_review_not_auto_admitted(self):
        a=P.build_review_plan(fixture())
        b=deepcopy(a)
        e=deepcopy(b['requests'][0]);e['scope']['symbol']='SZ300462'
        e['review_request_id']=P._proposal_identity(e['scope'])
        b['requests'].append(e);b['review_request_count']=2;b['producer_quarantined_source_period_records']=2
        plan_signed(b)
        d=P.compare_plans(a,b)
        self.assertEqual(d['counts']['NEW_SCOPE_REQUIRES_REVIEW'],1)

    def test_unchanged_and_evidence_revision_changed_states(self):
        a=P.build_review_plan(fixture())
        self.assertEqual(P.compare_plans(a,a)['counts']['UNCHANGED_EVIDENCE_STILL_QUARANTINED'],1)
        r=fixture();r['entries'][0]['accepted_candidate_parquet_sha256_not_quarantined_raw_data']='8'*64;signed(r)
        b=P.build_review_plan(r)
        self.assertEqual(P.compare_plans(a,b)['counts']['EVIDENCE_REVISION_CHANGED_REQUIRES_REVIEW'],1)

    def test_readiness_sha_mismatch_rejected(self):
        r=fixture();r['entries'][0]['symbol']='SZ300119'
        with self.assertRaisesRegex(P.PlanError,'READINESS_DIAGNOSTIC_SHA_CHANGED'):
            P.build_review_plan(r)

    def test_forged_source_permission_rejected(self):
        for field in ('production_merge_authorized','qmt_history_download_authorized',
                      'provider_identity_authenticated','project_market_files_written',
                      'market_quality_cleared','original_producer_quarantines_cleared'):
            r=fixture();r[field]=True;signed(r)
            with self.subTest(field=field), self.assertRaisesRegex(P.PlanError,'UNSUPPORTED_AUTHORITY'):
                P.build_review_plan(r)

    def test_forged_entry_admission_rejected(self):
        for field in ('producer_quarantine_cleared','minute_market_candidate_approved',
                      'source_independence_authenticated','qmt_history_download_authorized'):
            r=fixture();r['entries'][0][field]=True;signed(r)
            with self.subTest(field=field), self.assertRaisesRegex(P.PlanError,'ENTRY_AUTHORITY_CHANGED'):
                P.build_review_plan(r)

    def test_missing_native_qmt_blocker_rejected(self):
        r=fixture();r['entries'][0]['unresolved_evidence_requirements'].remove(
            'QMT_NATIVE_MINUTE_BYTES_NOT_INDEPENDENTLY_VERIFIED');signed(r)
        with self.assertRaisesRegex(P.PlanError,'RECOVERY_REQUIRED_GATES_MISSING'):
            P.build_review_plan(r)

    def test_evidence_hash_source_scope_retained(self):
        e=P.build_review_plan(fixture())['requests'][0]['evidence']
        self.assertEqual(e['accepted_candidate_parquet_sha256_NOT_quarantined_raw_qmt'],'5'*64)
        self.assertEqual(e['producer_receipt_bytes_sha256'],'4'*64)
        self.assertEqual(e['tdx_local_day_evidence']['day_parquet_bytes_sha256'],'f'*64)

    def test_missing_tdx_day_is_still_blocked(self):
        r=fixture(state='DAY_NOT_REGISTERED_IN_OVERLAY')
        a=P.build_review_plan(r)
        self.assertIsNone(a['requests'][0]['evidence']['tdx_local_day_evidence'])
        self.assertEqual(a['requests'][0]['review_disposition'],
                         'BLOCKED_MISSING_INDEPENDENT_EVIDENCE')

    def test_corrupt_unknown_day_state_refused(self):
        r=fixture();r['entries'][0]['tdx_day_evidence_state']='CERTIFIED'
        r['day_local_evidence_states']={'CERTIFIED':1};signed(r)
        with self.assertRaisesRegex(P.PlanError,'UNKNOWN_OR_MISSING_DAY_STATE'):
            P.build_review_plan(r)

    def test_day_local_proof_promotes_provider_refused(self):
        r=fixture();r['entries'][0]['tdx_day_local_evidence']['provider_identity_authenticated']=True;signed(r)
        with self.assertRaisesRegex(P.PlanError,'TDX_LOCAL_PROOF_INCOMPLETE'):
            P.build_review_plan(r)

    def test_trading_day_not_legal_rejected(self):
        r=fixture();r['window']=['2026-02-30','2026-02-30'];signed(r)
        with self.assertRaisesRegex(P.PlanError,'INVALID_TRADING_DAY'):
            P.build_review_plan(r)

    def test_duplicate_scope_rejected(self):
        r=fixture();r['entries'].append(deepcopy(r['entries'][0]));
        r['original_producer_quarantined_stock_days']=2
        r['original_quarantined_source_period_records']=2
        r['day_local_evidence_states']={P.DAY_VALID:2};signed(r)
        with self.assertRaisesRegex(P.PlanError,'DUPLICATE_RECOVERY_SCOPE'):
            P.build_review_plan(r)

    def test_wrong_stockday_count_rejected(self):
        r=fixture();r['distinct_quarantined_stock_days']=2;signed(r)
        with self.assertRaisesRegex(P.PlanError,'READINESS_SCOPE_OR_DAY_COUNTS_DISAGREE'):
            P.build_review_plan(r)

    def test_nonfinite_day_open_rejected_despite_rehashed_diagnostic(self):
        r=fixture();r['entries'][0]['tdx_day_local_evidence']['target_day_open']=float('nan')
        with self.assertRaises(ValueError):P.digest(r)

    def test_prior_plan_scope_outside_window_fail_closed(self):
        p=P.build_review_plan(fixture())
        p['window']=['2026-11-24','2026-11-24']
        plan_signed(p)
        with self.assertRaisesRegex(P.PlanError,'PRIOR_PLAN_SCOPE_OUTSIDE_WINDOW'):
            P.validate_plan(p)

    def test_absent_scope_case_requires_full_evidence_not_auto_resolve(self):
        p=P.build_review_plan(fixture())
        empty=deepcopy(p)
        empty['requests']=[]
        empty['review_request_count']=0
        empty['producer_quarantined_source_period_records']=0
        plan_signed(empty)
        result=P.compare_plans(p,empty)
        self.assertEqual(result['counts']['NOT_IN_CURRENT_REVIEW_SCOPE_NOT_RESOLVED'],1)
        self.assertFalse(result['previous_producer_quarantine_closure_authorized'])

    def test_bad_incident_id_rejected(self):
        r=fixture();r['entries'][0]['original_quality_incident_ids']=['notsha'];signed(r)
        with self.assertRaisesRegex(P.PlanError,'STABLE_INCIDENT_ID_INVALID'):
            P.build_review_plan(r)

    def test_unverified_recovery_plan_cannot_self_claim_payload(self):
        p=P.build_review_plan(fixture())
        p['requests'][0]['minute_payload_present']=True;plan_signed(p)
        with self.assertRaisesRegex(P.PlanError,'CANDIDATE_OR_SCOPE_CHANGED'):
            P.validate_plan(p)

    def test_prior_plan_evidence_hash_change_even_if_new_top_sha(self):
        p=P.build_review_plan(fixture());p['requests'][0]['evidence']['missing_requirements'].append('EXTRA')
        plan_signed(p)
        with self.assertRaisesRegex(P.PlanError,'REVIEW_PLAN_EVIDENCE_CHANGED'):
            P.validate_plan(p)

    def test_prior_plan_top_sha_tamper_rejected(self):
        p=P.build_review_plan(fixture());p['market_candidate_rows_generated']=10
        with self.assertRaisesRegex(P.PlanError,'REVIEW_PLAN_DIGEST_CHANGED'):
            P.validate_plan(p)

    def test_inspect_injected_readiness_never_calls_provider(self):
        r=fixture();hits=[]
        def reader(*a,**kw):hits.append((a,kw));return deepcopy(r)
        p=P.inspect('/not/existent','2026-11-25','2026-11-25',readiness_reader=reader)
        self.assertEqual(len(hits),1)
        self.assertEqual(hits[0][1]['max_stock_days'],64)
        self.assertEqual(p['review_request_count'],1)

    def test_read_prior_explicit_sha_and_traversal_gate(self):
        with TemporaryDirectory() as td:
            root=Path(td);out=root/'prior.json';p=P.build_review_plan(fixture())
            out.write_bytes(P.canonical(p))
            sha=sha256(out.read_bytes()).hexdigest()
            stub=type('F',(),{
                '_secure_relative':staticmethod(lambda rt,rel: rt / rel if rel=='prior.json' else (_ for _ in ()).throw(ValueError('TRAVERSAL'))),
                '_hash_stable_file':staticmethod(lambda x:(sha256(x.read_bytes()).hexdigest(),x.stat().st_size)),
            })
            with mock.patch.dict(sys.modules,{'market_quality_source_proofs':stub}):
                self.assertEqual(P.read_prior(root,'prior.json',sha),p)
                with self.assertRaises(ValueError):P.read_prior(root,'../prior.json',sha)
                with self.assertRaisesRegex(P.PlanError,'SHA_OR_SIZE_MISMATCH'):
                    P.read_prior(root,'prior.json','f'*64)

    def test_prior_duplicate_json_key_rejected(self):
        with TemporaryDirectory() as td:
            root=Path(td);out=root/'prior.json';p=P.build_review_plan(fixture())
            out.write_bytes(b'{"format":"injected",'+P.canonical(p)[1:])
            sha=sha256(out.read_bytes()).hexdigest()
            stub=type('F',(),{
                '_secure_relative':staticmethod(lambda rt,rel: rt / rel),
                '_hash_stable_file':staticmethod(lambda x:(sha256(x.read_bytes()).hexdigest(),x.stat().st_size)),
            })
            with mock.patch.dict(sys.modules,{'market_quality_source_proofs':stub}):
                with self.assertRaisesRegex(P.PlanError,'DUPLICATE_JSON_KEY'):
                    P.read_prior(root,'prior.json',sha)

    def test_cli_missing_source_does_not_leak_path(self):
        from contextlib import redirect_stdout
        from io import StringIO
        b=StringIO()
        with redirect_stdout(b):
            rc=P.main(['--module-root','/secret/project','--start-day','2026-11-25',
                       '--end-day','2026-11-25','--summary-only'])
        self.assertEqual(rc,3)
        self.assertNotIn('/secret/project',b.getvalue())

    def test_many_stockdays_missing_inputs_fail_closed(self):
        r=fixture();r['original_producer_quarantined_stock_days']=129
        signed(r)
        with self.assertRaisesRegex(P.PlanError,'READINESS_ORIGINAL_QUARANTINE_COUNT_CHANGED'):
            P.build_review_plan(r)

if __name__=='__main__':unittest.main()
