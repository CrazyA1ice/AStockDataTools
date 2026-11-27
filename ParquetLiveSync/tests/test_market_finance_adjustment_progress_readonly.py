"""Synthetic bounded source-free financial/adjustments checkpoint metadata audit."""
from __future__ import annotations

import contextlib
from io import StringIO
import inspect as inspect_module
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_finance_adjustment_progress_readonly as S


class CurrentLedgersTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.module = Path(self.temp.name) / 'module'
        self.workspace = self.module / 'work' / 'qmt_extra'
        self.workspace.mkdir(parents=True)
        self.stock = Path(self.temp.name) / 'stock'
        self.extra = self.stock / 'AllCycleAStockData' / 'qmt_extra'
        self.extra.mkdir(parents=True)
        for period in S.EXTRA.L.PERIODS:
            (self.extra.parent / period).mkdir()
        self.expected_root = str(self.extra.resolve())

    def supplementary(self, **overrides):
        default = {
            'format': S.EXTRA.FORMAT, 'root': self.expected_root,
            'cursor': {'financial': '000001.SZ',
                       'adjustments': '600000.SH'},
            'last_asof': '2026-11-27',
            'financial_pending': {
                '000001.SZ': {'table': 'Capital', 'attempts': 3}},
        }
        default.update(overrides)
        return default

    def cache(self, **overrides):
        default = {
            'format': S.CACHE.FORMAT, 'root': self.expected_root,
            'import_cursor': '000001.SZ',
            'daily_date': '2026-11-27',
            'daily_cursor': '600000.SH',
            'pending_retry_cursor': '000001.SZ',
            'daily_sweep_start': '2026-11-25',
            'daily_sweep_reached_end': False,
            'daily_sweep_finished': '',
            'pending': {
                '000010.SZ': {'reason': 'SOURCE_HISTORY_CONFLICT', 'attempts': 2},
                '600001.SH': {'reason': 'NO_CACHE', 'attempts': 1}},
        }
        default.update(overrides)
        return default

    def write(self, name, value):
        p = self.workspace / name
        p.write_text(json.dumps(value), encoding='utf-8')
        return p

    def test_01_no_files_never_claims_complete_or_generates_defaults(self):
        result = S.inspect(self.module, self.stock)
        self.assertEqual(result['ledgers_present'], 0)
        self.assertFalse(result['supplementary_progress']['present'])
        self.assertFalse(result['financial_cache_progress']['present'])
        self.assertEqual(list(self.workspace.iterdir()), [])
        self.assertFalse(result['finance_full_history_coverage_certified'])
        self.assertFalse(result['adjustments_universe_exhaustion_certified'])
        self.assertFalse(result['original_run_receipt_authenticated'])

    def test_02_two_valid_physical_checkpoints_are_not_aggregated(self):
        self.write('progress.json', self.supplementary())
        self.write('financial-cache-progress.json', self.cache())
        result = S.inspect(self.module, self.stock)
        self.assertEqual(result['ledgers_present'], 2)
        self.assertEqual(len(result['physical_ledgers']), 2)
        self.assertTrue(all(x['sha256'] and len(x['sha256']) == 64
                            for x in result['physical_ledgers']))
        a = result['supplementary_progress']
        b = result['financial_cache_progress']
        self.assertEqual(a['adjustments_cursor'], '600000.SH')
        self.assertEqual(a['financial_pending_count'], 1)
        self.assertEqual(a['financial_pending_by_table'], {'Capital': 1})
        self.assertEqual(b['pending_count'], 2)
        self.assertEqual(b['pending_reason_counts'],
                         {'NO_CACHE': 1, 'SOURCE_HISTORY_CONFLICT': 1})
        self.assertFalse(result['state_cross_file_atomic_snapshot_certified'])
        self.assertTrue(result['separate_progress_ledgers_not_aggregated'])

    def test_03_single_cache_missing_supplementary_is_observed_not_rebuilt(self):
        self.write('financial-cache-progress.json', self.cache())
        result = S.inspect(self.module, self.stock)
        self.assertEqual(result['ledgers_present'], 1)
        self.assertFalse(result['supplementary_progress']['present'])
        self.assertEqual(result['financial_cache_progress']['pending_count'], 2)
        self.assertFalse((self.workspace / 'progress.json').exists())

    def test_04_single_supplementary_missing_financial_is_observed(self):
        self.write('progress.json', self.supplementary())
        result = S.inspect(self.module, self.stock)
        self.assertEqual(result['ledgers_present'], 1)
        self.assertFalse(result['financial_cache_progress']['present'])
        self.assertEqual(result['supplementary_progress']['financial_pending_count'], 1)

    def test_05_root_identity_mismatch_never_accepted(self):
        self.write('progress.json', self.supplementary(root='C:/forged'))
        with self.assertRaisesRegex(S.ProgressError,
                                    'SUPPLEMENTARY_LEDGER_IDENTITY_INVALID'):
            S.inspect(self.module, self.stock)

    def test_06_cache_root_identity_mismatch_rejected(self):
        self.write('financial-cache-progress.json', self.cache(root='C:/forged'))
        with self.assertRaisesRegex(S.ProgressError,
                                    'FINANCIAL_CACHE_LEDGER_IDENTITY_INVALID'):
            S.inspect(self.module, self.stock)

    def test_07_invalid_financial_pending_reason_refused(self):
        self.write('financial-cache-progress.json', self.cache(
            pending={'000001.SZ': {'reason': 'APPROVED', 'attempts': 1}}))
        with self.assertRaisesRegex(S.ProgressError,
                                    'FINANCIAL_PENDING_ENTRY_INVALID'):
            S.inspect(self.module, self.stock)
        self.write('financial-cache-progress.json', self.cache(
            pending={'': {'reason': 'NO_CACHE', 'attempts': 1}}))
        with self.assertRaisesRegex(S.ProgressError,
                                    'FINANCIAL_PENDING_ENTRY_INVALID'):
            S.inspect(self.module, self.stock)

    def test_08_bad_pending_attempts_refused(self):
        self.write('progress.json', self.supplementary(
            financial_pending={'000001.SZ': {'table': 'Capital', 'attempts': 0}}))
        with self.assertRaisesRegex(S.ProgressError,
                                    'SUPPLEMENTARY_PENDING_MALFORMED'):
            S.inspect(self.module, self.stock)
        self.write('progress.json', self.supplementary(
            financial_pending={'': {'table': 'Capital', 'attempts': 1}}))
        with self.assertRaisesRegex(S.ProgressError,
                                    'SUPPLEMENTARY_PENDING_MALFORMED'):
            S.inspect(self.module, self.stock)

    def test_09_invalid_daily_date_refused(self):
        self.write('financial-cache-progress.json', self.cache(
            daily_date='2026-02-30'))
        with self.assertRaisesRegex(S.ProgressError,
                                    'PROGRESS_DATE_FIELD_INVALID'):
            S.inspect(self.module, self.stock)

    def test_10_unsupported_cursor_symbol_rejected(self):
        self.write('progress.json', self.supplementary(
            cursor={'financial': '???', 'adjustments': '600000.SH'}))
        with self.assertRaisesRegex(S.ProgressError,
                                    'PROGRESS_STOCK_CURSOR_INVALID'):
            S.inspect(self.module, self.stock)

    def test_11_invalid_json_fails_closed(self):
        (self.workspace / 'progress.json').write_text('{broken', encoding='utf-8')
        with self.assertRaisesRegex(S.ProgressError,
                                    'PROGRESS_LEDGER_INVALID_JSON'):
            S.inspect(self.module, self.stock)

    def test_12_single_file_size_budget_fails_before_parse(self):
        self.write('progress.json', self.supplementary())
        with mock.patch.object(S, 'MAX_FILE_BYTES', 5):
            with self.assertRaisesRegex(S.ProgressError,
                                        'PROGRESS_LEDGER_EMPTY_OR_SIZE_LIMIT'):
                S.inspect(self.module, self.stock)

    def test_13_state_changed_during_hash_sequence_is_detected(self):
        self.write('progress.json', self.supplementary())
        original = S._bytes
        calls = [0]

        def replace_during_inspection(root, name):
            calls[0] += 1
            if calls[0] == 3:
                self.write('progress.json', self.supplementary(last_asof='2026-11-26'))
            return original(root, name)

        with mock.patch.object(S, '_bytes', side_effect=replace_during_inspection):
            with self.assertRaisesRegex(S.ProgressError,
                                        'PROGRESS_LEDGER_CHANGED_DURING_CHECK'):
                S.inspect(self.module, self.stock)

    def test_14_symlink_progress_rejected_when_supported(self):
        target = self.workspace / 'real.json'
        target.write_text(json.dumps(self.supplementary()), encoding='utf-8')
        linked = self.workspace / 'progress.json'
        try:
            linked.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('symlink unavailable')
        with self.assertRaisesRegex(S.ProgressError,
                                    'PROGRESS_LEDGER_SYMLINK_FORBIDDEN'):
            S.inspect(self.module, self.stock)

    def test_15_cli_error_does_not_expose_private_root(self):
        with mock.patch.object(S, 'inspect',
                               side_effect=RuntimeError('D:/secret/private-root')):
            stream = StringIO()
            with contextlib.redirect_stdout(stream):
                rc = S.main(['--module-root', str(self.module),
                             '--stock-root', str(self.stock)])
        self.assertEqual(rc, 3)
        self.assertIn('LOCAL_PROGRESS_READONLY_REVIEW_REQUIRED', stream.getvalue())
        self.assertNotIn('D:/secret', stream.getvalue())

    def test_16_no_qmt_writer_or_historical_receipt_bypass(self):
        source = inspect_module.getsource(S)
        for banned in ('download_history_data(', 'get_market_data_ex(',
                       'write_bytes(', 'write_table(', 'mkdir(', 'unlink(',
                       'os.replace(', 'rename(', 'GAP.verify_original(',
                       'AUDIT.audit(', 'E._save_state('):
            self.assertNotIn(banned, source)
        self.assertEqual(S.RELATIVE, ('progress.json', 'financial-cache-progress.json'))
        self.assertEqual(S.STATUS,
                         'LOCAL_FINANCE_ADJUSTMENT_PROGRESS_BYTES_ONLY_NOT_COMPLETENESS_CERTIFIED')


if __name__ == '__main__':
    unittest.main()
