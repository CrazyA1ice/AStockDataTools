"""Real synthetic evidence-chain bytes; immutable historical receipt opt-in tests."""
from __future__ import annotations

import contextlib
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audit_market_quarantine_readonly as AUDIT
import market_historical_receipt_sha_locator_readonly as LOC
import market_nine_quarantine_offline_source_gap_readonly as GAP


class PinnedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.module=Path(self.tmp.name)
        self.work=self.module/'work'
        self.work.mkdir()
        daily=self.work/'market_update'/'daily'
        daily.mkdir(parents=True)
        self.day='2026-11-25'
        candidate=daily/(self.day+'.parquet')
        candidate.write_bytes(b'private candidate fixture, not actual Parquet')
        self.candidate_sha=sha256(candidate.read_bytes()).hexdigest()
        q={
            **{'SZ300'+str(i):'ValueError: QMT returned no original OHLCVA 1m: not supplied'
               for i in range(119,126)},
            'SH605336':'ValueError: Independent official DAY materialized OHLC discrepancy: open',
            'SZ300462':'ValueError: Independent official DAY materialized OHLC discrepancy: open',
        }
        meta={'format':'one_command_qmt_market_update_v1',
              'date':self.day,'sha256':self.candidate_sha,
              'rows':5206*240,'stock_days_accepted':5206,
              'expected_stock_days':5215,'quarantined':q}
        (daily/(self.day+'.json')).write_text(json.dumps(meta),encoding='utf-8')
        self.stage=self.work/'unified-original-stage.log'
        self.stage.write_text(AUDIT.MARKER+json.dumps({
            'date':self.day,'sha256':self.candidate_sha,
            'accepted':5206,'quarantine':9,'rows':5206*240})+'\n',encoding='utf-8')
        receipt={'format':'qmt_daily_single_trigger_v3',
                 'invocation':'Scheduled','run_scope':'ALL_FOUR_SECTIONS',
                 'history_only':False,'china_start':'2026-11-25T15:20:00',
                 'stage_records':{'EIGHT_PERIODS':{
                     'exit_code':0,'log_path':str(self.stage)}}}
        self.history=self.work/'history'
        self.history.mkdir()
        self.original=self.history/'original-20261125.json'
        self.original.write_bytes(json.dumps(receipt,sort_keys=True).encode('utf-8'))
        self.expected=sha256(self.original.read_bytes()).hexdigest()
        self.latest=self.work/'last-afternoon-unified.json'
        self.latest.write_bytes(b'{"current":"2026-11-26","newer":true}')
        (self.work/'probes').mkdir()
        self.probes=self.work/'probes'

    def audit(self,**kw):
        return AUDIT.audit(self.module,self.day,self.expected,verify_parquet=True,**kw)

    def locator(self,**kw):
        with mock.patch.object(LOC,'TARGET_SHA',self.expected):
            return LOC.locate(self.module,target_sha256=self.expected,**kw)

    def test_mutable_alias_refuses_historical_hash(self):
        with self.assertRaisesRegex(AUDIT.EvidenceError,'RUN_RECEIPT_SHA_MISMATCH'):
            self.audit()

    def test_explicit_archived_receipt_preserves_original_eight_periods_chain(self):
        o=self.audit(receipt_relative='history/original-20261125.json')
        self.assertEqual(o['accepted'],5206)
        self.assertEqual(o['quarantined'],9)
        self.assertEqual(o['expected'],5215)
        self.assertTrue(o['parquet_content_sha_verified'])
        self.assertFalse(o['data_quality_cleared'])

    def test_explicit_original_wrong_sha_does_not_bypass_pin(self):
        with self.assertRaisesRegex(AUDIT.EvidenceError,'RUN_RECEIPT_SHA_MISMATCH'):
            AUDIT.audit(self.module,self.day,'f'*64,True,
                        receipt_relative='history/original-20261125.json')

    def test_archived_receipt_bad_chained_stage_log_rejected(self):
        self.stage.write_bytes(b'not the right Nov25 stage')
        with self.assertRaisesRegex(AUDIT.EvidenceError,'STAGED_TARGET_DATE_COUNT_0'):
            self.audit(receipt_relative='history/original-20261125.json')

    def test_archived_receipt_modified_candidate_parquet_rejected(self):
        (self.work/'market_update'/'daily'/(self.day+'.parquet')).write_bytes(b'changed!')
        with self.assertRaisesRegex(AUDIT.EvidenceError,'PHYSICAL_PARQUET_SHA_MISMATCH'):
            self.audit(receipt_relative='history/original-20261125.json')

    def test_receipt_relative_traversal_and_absolute_rejected(self):
        for path in ('../secret.json','history/../file.json','/tmp/file.json',
                     'C:/invalid.json','history//original.json','history\\.json',
                     'history/original-20261125.txt'):
            with self.subTest(path=path):
                with self.assertRaisesRegex(AUDIT.EvidenceError,'RELATIVE_PATH_INVALID'):
                    self.audit(receipt_relative=path)

    def test_missing_in_work_explicit_receipt_rejected(self):
        with self.assertRaisesRegex(AUDIT.EvidenceError,'OUTSIDE_WORK_OR_MISSING'):
            self.audit(receipt_relative='missing.json')

    def test_explicit_symlink_receipt_fails_closed(self):
        link=self.work/'alias.json'
        try: link.symlink_to(self.original)
        except (OSError,NotImplementedError): self.skipTest('symlink not available')
        with self.assertRaisesRegex(AUDIT.EvidenceError,'SYMLINK_FORBIDDEN'):
            self.audit(receipt_relative='alias.json')

    def test_locator_finds_matching_nested_bytes_without_replacing_latest(self):
        before=self.latest.read_bytes()
        r=self.locator(max_depth=2)
        self.assertEqual(r['matching_file_count'],1)
        self.assertEqual(r['exact_original_receipt_sha_matches'][0]['receipt_relative_within_work'],
                         'history/original-20261125.json')
        self.assertFalse(r['original_run_and_stage_log_chain_verified'])
        self.assertFalse(r['production_market_write_authorized'])
        self.assertEqual(self.latest.read_bytes(),before)

    def test_locator_depth_zero_never_assumes_unsearched_archive_absent(self):
        r=self.locator(max_depth=0)
        self.assertEqual(r['matching_file_count'],0)
        self.assertTrue(r['no_match_in_scoped_files_only'])
        self.assertEqual(r['maximum_child_directory_depth_explored'],0)

    def test_locator_explicit_history_subdirectory_depth_zero(self):
        r=self.locator(search_subdir='history',max_depth=0)
        self.assertEqual(r['matching_file_count'],1)
        self.assertEqual(r['search_subdir_relative_to_installed_work'],'history')

    def test_locator_rejects_unbounded_depth_and_wrong_sha(self):
        with self.assertRaisesRegex(LOC.ReceiptLocateError,'DEPTH_OUTSIDE_BOUND'):
            self.locator(max_depth=10)
        with self.assertRaisesRegex(LOC.ReceiptLocateError,'FIXED_SHA_REQUIRED'):
            LOC.locate(self.module,target_sha256='f'*64)

    def test_locator_rejects_search_outside_work(self):
        for path in ('../','/','C:/','history\\', 'history/../archive'):
            with self.subTest(path=path),self.assertRaisesRegex(LOC.ReceiptLocateError,'SUBDIRECTORY_INVALID'):
                self.locator(search_subdir=path)

    def test_locator_refuses_symlink_search_entry(self):
        link=self.work/'link.json'
        try:link.symlink_to(self.original)
        except (OSError,NotImplementedError):self.skipTest('symlink unavailable')
        with self.assertRaisesRegex(LOC.ReceiptLocateError,'SYMLINK_ENTRY_REJECTED'):
            self.locator()

    def test_locator_refuses_entry_budget_exceeded(self):
        for i in range(7):
            (self.work/f'file{i}.txt').write_text('x')
        with mock.patch.object(LOC,'MAX_ENTRIES',1):
            with self.assertRaisesRegex(LOC.ReceiptLocateError,'ENTRY_BUDGET'):
                self.locator()

    def test_locator_reports_oversize_files_not_silent_global_absence(self):
        with mock.patch.object(LOC,'MAX_READ_BYTES',12):
            r=self.locator()
        self.assertGreaterEqual(len(r['oversize_or_empty_json_relative_paths_not_hashed']),1)
        self.assertEqual(r['matching_file_count'],0)
        self.assertFalse(r['scope_exhaustive'])

    def test_locator_rejects_total_bytes_budget(self):
        with mock.patch.object(LOC,'MAX_BYTES_TOTAL',1):
            with self.assertRaisesRegex(LOC.ReceiptLocateError,'TOTAL_JSON_BYTES_BUDGET'):
                self.locator()

    def test_locator_rejects_unbounded_json_candidate_count(self):
        with mock.patch.object(LOC,'MAX_JSON',1):
            with self.assertRaisesRegex(LOC.ReceiptLocateError,'JSON_CANDIDATE_BUDGET'):
                self.locator()

    def test_compatibility_original_audit_default_unchanged(self):
        self.latest.write_bytes(self.original.read_bytes())
        r=self.audit()
        self.assertEqual(r['run_receipt_sha256'],self.expected)
        self.assertTrue(r['parquet_content_sha_verified'])

    def test_p311_nine_gap_scan_with_authenticated_local_receipt_bytes_still_blocked_admission(self):
        # Only this synthetic-fixture test substitutes its temporary receipt hash.
        # Production GAP.RUN_SHA remains the pinned actual 2026-11-25 digest.
        production_sha = GAP.RUN_SHA
        with mock.patch.object(GAP, 'RUN_SHA', self.expected):
            r=GAP.inspect(self.module,self.probes,
                          receipt_relative='history/original-20261125.json')
            self.assertEqual(r['pinned_run_receipt_sha256'], self.expected)
        self.assertEqual(GAP.RUN_SHA, production_sha)
        self.assertEqual(r['original_quarantined_stock_days'],9)
        self.assertEqual(r['selected_receipt_relative_to_work'],'history/original-20261125.json')
        self.assertEqual(r['existing_probe_files_content_checked'],0)
        self.assertEqual(r['nine_quarantine_source_status_counts'],
                         {'NO_MATCHING_VALIDATED_JSONL_IN_EXPLICIT_PROBE_DIRECTORY':9})
        self.assertFalse(r['supplier_origin_authenticated'])
        self.assertFalse(r['original_quarantines_cleared'])
        self.assertFalse(r['market_files_written'])

    def test_p311_without_explicit_archived_receipt_still_refuses_mismatched_alias(self):
        with self.assertRaisesRegex(AUDIT.EvidenceError,'RUN_RECEIPT_SHA_MISMATCH'):
            GAP.inspect(self.module,self.probes)

    def test_real_historical_archive_alone_not_asserted_as_official_provenance(self):
        a=self.locator()
        self.assertFalse(a['qmt_provider_authenticated'])
        self.assertFalse(a['producer_quarantine_cleared'])
        self.assertFalse(a['market_files_written'])
        self.assertEqual(a['qmt_download_calls'],0)

    def test_cli_error_does_not_print_private_absolute_path(self):
        out=StringIO()
        with contextlib.redirect_stdout(out):
            status=LOC.main(['--module-root','/private/sensitive-absolute-path'])
        self.assertEqual(status,3)
        self.assertNotIn('sensitive-absolute-path',out.getvalue())

    def test_new_modules_do_not_write_market_data_or_call_qmt(self):
        import inspect
        for obj in (LOC,GAP):
            src=inspect.getsource(obj)
            for phrase in ('download_history_data(', 'get_market_data_ex(',
                           'write_bytes(', 'write_table(', 'os.replace(', 'mkdir('):
                self.assertNotIn(phrase,src)


if __name__=='__main__':unittest.main()
