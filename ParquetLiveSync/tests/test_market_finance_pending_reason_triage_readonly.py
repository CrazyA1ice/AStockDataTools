"""Pinned ledger-only finance pending category evidence; all fixtures synthetic."""
from __future__ import annotations

import contextlib
from hashlib import sha256
from io import StringIO
import inspect as inspect_module
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_finance_pending_reason_triage_readonly as S


class FinancialPendingTriageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.module = root / 'module'
        self.dir = self.module / 'work' / 'qmt_extra'
        self.dir.mkdir(parents=True)
        self.stock = root / 'stock'
        self.extra = self.stock / 'AllCycleAStockData' / 'qmt_extra'
        self.extra.mkdir(parents=True)
        for period in S.EXTRA.L.PERIODS:
            (self.extra.parent / period).mkdir()

    def item(self, reason, attempts=1, asof='2026-11-25', detail=None):
        d = {'reason': reason, 'attempts': attempts}
        if asof is not None:
            d['asof'] = asof
        if detail is not None:
            d['detail'] = detail
        return d

    def ledger(self, pending=None, **updates):
        doc = {
            'format': S.LEDGER.CACHE.FORMAT,
            'root': str(self.extra.resolve()),
            'import_cursor': '920992.BJ',
            'daily_date': '2026-11-25',
            'daily_cursor': '002639.SZ',
            'daily_sweep_reached_end': False,
            'daily_sweep_start': '2026-11-19',
            'daily_sweep_finished': '2026-11-18',
            'pending_retry_cursor': '688259.SH',
            'pending': pending if pending is not None else {},
        }
        doc.update(updates)
        return doc

    def write(self, value):
        data = json.dumps(value, ensure_ascii=False,
                          separators=(',', ':')).encode('utf-8')
        (self.dir / S.NAME).write_bytes(data)
        return sha256(data).hexdigest()

    def read(self, expected):
        return S.inspect(self.module, self.stock, expected)

    def test_01_empty_ledger_counts_zero_without_claiming_completeness(self):
        digest = self.write(self.ledger())
        out = self.read(digest)
        self.assertEqual(out['ledger_saved_pending_count'], 0)
        self.assertEqual(out['pending_reason_counts'], {})
        self.assertEqual(out['physical_ledger_sha256'], digest)
        for k in ('full_history_coverage_certified',
                  'financial_repair_authorized',
                  'original_run_receipt_authenticated',
                  'original_quarantines_cleared', 'market_files_written'):
            self.assertFalse(out[k], k)

    def test_02_original_77_reason_type_counts_are_not_assumed(self):
        data = {
            '000001.SZ': self.item('SOURCE_HISTORY_CONFLICT', 2,
                detail='SOURCE_HISTORY_CONFLICT 000001.SZ table=Capital removed_or_revised=3'),
            '600000.SH': self.item('CACHE_DECODE_ERROR', 1,
                detail='QMT provider UTF-8 decode failed twice even for one stock'),
            '688001.SH': self.item('NO_CACHE', 5)}
        digest = self.write(self.ledger(data))
        out = self.read(digest)
        self.assertEqual(out['ledger_saved_pending_count'], 3)
        self.assertEqual(out['pending_reason_counts'], {
            'SOURCE_HISTORY_CONFLICT': 1, 'CACHE_DECODE_ERROR': 1, 'NO_CACHE': 1})
        self.assertEqual(out['source_history_conflict_table_counts_if_exact_detail'],
                         {'Capital': 1})
        self.assertEqual(out['source_history_conflict_detail_classes'],
                         {'RAW_HISTORICAL_VARIANT_REMOVED_OR_REVISED': 1})
        self.assertEqual(out['pending_attempts_buckets'], {'1': 1, '2-3': 1, '4-9': 1})
        self.assertFalse(out['raw_history_data_compared'])
        self.assertFalse(out['financial_source_provider_authenticated'])

    def test_03_noncapital_strict_raw_history_conflict_preserves_table_only(self):
        reason = 'SOURCE_HISTORY_CONFLICT 600000.SH table=Balance removed_or_revised=20'
        dig = self.write(self.ledger({'600000.SH': self.item(
            'SOURCE_HISTORY_CONFLICT', detail=reason)}))
        out = self.read(dig)
        self.assertEqual(out['source_history_conflict_table_counts_if_exact_detail'],
                         {'Balance': 1})
        self.assertNotIn('600000.SH', json.dumps(out, ensure_ascii=False))

    def test_04_scoped_capital_proof_is_review_only_not_approval(self):
        detail = ('SOURCE_HISTORY_CONFLICT 000001.SZ table=Capital '
                  'scoped_m_quarter_proof=REPORT_KEYS_ADDED_OR_REMOVED')
        digest = self.write(self.ledger({'000001.SZ': self.item(
            'SOURCE_HISTORY_CONFLICT', detail=detail)}))
        out = self.read(digest)
        self.assertEqual(out['source_history_conflict_detail_classes'], {
            'SCOPED_CAPITAL_PROOF_REPORT_KEYS_ADDED_OR_REMOVED': 1})
        self.assertFalse(out['financial_repair_authorized'])

    def test_05_unknown_message_not_assumed_safe_or_disclosed(self):
        raw = 'Sensitive secret: C:/private/finance/hidden-file'
        digest = self.write(self.ledger({'000001.SZ': self.item(
            'SOURCE_HISTORY_CONFLICT', detail=raw)}))
        out = self.read(digest)
        self.assertEqual(out['unparsed_source_conflicts_not_assumed_safe'], 1)
        self.assertNotIn('Sensitive secret', json.dumps(out))
        self.assertNotIn('C:/private', json.dumps(out))

    def test_06_mismatched_embedded_stock_code_refused_as_valid_proof(self):
        raw = 'SOURCE_HISTORY_CONFLICT 000002.SZ table=Capital removed_or_revised=2'
        digest = self.write(self.ledger({'000001.SZ': self.item(
            'SOURCE_HISTORY_CONFLICT', detail=raw)}))
        out = self.read(digest)
        self.assertEqual(out['source_history_conflict_detail_classes'],
                         {'UNCLASSIFIED_DETAIL': 1})

    def test_07_missing_detail_is_unclassified_not_implied_ok(self):
        digest = self.write(self.ledger({'000001.SZ': self.item(
            'SOURCE_HISTORY_CONFLICT', detail=None)}))
        out = self.read(digest)
        self.assertEqual(out['unparsed_source_conflicts_not_assumed_safe'], 1)

    def test_08_large_retry_count_buckets_preserve_counts(self):
        pending = {
            '000001.SZ': self.item('NO_CACHE', 1),
            '000002.SZ': self.item('NO_CACHE', 2),
            '000003.SZ': self.item('NO_CACHE', 3),
            '000004.SZ': self.item('NO_CACHE', 4),
            '000005.SZ': self.item('NO_CACHE', 9),
            '000006.SZ': self.item('NO_CACHE', 10)}
        digest = self.write(self.ledger(pending))
        out = self.read(digest)
        self.assertEqual(out['pending_attempts_buckets'],
                         {'1': 1, '2-3': 2, '4-9': 2, '10+': 1})
        self.assertEqual(sum(out['pending_attempts_buckets'].values()), 6)

    def test_09_pending_asof_months_and_missing_are_aggregate_only(self):
        pending = {
            '000001.SZ': self.item('NO_CACHE', asof='2026-10-30'),
            '000002.SZ': self.item('NO_CACHE', asof='2026-11-25'),
            '000003.SZ': self.item('NO_CACHE', asof=None)}
        digest = self.write(self.ledger(pending))
        out = self.read(digest)
        self.assertEqual(out['pending_asof_earliest'], '2026-10-30')
        self.assertEqual(out['pending_asof_latest'], '2026-11-25')
        self.assertEqual(out['pending_asof_month_counts'],
                         {'2026-10': 1, '2026-11': 1})
        self.assertEqual(out['pending_asof_missing'], 1)

    def test_10_invalid_saved_asof_date_rejected(self):
        dig = self.write(self.ledger({'000001.SZ':
            self.item('NO_CACHE', asof='2026-02-30')}))
        with self.assertRaisesRegex(S.TriageError, 'PENDING_ASOF_INVALID'):
            self.read(dig)

    def test_11_identity_and_daily_fields_preserved(self):
        digest = self.write(self.ledger())
        out = self.read(digest)
        self.assertEqual(out['ledger_saved_daily_date'], '2026-11-25')
        self.assertEqual(out['ledger_saved_daily_cursor'], '002639.SZ')
        self.assertFalse(out['ledger_saved_daily_sweep_reached_end'])

    def test_12_wrong_pinned_sha_refuses_existing_bytes(self):
        self.write(self.ledger())
        with self.assertRaisesRegex(S.TriageError,
                                    'PINNED_FINANCIAL_CACHE_LEDGER_SHA_MISMATCH'):
            self.read('f' * 64)

    def test_13_invalid_sha_argument_rejected(self):
        self.write(self.ledger())
        with self.assertRaisesRegex(S.TriageError,
                                    'EXPECTED_LEDGER_SHA_REQUIRED'):
            self.read('not-sha')

    def test_14_missing_physical_file_never_constructed(self):
        with self.assertRaisesRegex(S.TriageError,
                                    'EXPLICIT_FINANCIAL_CACHE_LEDGER_MISSING'):
            self.read('f' * 64)
        self.assertFalse((self.dir / S.NAME).exists())

    def test_15_mutation_during_two_read_checks_detected(self):
        digest = self.write(self.ledger())
        native = S.LEDGER._bytes
        calls = [0]

        def changing(root, name):
            calls[0] += 1
            if calls[0] == 2:
                self.write(self.ledger(daily_date='2026-11-26'))
            return native(root, name)

        with mock.patch.object(S.LEDGER, '_bytes', side_effect=changing):
            with self.assertRaisesRegex(S.TriageError,
                     'PINNED_FINANCIAL_CACHE_LEDGER_CHANGED_DURING_TRIAGE'):
                self.read(digest)

    def test_16_cli_error_hides_absolute_user_path(self):
        with mock.patch.object(S, 'inspect',
                               side_effect=RuntimeError('D:/sensitive/path')):
            output = StringIO()
            with contextlib.redirect_stdout(output):
                code = S.main(['--module-root', str(self.module),
                               '--stock-root', str(self.stock),
                               '--expected-ledger-sha256', 'f' * 64])
        self.assertEqual(code, 3)
        self.assertIn('FINANCIAL_PENDING_REASON_TRIAGE_REVIEW_REQUIRED',
                      output.getvalue())
        self.assertNotIn('D:/sensitive', output.getvalue())

    def test_17_no_qmt_downloads_writes_or_original_receipt_bypass(self):
        source = inspect_module.getsource(S)
        for unsafe in ('download_history_data(', 'get_market_data_ex(',
                       'write_bytes(', 'write_table(', 'mkdir(', 'unlink(',
                       'os.replace(', 'rename(', 'GAP.verify_original(',
                       'AUDIT.audit('):
            self.assertNotIn(unsafe, source)
        self.assertEqual(S.NAME, 'financial-cache-progress.json')
        self.assertEqual(S.STATUS,
                         'PINNED_SAVED_FINANCE_PENDING_CATEGORIES_ONLY_NO_HISTORY_REPAIR')


if __name__ == '__main__':
    unittest.main()
