"""Pure synthetic backlog tests; no QMT, paid data, network, or project writes."""
import contextlib
from copy import deepcopy
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import market_quality_backlog as B
import market_quality_engine as Q


def case(day='2024-03-15',symbol='SZ300119',source='qmt-daily-stage',period='1min',
         raw=None,version='a',open_bad=True,producer=True):
    scope={'trading_day':day,'symbol':symbol,'source_id':source,'period':period}
    rules=[]
    if producer:
        rules.append('PRODUCER_QUARANTINED')
    if open_bad:
        rules.append('OHLCVA_MISMATCH')
    rules.append('SOURCE_PROVENANCE_UNVERIFIED')
    findings=[{'rule_id':r,'status':'DETECTED' if r!='SOURCE_PROVENANCE_UNVERIFIED' else 'INSUFFICIENT_EVIDENCE',
               'suggested_action':Q.ACTIONS[r]} for r in rules]
    return {'format':Q.REPORT,'scope':scope,
            'input_evidence_json_sha256':sha256(version.encode()).hexdigest(),
            'source_snapshot_sha256':raw,'findings':findings,
            'detected_rules':[r for r in rules if r!='SOURCE_PROVENANCE_UNVERIFIED'],
            'unverified_rules':['SOURCE_PROVENANCE_UNVERIFIED'],
            'quality_state':'QUARANTINED' if len(rules)>1 else 'UNVERIFIED',
            'production_admission_authorized':False,
            'qmt_cache_write_authorized':False,
            'market_parquet_or_h5_write_authorized':False}


def batch(records):
    return {'format':Q.REPORT+'_batch','case_count':len(records),'cases':records}


class BacklogTests(unittest.TestCase):
    def test_two_dates_same_engine_no_date_lock(self):
        r=B.build_backlog(batch([case(day='2018-08-08'),case(day='2026-11-25',symbol='SH605336')]))
        self.assertEqual(r['case_count'],2)
        self.assertEqual(r['unique_incidents'],6)
        self.assertFalse(r['automatic_closure_authorized'])
        self.assertFalse(r['market_files_written'])
        self.assertEqual(r['qmt_cache_download_calls'],0)

    def test_ids_are_stable_across_reordered_evidence_and_repeated_obs(self):
        a=case(version='one')
        b=case(day='2025-01-10',symbol='BJ920021',version='two')
        x=B.build_backlog(batch([a,b]))
        y=B.build_backlog(batch([b,a,a]))
        self.assertEqual([i['incident_id'] for i in x['issues']],
                         [i['incident_id'] for i in y['issues']])
        self.assertEqual(x['unique_incidents'],y['unique_incidents'])
        self.assertEqual(y['findings_observed_including_repeats'],9)
        self.assertNotEqual(x['backlog_sha256'],y['backlog_sha256'])

    def test_different_source_same_stock_day_is_separate_incident(self):
        a=case(source='provider-A')
        b=case(source='provider-B')
        r=B.build_backlog(batch([a,b]))
        self.assertEqual(r['unique_incidents'],6)
        self.assertEqual(len({i['incident_id'] for i in r['issues']}),6)

    def test_same_scope_different_case_digest_requests_revision_review(self):
        a=case(version='v1',raw='a'*64)
        b=case(version='v2',raw='b'*64)
        r=B.build_backlog(batch([a,b]))
        self.assertEqual(r['unique_incidents'],3)
        self.assertEqual(r['issues_requiring_revision_review'],3)
        for issue in r['issues']:
            self.assertEqual(issue['evidence_version_count'],2)
            self.assertEqual(issue['state'],'OPEN_QUARANTINED' if issue['rule_id']!='SOURCE_PROVENANCE_UNVERIFIED' else 'NEEDS_EVIDENCE')
            self.assertFalse(issue['automatic_closure_authorized'])

    def test_one_revision_detected_another_uncertain_never_closes_detected(self):
        a=case(version='v1')
        b=case(version='v2')
        b['findings'][1]['status']='INSUFFICIENT_EVIDENCE'
        b['detected_rules'].remove('OHLCVA_MISMATCH')
        b['unverified_rules'].append('OHLCVA_MISMATCH')
        r=B.build_backlog(batch([a,b]))
        issue=next(i for i in r['issues'] if i['rule_id']=='OHLCVA_MISMATCH')
        self.assertEqual(issue['state'],'OPEN_QUARANTINED')
        self.assertTrue(issue['revision_review_required'])
        self.assertFalse(issue['automatic_closure_authorized'])

    def test_storage_integrity_precedes_price_conflict(self):
        a=case()
        a['findings'].append({'rule_id':'STORAGE_OR_RECEIPT_INTEGRITY','status':'DETECTED',
                              'suggested_action':Q.ACTIONS['STORAGE_OR_RECEIPT_INTEGRITY']})
        a['detected_rules'].append('STORAGE_OR_RECEIPT_INTEGRITY')
        r=B.build_backlog(batch([a]))
        self.assertEqual(r['issues'][0]['priority'],'P0')
        self.assertEqual(r['issues'][0]['rule_id'],'STORAGE_OR_RECEIPT_INTEGRITY')

    def test_uncertain_only_needs_evidence_not_cleared(self):
        a=case(open_bad=False,producer=False)
        r=B.build_backlog(batch([a]))
        self.assertEqual(r['issues'][0]['state'],'NEEDS_EVIDENCE')
        self.assertEqual(r['issues'][0]['priority'],'P3')
        self.assertFalse(r['market_quality_cleared'])

    def test_source_hash_is_optional_but_only_true_source_digest_not_case_sha(self):
        a=case(raw=None)
        r=B.build_backlog(batch([a]))
        self.assertIsNone(r['issues'][0]['evidence_versions'][0]['raw_source_sha256_if_supplied'])
        self.assertIn('NORMALIZED_CASE_JSON_ONLY',r['source_evidence_sha_scope'])

    def test_untrusted_suggested_action_rejected(self):
        a=case();a['findings'][0]['suggested_action']='download_history_data'
        with self.assertRaisesRegex(B.BacklogError,'UNTRUSTED_FINDING_ACTION'):
            B.build_backlog(batch([a]))

    def test_unknown_rule_rejected(self):
        a=case();a['findings'][0]['rule_id']='DISABLE_SSL_VERIFY'
        with self.assertRaisesRegex(B.BacklogError,'UNKNOWN_RULE'):
            B.build_backlog(batch([a]))

    def test_cannot_use_upstream_write_authority(self):
        for flag in ('production_admission_authorized','qmt_cache_write_authorized','market_parquet_or_h5_write_authorized'):
            with self.subTest(flag=flag):
                a=case();a[flag]=True
                with self.assertRaisesRegex(B.BacklogError,'AUTHORITY_CHANGED'):
                    B.build_backlog(batch([a]))

    def test_invalid_case_count_rejected(self):
        a=batch([case()]);a['case_count']=3
        with self.assertRaisesRegex(B.BacklogError,'CASE_COUNT'):
            B.build_backlog(a)

    def test_invalid_sha_rejected(self):
        a=case();a['input_evidence_json_sha256']='not-the-source'
        with self.assertRaisesRegex(B.BacklogError,'DIGEST_MISSING'):
            B.build_backlog(batch([a]))

    def test_invalid_date_and_symbol_rejected(self):
        for k,v in (('trading_day','2026-02-30'),('symbol','invalid')):
            with self.subTest(k=k):
                a=case();a['scope'][k]=v
                with self.assertRaises(B.BacklogError):
                    B.build_backlog(batch([a]))

    def test_diff_source_revisions_never_assumed_chronologically_new(self):
        a=case(version='2020',raw='0'*64)
        b=case(version='2010',raw='1'*64)
        r=B.build_backlog(batch([b,a]))
        self.assertTrue(r['issues_requiring_revision_review'])
        self.assertFalse(r['automatic_closure_authorized'])

    def test_empty_batch_valid_but_does_not_certify_market(self):
        r=B.build_backlog(batch([]))
        self.assertEqual(r['unique_incidents'],0)
        self.assertFalse(r['market_quality_cleared'])
        self.assertFalse(r['automatic_closure_authorized'])

    def test_backlog_sha_is_canonical_without_self_hash(self):
        r=B.build_backlog(batch([case()]))
        self.assertEqual(r['backlog_sha256'],B.digest({k:v for k,v in r.items() if k!='backlog_sha256'}))

    def test_from_daily_receipt_remains_sealed_nonadmitting(self):
        doc={'status':'READ_ONLY_DAILY_QUARANTINE_QUALITY_TRIAGE',
             'project_market_files_modified':False,'data_quality_cleared':False,
             'production_merge_authorized':False,
             'quality_cases':batch([case()]),'existing_day_receipts_checked':1,
             'producer_quarantines_preserved':1,
             'producer_accepted_stock_days_reported_not_recrossvalidated':5206}
        rd=Mock(return_value=doc)
        r=B.from_daily_receipts(Path('/missing'),start_day='2025-01-01',end_day='2025-01-02',reader=rd)
        rd.assert_called_once_with(Path('/missing'),start_day='2025-01-01',end_day='2025-01-02')
        self.assertEqual(r['original_producer_quarantines_preserved'],1)
        self.assertEqual(r['accepted_stock_days_reported_not_independently_verified'],5206)
        self.assertFalse(r['official_day_independently_certified'])
        self.assertFalse(r['original_raw_qmt_independently_certified'])
        self.assertFalse(r['market_files_written'])
        self.assertEqual(r['backlog_sha256'],B.digest({k:v for k,v in r.items() if k!='backlog_sha256'}))

    def test_mutated_daily_adapter_authority_fails_closed(self):
        doc={'status':'READ_ONLY_DAILY_QUARANTINE_QUALITY_TRIAGE',
             'project_market_files_modified':True,'data_quality_cleared':False,
             'production_merge_authorized':False,'quality_cases':batch([])}
        with self.assertRaisesRegex(B.BacklogError,'DAILY_ADAPTER_AUTHORITY_CHANGED'):
            B.from_daily_receipts('/synthetic',start_day='2025-01-01',end_day='2025-01-01',reader=Mock(return_value=doc))

    def test_quality_json_cli_no_write(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'cases.json'
            p.write_text(json.dumps(batch([case()])),encoding='utf-8')
            before=p.read_bytes()
            out=StringIO()
            with contextlib.redirect_stdout(out):
                result=B.main(['--quality-json',str(p)])
            self.assertEqual(result,0)
            self.assertEqual(json.loads(out.getvalue())['unique_incidents'],3)
            self.assertEqual(p.read_bytes(),before)
            self.assertEqual([x.name for x in Path(root).iterdir()],['cases.json'])

    def test_missing_cli_args_fail_without_download(self):
        out=StringIO()
        with contextlib.redirect_stdout(out):
            code=B.main([])
        self.assertEqual(code,3)
        self.assertIn('REVIEW_REQUIRED',out.getvalue())

    def test_no_QMT_or_fs_writer_import(self):
        import inspect
        src=inspect.getsource(B)
        for pattern in ('xtquant','download_history_data(', 'pq.write_table(', 'os.replace('):
            self.assertNotIn(pattern,src)

if __name__=='__main__':unittest.main()
