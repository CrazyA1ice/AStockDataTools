"""No-write physical target footprint and transaction blueprint tests."""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import contextlib
from io import StringIO
import json
import stat
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_market_recovery_review_plan import fixture
import market_recovery_review_plan as R
import market_recovery_transaction_preflight as F


def plan(day='2026-11-25',symbol='SH605336'):
    return R.build_review_plan(fixture(day=day,symbol=symbol))


class PreflightTests(unittest.TestCase):
    def test_eight_periods_one_day_single_scope(self):
        b=F.build_blueprint(plan(),layout_year=2026)
        self.assertEqual(b['eight_period_target_file_count'],8)
        self.assertEqual({x['relative_path'] for x in b['target_files']},
                         {p+'/2026-11.parquet' for p in F.PERIODS})
        self.assertEqual(b['transaction_status'],'BLOCKED_NOT_A_MARKET_CANDIDATE')
        self.assertEqual(b['staging_bytes_written'],0)
        self.assertEqual(b['production_bytes_written'],0)
        self.assertFalse(b['private_backup_materialized'])
        self.assertFalse(b['production_merge_authorized'])
        self.assertFalse(b['rollback_tested'])

    def test_different_tickers_same_month_deduplicate_target_files(self):
        p=plan()
        q=plan(symbol='SZ300462')
        p['requests'].extend(q['requests'])
        p['review_request_count']=p['producer_quarantined_source_period_records']=2
        p['plan_sha256']=R.digest({k:v for k,v in p.items() if k!='plan_sha256'})
        b=F.build_blueprint(p,layout_year=2026)
        self.assertEqual(b['recovery_review_request_count'],2)
        self.assertEqual(b['eight_period_target_file_count'],8)
        self.assertTrue(all(len(t['affected_review_request_ids'])==2 for t in b['target_files']))

    def test_cross_month_eight_periods_keep_distinct_targets(self):
        p=plan()
        q=plan(day='2026-10-14')
        p['window']=['2026-10-14','2026-11-25']
        p['requests'].extend(q['requests'])
        p['review_request_count']=p['producer_quarantined_source_period_records']=2
        p['plan_sha256']=R.digest({k:v for k,v in p.items() if k!='plan_sha256'})
        b=F.build_blueprint(p,layout_year=2026)
        self.assertEqual(b['eight_period_target_file_count'],16)

    def test_prior_year_annual_file_targets(self):
        b=F.build_blueprint(plan(day='2019-04-09'),layout_year=2026)
        self.assertTrue(all(t['relative_path'].endswith('/2019.parquet') for t in b['target_files']))

    def test_layout_year_explicit_changes_physical_targets(self):
        p=plan(day='2019-04-09')
        current=F.build_blueprint(p,layout_year=2019)
        archived=F.build_blueprint(p,layout_year=2020)
        self.assertEqual(current['target_files'][0]['relative_path'],'15min/2019-04.parquet')
        self.assertEqual(archived['target_files'][0]['relative_path'],'15min/2019.parquet')
        self.assertNotEqual(current['blueprint_sha256'],archived['blueprint_sha256'])

    def test_future_year_outside_declared_layout_refused(self):
        with self.assertRaisesRegex(F.PreflightError,'AFTER_DECLARED_LAYOUT_YEAR'):
            F.build_blueprint(plan(),layout_year=2025)

    def test_noninteger_and_out_of_range_year_refused(self):
        for year in (True,None,'2026',1800,2201):
            with self.subTest(year=year),self.assertRaises(F.PreflightError):
                F.build_blueprint(plan(),layout_year=year)

    def test_review_plan_evidence_tamper_refused(self):
        p=plan();p['requests'][0]['evidence']['producer_receipt_bytes_sha256']='e'*64
        with self.assertRaises(R.PlanError):F.build_blueprint(p,layout_year=2026)

    def test_review_plan_forged_admission_rejected(self):
        p=plan();p['market_files_written']=True
        p['plan_sha256']=R.digest({k:v for k,v in p.items() if k!='plan_sha256'})
        with self.assertRaises(R.PlanError):F.build_blueprint(p,layout_year=2026)

    def test_nine_different_tickers_generate_only_eight_physical_files(self):
        symbols=('SH605336','SZ300119','SZ300120','SZ300121','SZ300122',
                 'SZ300123','SZ300124','SZ300125','SZ300462')
        p=plan(symbol=symbols[0])
        for symbol in symbols[1:]:p['requests'].extend(plan(symbol=symbol)['requests'])
        p['review_request_count']=p['producer_quarantined_source_period_records']=len(symbols)
        p['plan_sha256']=R.digest({k:v for k,v in p.items() if k!='plan_sha256'})
        b=F.build_blueprint(p,layout_year=2026)
        self.assertEqual(b['eight_period_target_file_count'],8)
        self.assertTrue(all(len(x['affected_review_request_ids'])==9 for x in b['target_files']))
        self.assertFalse(b['market_quality_cleared'])

    def test_empty_review_plan_does_not_certify_commit(self):
        p=plan();p['requests']=[]
        p['review_request_count']=p['producer_quarantined_source_period_records']=0
        p['plan_sha256']=R.digest({k:v for k,v in p.items() if k!='plan_sha256'})
        b=F.build_blueprint(p,layout_year=2026)
        self.assertEqual(b['eight_period_target_file_count'],0)
        self.assertFalse(b['production_merge_authorized'])

    def test_target_footprint_readonly_per_file_sha(self):
        with TemporaryDirectory() as td:
            root=Path(td);base=root/'AllCycleAStockData'
            for period in F.PERIODS:(base/period).mkdir(parents=True)
            file=base/'1min'/'2026-11.parquet';file.write_bytes(b'temporary-parquet-bytes')
            original=file.read_bytes();modified=file.stat().st_mtime_ns
            layout=types.SimpleNamespace(storage_root=lambda p,require_all=True: base)
            with mock.patch.dict(sys.modules,{'local_layout':layout}):
                b=F.build_blueprint(plan(),layout_year=2026,target_root=root)
            self.assertEqual(b['physical_target_files_checked'],8)
            targets={t['relative_path']:t for t in b['target_files']}
            info=targets['1min/2026-11.parquet']['file_observation']
            self.assertEqual(info['bytes_sha256'],sha256(original).hexdigest())
            self.assertEqual(info['state'],'EXISTING_BYTES_OBSERVED_NOT_BACKED_UP')
            self.assertTrue(all(t['file_observation']['state']=='ABSENT_BLOCKED' for k,t in targets.items() if k!='1min/2026-11.parquet'))
            self.assertEqual(file.read_bytes(),original)
            self.assertEqual(file.stat().st_mtime_ns,modified)
            self.assertFalse(b['source_snapshot_is_rollback_backup'])

    def test_symlinked_target_refused_even_if_exists(self):
        with TemporaryDirectory() as td:
            root=Path(td);base=root/'AllCycleAStockData'
            for period in F.PERIODS:(base/period).mkdir(parents=True)
            actual=base/'1min'/'actual.parquet';actual.write_bytes(b'synthetic data')
            link=base/'1min'/'2026-11.parquet'
            try: link.symlink_to(actual)
            except (OSError,NotImplementedError):self.skipTest('symlink unavailable')
            layout=types.SimpleNamespace(storage_root=lambda p,require_all=True:base)
            with mock.patch.dict(sys.modules,{'local_layout':layout}):
                with self.assertRaisesRegex(F.PreflightError,'TARGET_SYMLINK_FORBIDDEN'):
                    F.build_blueprint(plan(),layout_year=2026,target_root=root)

    def test_target_read_error_fail_closed(self):
        with TemporaryDirectory() as td:
            root=Path(td);base=root/'AllCycleAStockData'
            for period in F.PERIODS:(base/period).mkdir(parents=True)
            target=base/'1min'/'2026-11.parquet';target.mkdir()
            layout=types.SimpleNamespace(storage_root=lambda p,require_all=True:base)
            with mock.patch.dict(sys.modules,{'local_layout':layout}):
                with self.assertRaisesRegex(F.PreflightError,'TARGET_NOT_REGULAR_FILE'):
                    F.build_blueprint(plan(),layout_year=2026,target_root=root)

    def test_physical_root_only_checked_when_explicit(self):
        b=F.build_blueprint(plan(),layout_year=2026)
        self.assertFalse(b['physical_target_checks_requested'])
        self.assertEqual(b['physical_target_files_checked'],0)
        self.assertTrue(all(t['file_observation']['state']=='NOT_INSPECTED_NO_TARGET_ROOT' for t in b['target_files']))

    def test_blueprint_digest_covers_target_observations(self):
        b=F.build_blueprint(plan(),layout_year=2026)
        self.assertEqual(b['blueprint_sha256'],R.digest({k:v for k,v in b.items() if k!='blueprint_sha256'}))

    def test_source_plan_revision_changes_blueprint_hash_without_new_paths(self):
        a=plan();b=deepcopy(a)
        b['requests'][0]['evidence']['producer_receipt_bytes_sha256']='6'*64
        b['requests'][0]['evidence_revision_sha256']=R.digest(b['requests'][0]['evidence'])
        b['plan_sha256']=R.digest({k:v for k,v in b.items() if k!='plan_sha256'})
        t1=F.build_blueprint(a,layout_year=2026)
        t2=F.build_blueprint(b,layout_year=2026)
        self.assertNotEqual(t1['blueprint_sha256'],t2['blueprint_sha256'])
        self.assertEqual([r['relative_path'] for r in t1['target_files']],
                         [r['relative_path'] for r in t2['target_files']])

    def test_cli_missing_module_root_redacts_private_paths(self):
        b=StringIO()
        with contextlib.redirect_stdout(b):
            rc=F.main(['--module-root','/private/secret','--start-day','2026-11-25',
                       '--end-day','2026-11-25','--layout-year','2026','--summary-only'])
        self.assertEqual(rc,3)
        self.assertNotIn('/private/secret',b.getvalue())

    def test_cli_layout_year_required(self):
        import inspect
        source=inspect.getsource(F)
        self.assertIn("p.add_argument('--layout-year', type=int, required=True)",source)

    def test_no_permission_to_write_or_generate_candidate(self):
        report=F.build_blueprint(plan(),layout_year=2026)
        for key in ('native_minute_payload_present','private_candidate_materialized',
                    'private_backup_materialized','rollback_tested',
                    'production_merge_authorized','qmt_cache_write_authorized',
                    'qmt_history_download_authorized','market_parquet_or_h5_write_authorized'):
            self.assertFalse(report[key])
        self.assertEqual(report['qmt_history_download_calls'],0)

    def test_invalid_unsigned_plan_refused(self):
        with self.assertRaises(R.PlanError):F.build_blueprint({},layout_year=2026)

    def test_invalid_target_root_propagates_fail_closed(self):
        with mock.patch.dict(sys.modules,{'local_layout':types.SimpleNamespace(storage_root=lambda *a,**kw: (_ for _ in ()).throw(ValueError('LAYOUT_INVALID')))}):
            with self.assertRaisesRegex(ValueError,'LAYOUT_INVALID'):
                F.build_blueprint(plan(),layout_year=2026,target_root='/invalid')

    def test_no_project_writers_used(self):
        import inspect
        source=inspect.getsource(F)
        for forbidden in ('write_table(', 'write_bytes(', 'os.replace(', 'download_history_data(', 'CreateFile(', 'shutil.copyfile('):
            self.assertNotIn(forbidden,source)


if __name__=='__main__':unittest.main()
