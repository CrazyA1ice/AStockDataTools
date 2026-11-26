"""No provider download, no real file writes; test strict claimed-source triage."""
import contextlib
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_declared_day_backlog_bridge as M
import market_day_universe_crosscheck as U
import market_quality_engine as Q
import market_quality_backlog as B


def report(day='2025-05-12', reference_source='declared-external'):
    active = {'SH600000':True,'SZ000001':False,'SZ300888':True,'BJ920021':True}
    claimed = {'SH600000':'TRADED','SZ000001':'TRADED','SZ300888':'NO_TRADE',
               'SZ300119':'TRADED','BJ920021':'UNKNOWN','SH601318':'UNKNOWN',
               'SZ301001':'NO_TRADE'}
    comparison = U.reconcile(active, claimed)
    result = {
        'status':U.STATUS,'day':day,'anchor_symbol':'SH600000',
        'tdx_overlay_parquet_bytes_sha256':'a'*64,
        'tdx_overlay_state_bytes_sha256':'b'*64,
        'tdx_overlay_receipt_bytes_sha256':'c'*64,
        'reference_bytes_sha256':'d'*64,
        'declared_reference_source_id':reference_source,
        'declared_reference_coverage_claim':'PARTIAL_DECLARED',
        'reference_symbol_count':len(claimed),
        'normalized_exchange_code_count':len(active),
        'rows_checked':len(active),
        'independent_reference_provider_authenticated':False,
        'reference_full_stock_day_universe_certified':False,
        'tdx_provider_identity_authenticated':False,
        'instrument_membership_authenticated':False,
        'source_independence_authenticated':False,
        'native_qmt_1min_certified':False,
        'original_producer_quarantines_cleared':False,
        'market_quality_cleared':False,
        'market_write_authorized':False,
        'market_files_written':False,
        'qmt_history_download_calls':0,
        **comparison,
    }
    result['comparison_json_sha256'] = U.sha(result)
    return result


class BridgeTests(unittest.TestCase):
    def test_real_generic_quality_engine_rule_exists(self):
        self.assertIn('DECLARED_DAY_STATE_CONFLICT',Q.ACTIONS)
        self.assertIn('DECLARED_DAY_REFERENCE_UNCERTAIN',Q.ACTIONS)

    def test_crosscheck_declared_conflicts_convert_to_review_only(self):
        r=M.make_backlog(report())
        self.assertEqual(r['declared_conflicting_stock_days'],3)
        self.assertEqual(r['declared_uncertain_stock_days'],2)
        self.assertEqual(r['generic_backlog']['case_count'],5)
        self.assertFalse(r['declared_source_comparison_is_official_market_verification'])
        self.assertFalse(r['market_files_written'])
        self.assertFalse(r['automatic_quarantine_closure_authorized'])

    def test_conflict_incidents_are_only_assertion_level_and_P2(self):
        r=M.make_backlog(report())
        issues=[x for x in r['generic_backlog']['issues'] if x['rule_id']=='DECLARED_DAY_STATE_CONFLICT']
        self.assertEqual(len(issues),3)
        self.assertTrue(all(x['state']=='OPEN_QUARANTINED' for x in issues))
        self.assertTrue(all(x['priority']=='P2' for x in issues))
        self.assertEqual({x['scope']['symbol'] for x in issues},
                         {'SZ000001','SZ300888','SZ300119'})

    def test_unlisted_code_and_unknown_claim_are_uncertain(self):
        r=M.make_backlog(report())
        issues=[x for x in r['generic_backlog']['issues'] if x['rule_id']=='DECLARED_DAY_REFERENCE_UNCERTAIN']
        self.assertEqual(len(issues),2)
        self.assertTrue(all(x['state']=='NEEDS_EVIDENCE' for x in issues))
        self.assertEqual({x['scope']['symbol'] for x in issues},
                         {'BJ920021','SH601318'})

    def test_no_market_provenance_is_claimed_even_on_match(self):
        out=M.make_backlog(report())
        for key in ('provider_identity_authenticated','official_stock_day_universe_certified',
                    'native_qmt_minutes_certified','market_quality_cleared',
                    'market_files_written','production_market_admission_authorized'):
            self.assertIs(out[key],False)

    def test_complete_claim_does_not_create_official_universe_certification(self):
        r=report();r['declared_reference_coverage_claim']='FULL_DECLARED';r['comparison_json_sha256']=U.sha({k:v for k,v in r.items() if k!='comparison_json_sha256'})
        out=M.make_backlog(r)
        self.assertFalse(out['official_stock_day_universe_certified'])

    def test_conflicting_evidence_document_versions_have_stable_incident_ids(self):
        a=M.make_backlog(report('2025-05-12'))
        r=report('2025-05-12',reference_source='another-source')
        b=M.make_backlog(r)
        get=lambda doc:sorted(x['incident_id'] for x in doc['generic_backlog']['issues'])
        self.assertEqual(get(a),get(b))
        self.assertNotEqual(a['crosscheck_report_sha256'],b['crosscheck_report_sha256'])

    def test_different_date_not_forced_to_nov25(self):
        a=M.make_backlog(report('2019-02-15'))
        b=M.make_backlog(report('2026-11-25'))
        self.assertNotEqual({i['incident_id'] for i in a['generic_backlog']['issues']},
                            {i['incident_id'] for i in b['generic_backlog']['issues']})

    def test_no_diff_returns_empty_noncertified_backlog(self):
        r=report()
        r['groups']={k:[] for k in M.GROUPS}
        r['groups']['declared_traded_and_overlay_active']=['BJ920021','SH600000','SZ300888']
        r['groups']['declared_no_trade_and_zero_in_overlay']=['SZ000001']
        r['counts']={k:len(v) for k,v in r['groups'].items()}
        r['reference_symbol_count']=4
        r['has_declared_conflict']=False
        r['comparison_json_sha256']=U.sha({k:v for k,v in r.items() if k!='comparison_json_sha256'})
        out=M.make_backlog(r)
        self.assertEqual(out['generic_backlog']['unique_incidents'],0)
        self.assertFalse(out['market_quality_cleared'])

    def test_tampered_report_diagnostic_sha_rejected(self):
        r=report();r['reference_bytes_sha256']='e'*64
        with self.assertRaisesRegex(M.BridgeError,'DIAGNOSTIC_DIGEST_CHANGED'):
            M.make_backlog(r)

    def test_forged_independence_flag_rejected(self):
        r=report();r['source_independence_authenticated']=True
        r['comparison_json_sha256']=U.sha({k:v for k,v in r.items() if k!='comparison_json_sha256'})
        with self.assertRaisesRegex(M.BridgeError,'UNSUPPORTED_AUTHORITY'):
            M.make_backlog(r)

    def test_provider_write_claim_rejected(self):
        for key in ('market_write_authorized','market_files_written','original_producer_quarantines_cleared'):
            r=report();r[key]=True
            r['comparison_json_sha256']=U.sha({k:v for k,v in r.items() if k!='comparison_json_sha256'})
            with self.subTest(key=key), self.assertRaises(M.BridgeError):M.make_backlog(r)

    def test_reject_missing_source_file_sha(self):
        r=report();r['tdx_overlay_parquet_bytes_sha256']=None
        r['comparison_json_sha256']=U.sha({k:v for k,v in r.items() if k!='comparison_json_sha256'})
        with self.assertRaisesRegex(M.BridgeError,'MISSING_CROSSCHECK_BYTE_SHA'):
            M.make_backlog(r)

    def test_reject_count_forgery(self):
        r=report();r['counts']['declared_traded_missing_in_overlay']+=1
        r['comparison_json_sha256']=U.sha({k:v for k,v in r.items() if k!='comparison_json_sha256'})
        with self.assertRaisesRegex(M.BridgeError,'COUNTED'):
            M.make_backlog(r)

    def test_reference_bucket_sum_must_equal_reported_reference_count(self):
        r=report();r['reference_symbol_count']+=1
        r['comparison_json_sha256']=U.sha({k:v for k,v in r.items() if k!='comparison_json_sha256'})
        with self.assertRaisesRegex(M.BridgeError,'REFERENCE_SYMBOL_COUNT_DISAGREES'):
            M.make_backlog(r)

    def test_physical_day_code_count_must_match_present_buckets(self):
        r=report();r['normalized_exchange_code_count']+=1
        r['comparison_json_sha256']=U.sha({k:v for k,v in r.items() if k!='comparison_json_sha256'})
        with self.assertRaisesRegex(M.BridgeError,'OVERLAY_SYMBOL_COUNT_DISAGREES'):
            M.make_backlog(r)

    def test_reject_duplicate_symbol_across_buckets(self):
        r=report();r['groups']['declared_traded_zero_in_overlay'].append('SZ300119')
        r['groups']['declared_traded_zero_in_overlay'].sort()
        r['counts']['declared_traded_zero_in_overlay']=len(r['groups']['declared_traded_zero_in_overlay'])
        r['comparison_json_sha256']=U.sha({k:v for k,v in r.items() if k!='comparison_json_sha256'})
        with self.assertRaisesRegex(M.BridgeError,'DUPLICATED_OR_INVALID'):
            M.make_backlog(r)

    def test_group_schema_missing_bucket_fails_closed(self):
        r=report();r['groups'].pop('declared_no_trade_and_zero_in_overlay')
        r['comparison_json_sha256']=U.sha({k:v for k,v in r.items() if k!='comparison_json_sha256'})
        with self.assertRaisesRegex(M.BridgeError,'BUCKET_SCHEMA_CHANGED'):
            M.make_backlog(r)

    def test_bad_day_and_reference_label_fail(self):
        for key,value in [('day','2026-02-30'),('declared_reference_source_id','../../fake')]:
            r=report();r[key]=value
            r['comparison_json_sha256']=U.sha({k:v for k,v in r.items() if k!='comparison_json_sha256'})
            with self.subTest(key=key),self.assertRaises(M.BridgeError):M.make_backlog(r)

    def test_source_sha_is_tdx_physical_day_not_raw_qmt(self):
        report_data=report()
        batch=M.to_quality_batch(report_data)
        self.assertTrue(all(x['source_snapshot_sha256']==report_data['tdx_overlay_parquet_bytes_sha256'] for x in batch['cases']))
        self.assertTrue(all(x['scope']['period']=='day' for x in batch['cases']))
        self.assertTrue(all(x['scope']['source_id']==M.SOURCE_ID for x in batch['cases']))

    def test_producer_existing_quarantines_join_without_closure(self):
        a=Q.analyze_batch([{'format':Q.FORMAT,'trading_day':'2025-05-12',
            'symbol':'SH600000','period':'1min','source_id':'qmt-daily-stage',
            'source_state':'UNKNOWN','official_stock_day':None,'producer_quarantined':True,
            'raw_source_sha256':None}])
        r=M.make_backlog(report(),producer_batch=a,producer_quarantine_count=1)
        self.assertEqual(r['producer_quarantines_included_unmodified'],1)
        self.assertEqual(r['generic_backlog']['case_count'],6)
        self.assertFalse(r['automatic_quarantine_closure_authorized'])

    def test_producer_count_mismatch_rejected(self):
        a=Q.analyze_batch([{'format':Q.FORMAT,'trading_day':'2025-05-12',
            'symbol':'SH600000','period':'1min','source_id':'qmt-daily-stage',
            'source_state':'UNKNOWN','official_stock_day':None,'producer_quarantined':True}])
        with self.assertRaisesRegex(M.BridgeError,'PRODUCER_QUARANTINE_COUNT_MISMATCH'):
            M.make_backlog(report(),producer_batch=a,producer_quarantine_count=3)

    def test_unknown_reference_codes_not_marked_as_market_error(self):
        q=M.to_quality_batch(report())
        e=[x for x in q['cases'] if x['scope']['symbol']=='BJ920021']
        self.assertEqual(len(e),1)
        self.assertNotIn('DECLARED_DAY_STATE_CONFLICT',e[0]['detected_rules'])
        self.assertIn('DECLARED_DAY_REFERENCE_UNCERTAIN',e[0]['unverified_rules'])

    def test_cli_without_valid_source_fails_with_no_private_path_leak(self):
        s=StringIO()
        with contextlib.redirect_stdout(s):
            rc=M.main(['--module-root','/private/root','--trading-day','2025-05-12',
                       '--anchor-symbol','SH600000','--reference-root','/private/reference',
                       '--reference-relative','reference.json','--reference-sha256','a'*64])
        self.assertEqual(rc,3)
        self.assertNotIn('/private/',s.getvalue())

    def test_has_no_market_writer_and_no_auto_clearing(self):
        import inspect
        src=inspect.getsource(M)
        for pattern in ('download_history_data(', 'pq.write_table(', 'os.replace('):
            self.assertNotIn(pattern,src)

if __name__=='__main__': unittest.main()
