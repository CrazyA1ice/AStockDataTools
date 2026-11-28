"""No QMT; synthetic immutable financial snapshot bytes and active pins only."""
from __future__ import annotations

import contextlib
from hashlib import sha256
from io import StringIO
import inspect as inspection
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_finance_prior_snapshot_census_readonly as S


class PriorFinanceSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        parent = Path(self.tmp.name)
        self.module = parent / 'module'
        self.work = self.module / 'work' / 'qmt_extra'
        self.work.mkdir(parents=True)
        self.stock = parent / 'stock'
        self.extra = self.stock / 'AllCycleAStockData' / 'qmt_extra'
        self.extra.mkdir(parents=True)
        for period in S.EXTRA.L.PERIODS:
            (self.extra.parent / period).mkdir()
        self.fin = self.extra / 'financial'
        self.fin.mkdir()

    def conflict(self, stock='000001.SZ', table='Top10Holder', *,
                 detail=None):
        return {
            'reason': 'SOURCE_HISTORY_CONFLICT',
            'attempts': 1, 'asof': '2026-11-25',
            'detail': detail or
                ('SOURCE_HISTORY_CONFLICT ' + stock +
                 ' table=' + table + ' removed_or_revised=2')
        }

    def ledger(self, pending=None):
        return {
            'format': S.LEDGER.CACHE.FORMAT, 'root': str(self.extra.resolve()),
            'import_cursor': '', 'daily_cursor': '002639.SZ',
            'daily_date': '2026-11-25',
            'daily_sweep_reached_end': False,
            'pending': pending if pending is not None else {
                '000001.SZ': self.conflict()},
        }

    def save(self, pending=None):
        data = json.dumps(self.ledger(pending), ensure_ascii=False).encode('utf-8')
        (self.work / S.NAME).write_bytes(data)
        return sha256(data).hexdigest()

    def snapshot(self, table='Top10Holder', stock='000001.SZ',
                 day='2026-11-23', suffix='a'*16, data=b'synthetic-parquet-bytes'):
        folder = self.fin / table / stock / 'snapshots'
        folder.mkdir(parents=True, exist_ok=True)
        name = day + '-' + suffix + '.parquet'
        (folder / name).write_bytes(data)
        return folder / name

    def pin(self, path, table='Top10Holder', stock='000001.SZ', **updates):
        day = path.name[:10]
        target = path.parent.parent / 'active' / (day + '.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        document = {
            'format': 'qmt_financial_active_v1',
            'symbol': stock, 'table': table, 'asof': day,
            'filename': path.name,
            'sha256': sha256(path.read_bytes()).hexdigest()}
        document.update(updates)
        target.write_text(json.dumps(document), encoding='utf-8')
        return target

    def run_scan(self, digest):
        return S.inspect(self.module, self.stock, digest)

    def test_01_empty_pending_scans_nothing_and_claims_no_repair(self):
        digest = self.save({})
        value = self.run_scan(digest)
        self.assertEqual(value['scopes_from_exact_conflict_details'], 0)
        self.assertEqual(value['physical_snapshot_files_sha_verified'], 0)
        self.assertFalse(value['parquet_row_or_history_union_verified'])
        self.assertFalse(value['financial_repair_authorized'])
        self.assertFalse(value['original_quarantines_cleared'])
        self.assertEqual(value['qmt_download_calls'], 0)

    def test_02_missing_prior_directory_is_reported_not_created(self):
        digest = self.save()
        value = self.run_scan(digest)
        self.assertEqual(value['conflict_scopes_missing_snapshot_directory'], 1)
        self.assertEqual(value['physical_snapshot_files_sha_verified'], 0)
        self.assertFalse((self.fin / 'Top10Holder').exists())

    def test_03_single_legacy_snapshot_hashed_without_payload_claim(self):
        path = self.snapshot()
        digest = self.save()
        value = self.run_scan(digest)
        self.assertEqual(value['physical_snapshot_files_sha_verified'], 1)
        self.assertEqual(value['physical_snapshot_bytes_hashed'],
                         len(path.read_bytes()))
        self.assertEqual(value['asof_active_pin_resolution_status_counts'],
                         {'LEGACY_UNPINNED_UNIQUE': 1})
        self.assertEqual(value['table_scoped_counts']['Top10Holder']
                         ['historical_asof_dates_observed'], 1)
        self.assertFalse(value['parquet_row_or_history_union_verified'])

    def test_04_two_versions_one_day_without_pin_report_ambiguous(self):
        self.snapshot(suffix='a'*16)
        self.snapshot(suffix='b'*16)
        digest = self.save()
        value = self.run_scan(digest)
        self.assertEqual(value['physical_snapshot_files_sha_verified'], 2)
        self.assertEqual(value['asof_active_pin_resolution_status_counts'],
                         {'MULTIPLE_VERSIONS_NO_PIN_REVIEW': 1})
        self.assertFalse(value['all_source_history_conflicts_resolved'])

    def test_05_active_pin_physically_selects_one_of_two_versions(self):
        path = self.snapshot(suffix='a'*16)
        self.snapshot(suffix='b'*16)
        self.pin(path)
        digest = self.save()
        value = self.run_scan(digest)
        self.assertEqual(value['physical_snapshot_files_sha_verified'], 2)
        self.assertEqual(value['asof_active_pin_resolution_status_counts'],
                         {'ACTIVE_PIN_SELECTED_BYTES_MATCH': 1})

    def test_06_wrong_active_pin_sha_rejected(self):
        path = self.snapshot()
        self.pin(path, sha256='f'*64)
        digest = self.save()
        with self.assertRaisesRegex(
                S.SnapshotError, 'PRIOR_SNAPSHOT_ACTIVE_PIN_PHYSICAL_SHA_MISMATCH'):
            self.run_scan(digest)

    def test_07_wrong_active_pin_symbol_rejected(self):
        path = self.snapshot()
        self.pin(path, symbol='600000.SH')
        digest = self.save()
        with self.assertRaisesRegex(S.SnapshotError,
                                    'PRIOR_SNAPSHOT_ACTIVE_PIN_FIELDS_INVALID'):
            self.run_scan(digest)

    def test_08_active_pin_unknown_filename_rejected(self):
        path = self.snapshot()
        self.pin(path, filename='2026-11-23-'+'b'*16+'.parquet')
        digest = self.save()
        with self.assertRaisesRegex(S.SnapshotError,
                                    'PRIOR_SNAPSHOT_ACTIVE_PIN_FIELDS_INVALID'):
            self.run_scan(digest)

    def test_09_unexpected_non_snapshot_direct_filename_blocked(self):
        self.snapshot()
        path = self.fin / 'Top10Holder' / '000001.SZ' / 'snapshots'
        (path / 'unexpected.txt').write_text('no', encoding='utf-8')
        digest = self.save()
        with self.assertRaisesRegex(S.SnapshotError,
                                    'PRIOR_SNAPSHOT_UNEXPECTED_DIRECT_ENTRY'):
            self.run_scan(digest)

    def test_10_snapshot_symlink_refused_if_supported(self):
        path = self.snapshot()
        alias = path.parent / ('2026-11-24-' + 'b'*16 + '.parquet')
        try:
            alias.symlink_to(path)
        except (OSError, NotImplementedError):
            self.skipTest('symlink unavailable')
        digest = self.save()
        with self.assertRaisesRegex(S.SnapshotError,
                                    'PRIOR_SNAPSHOT_SYMLINK_FORBIDDEN'):
            self.run_scan(digest)

    def test_11_wrong_pinned_ledger_sha_refused_before_sources(self):
        self.save()
        with self.assertRaisesRegex(S.SnapshotError, 'PINNED_LEDGER_SHA_MISMATCH'):
            self.run_scan('f'*64)

    def test_12_unclassified_conflict_detail_blocks_scope_selection(self):
        digest = self.save({'000001.SZ': self.conflict(
            detail='untrusted unknown kind')})
        with self.assertRaisesRegex(S.SnapshotError,
                                    'PINNED_SOURCE_CONFLICT_SCOPE_UNCLASSIFIED'):
            self.run_scan(digest)

    def test_13_capital_report_key_conflict_uses_exact_capital_path(self):
        detail = ('SOURCE_HISTORY_CONFLICT 000001.SZ table=Capital '
                  'scoped_m_quarter_proof=REPORT_KEYS_ADDED_OR_REMOVED')
        self.snapshot(table='Capital')
        digest = self.save({'000001.SZ': self.conflict(detail=detail)})
        value = self.run_scan(digest)
        self.assertEqual(value['table_scoped_counts']['Capital']
                         ['physical_snapshot_files_sha_verified'], 1)
        self.assertNotIn('Top10Holder', value['table_scoped_counts'])
        self.assertFalse(value['all_source_history_conflicts_resolved'])

    def test_14_decode_error_entries_are_not_old_conflict_scopes(self):
        digest = self.save({'000001.SZ': {'reason': 'CACHE_DECODE_ERROR',
                                         'attempts': 5, 'asof': '2026-11-25'}})
        value = self.run_scan(digest)
        self.assertEqual(value['pinned_ledger_pending_count'], 1)
        self.assertEqual(value['scopes_from_exact_conflict_details'], 0)

    def test_15_scope_budget_is_enforced_before_snapshot_io(self):
        pending = {
            '000001.SZ': self.conflict('000001.SZ'),
            '000002.SZ': self.conflict('000002.SZ')}
        digest = self.save(pending)
        with mock.patch.object(S, 'MAX_CONFLICT_SCOPES', 1):
            with self.assertRaisesRegex(S.SnapshotError,
                                        'PRIOR_SNAPSHOT_STOCK_SCOPE_BUDGET'):
                self.run_scan(digest)

    def test_16_byte_budget_rejects_existing_file_not_truncate(self):
        self.snapshot(data=b'longer-than-one')
        digest = self.save()
        with mock.patch.object(S, 'MAX_TOTAL_FILE_BYTES', 1):
            with self.assertRaisesRegex(
                    S.SnapshotError,
                    'PRIOR_SNAPSHOT_TOTAL_BYTES_OR_SINGLE_FILE_BUDGET'):
                self.run_scan(digest)

    def test_17_mutable_ledger_modified_after_snapshot_scan_rejected(self):
        self.snapshot()
        digest = self.save()
        native = S.LEDGER._bytes
        calls = [0]

        def mutate_on_final(root, name):
            calls[0] += 1
            if calls[0] == 2:
                self.save({})
            return native(root, name)

        with mock.patch.object(S.LEDGER, '_bytes', side_effect=mutate_on_final):
            with self.assertRaisesRegex(
                    S.SnapshotError,
                    'PINNED_LEDGER_CHANGED_DURING_SNAPSHOT_CENSUS'):
                self.run_scan(digest)

    def test_18_cli_error_does_not_leak_private_stock_paths(self):
        stream = StringIO()
        with mock.patch.object(
                S, 'inspect', side_effect=RuntimeError('D:/private/stock-files')):
            with contextlib.redirect_stdout(stream):
                result = S.main([
                    '--module-root', str(self.module),
                    '--stock-root', str(self.stock),
                    '--expected-ledger-sha256', 'f'*64])
        self.assertEqual(result, 3)
        self.assertIn('PRIOR_FINANCIAL_SNAPSHOT_READONLY_REVIEW_REQUIRED',
                      stream.getvalue())
        self.assertNotIn('D:/private', stream.getvalue())

    def test_19_no_qmt_download_writer_or_original_receipt_bypass(self):
        source = inspection.getsource(S)
        for forbidden in (
                'download_history_data(', 'get_market_data_ex(',
                'write_bytes(', 'write_table(', 'mkdir(', 'unlink(',
                'os.replace(', 'rename(', 'GAP.verify_original(',
                'AUDIT.audit('):
            self.assertNotIn(forbidden, source)
        self.assertFalse(S.MAX_TOTAL_FILE_BYTES > 512*1024*1024)
        self.assertFalse(S.MAX_CONFLICT_SCOPES > 128)


if __name__ == '__main__':
    unittest.main()
