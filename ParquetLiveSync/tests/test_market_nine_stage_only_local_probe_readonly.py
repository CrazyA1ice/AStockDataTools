"""Synthetic-only bounded local minute probes; never use the original run receipt."""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
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
import market_nine_stage_only_local_probe_readonly as S
import market_native_minute_jsonl_readonly as MINUTE

CN = timezone(timedelta(hours=8))


def rows(symbol='000001.SZ', day='2026-11-12', grid=None):
    return [
        {'datetime_cn': datetime.fromisoformat(day).replace(
            hour=h, minute=m, tzinfo=CN).isoformat(),
         'symbol': symbol, 'open': 10., 'high': 11.,
         'low': 9., 'close': 10.5, 'volume': 10., 'amount': 105.}
        for h, m in sorted(MINUTE.GRID if grid is None else grid)
    ]


class StageOnlyProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.module = Path(self.tmp.name)
        self.work = self.module / 'work'
        self.probe = self.work / S.PROBE_SUBDIR
        self.probe.mkdir(parents=True)

    def write(self, name='probe.jsonl', records=None):
        if records is None:
            records = rows()
        data = b''.join((json.dumps(r, sort_keys=True) + '\n').encode('utf-8')
                        for r in records)
        (self.probe / name).write_bytes(data)
        return sha256(data).hexdigest()

    def test_01_empty_dir_retains_all_nine_without_provider_approval(self):
        value = S.inspect(self.module)
        self.assertEqual(value['existing_probe_files_content_checked'], 0)
        self.assertEqual(len(value['nine_quarantine_local_evidence']), 9)
        self.assertEqual(value['nine_local_status_counts'],
                         {'NO_MATCHING_VALIDATED_JSONL_IN_EXPLICIT_PROBE_DIRECTORY': 9})
        for key in ('original_run_receipt_authenticated',
                    'original_run_stage_link_verified',
                    'original_quarantines_cleared', 'production_merge_authorized',
                    'market_files_written', 'local_files_provider_authenticated'):
            self.assertFalse(value[key], key)
        self.assertEqual(value['qmt_download_calls'], 0)
        self.assertTrue(value['local_file_inventory_unchanged_during_scan'])

    def test_02_three_other_symbols_are_not_nine(self):
        for symbol in ('000001.SZ', '600000.SH', '688001.SH'):
            self.write(symbol.replace('.', '_') + '.jsonl', rows(symbol))
        value = S.inspect(self.module)
        self.assertEqual(value['existing_probe_files_content_checked'], 3)
        self.assertEqual(value['nine_local_status_counts'],
                         {'NO_MATCHING_VALIDATED_JSONL_IN_EXPLICIT_PROBE_DIRECTORY': 9})
        self.assertEqual(sorted(s['checked_rows'] for s in value['probe_source_scopes']),
                         [241, 241, 241])

    def test_03_same_symbol_only_nov12_does_not_cover_nov25(self):
        self.write('old.jsonl', rows('300119.SZ', '2026-11-12'))
        value = S.inspect(self.module)
        stock = next(x for x in value['nine_quarantine_local_evidence']
                     if x['quarantined_symbol'] == 'SZ300119')
        self.assertEqual(stock['local_source_status'],
                         'MATCHING_SYMBOL_BUT_NO_20261125_IN_OBSERVED_SPAN')
        self.assertEqual(stock['matching_observed_scopes'][0]['last_day'],
                         '2026-11-12')
        self.assertFalse(stock['original_quarantine_cleared'])

    def test_04_exact_target_grid_is_still_not_admitted(self):
        self.write('target.jsonl', rows('300119.SZ', '2026-11-25'))
        value = S.inspect(self.module)
        stock = next(x for x in value['nine_quarantine_local_evidence']
                     if x['quarantined_symbol'] == 'SZ300119')
        self.assertEqual(stock['local_source_status'],
                         'LOCAL_TARGET_DAY_EXACT_241_WITH_0930_NOT_ADMITTED')
        self.assertFalse(stock['provider_origin_authenticated'])
        self.assertFalse(stock['official_day_reconciled'])
        self.assertFalse(stock['original_quarantine_cleared'])

    def test_05_240_without_opening_is_review_not_admission(self):
        self.write('target.jsonl', rows('300119.SZ', '2026-11-25',
                                        MINUTE.GRID_240))
        value = S.inspect(self.module)
        stock = next(x for x in value['nine_quarantine_local_evidence']
                     if x['quarantined_symbol'] == 'SZ300119')
        self.assertEqual(stock['local_source_status'],
                         'LOCAL_TARGET_DAY_EXACT_240_WITHOUT_0930_REVIEW_REQUIRED_NOT_ADMITTED')

    def test_06_two_same_symbol_sources_are_never_arbitrarily_promoted(self):
        self.write('a.jsonl', rows('300119.SZ', '2026-11-24'))
        self.write('b.jsonl', rows('300119.SZ', '2026-11-25'))
        value = S.inspect(self.module)
        stock = next(x for x in value['nine_quarantine_local_evidence']
                     if x['quarantined_symbol'] == 'SZ300119')
        self.assertEqual(stock['matching_validated_local_probe_files'], 2)
        self.assertEqual(stock['local_source_status'],
                         'MULTIPLE_SAME_SYMBOL_LOCAL_SOURCES_REVIEW_REQUIRED')

    def test_07_bad_numerical_source_rejected_fail_closed(self):
        record = rows()[0]
        self.write('bad.jsonl', [dict(record, volume=-123.)])
        with self.assertRaises(MINUTE.NativeMinuteError):
            S.inspect(self.module)

    def test_08_probe_count_budget_is_not_increased(self):
        self.write('a.jsonl')
        self.write('b.jsonl')
        with mock.patch.object(S.GAP, 'MAX_PROBES', 1):
            with self.assertRaisesRegex(S.StageOnlyProbeError,
                                        'LOCAL_PROBE_INVENTORY_SAFETY_GATE_FAILED'):
                S.inspect(self.module)

    def test_09_fake_inventory_production_permission_refused(self):
        base = S.INVENTORY.inspect(self.probe, 'minute')
        base['market_files_written'] = True
        with mock.patch.object(S.INVENTORY, 'inspect', return_value=base):
            with self.assertRaisesRegex(S.StageOnlyProbeError,
                                        'LOCAL_PROBE_INVENTORY_SAFETY_GATE_FAILED'):
                S.inspect(self.module)

    def test_10_probes_added_between_snapshots_fail_closed(self):
        self.write('original.jsonl')
        original = S.INVENTORY.inspect
        times = [0]

        def changing(root, kind):
            times[0] += 1
            if times[0] == 2:
                self.write('new.jsonl', rows('000002.SZ'))
            return original(root, kind)

        with mock.patch.object(S.INVENTORY, 'inspect', side_effect=changing):
            with self.assertRaisesRegex(S.StageOnlyProbeError,
                                        'LOCAL_PROBE_INVENTORY_CHANGED_DURING_SCAN'):
                S.inspect(self.module)

    def test_11_no_original_receipt_audit_called_even_on_true_local_rows(self):
        self.write('target.jsonl', rows('300119.SZ', '2026-11-25'))
        with mock.patch.object(S.GAP, 'verify_original', side_effect=AssertionError(
                'MISSING ORIGINAL RECEIPT MUST NEVER BE SPOOFED')):
            value = S.inspect(self.module)
        self.assertFalse(value['original_run_receipt_authenticated'])
        self.assertFalse(value['original_run_stage_link_verified'])

    def test_12_untrusted_source_claim_from_probe_scope_is_refused(self):
        self.write()
        with mock.patch.object(S.GAP, '_probe_scope', return_value={
                'parsed_symbol': '300119.SZ',
                'provider_origin_authenticated': True,
                'official_day_reconciled': False,
                'purchased_units_calibrated': False}):
            with self.assertRaisesRegex(S.StageOnlyProbeError,
                                        'LOCAL_PROBE_SOURCE_AUTHORITY_INVALID'):
                S.inspect(self.module)

    def test_13_missing_explicit_root_is_blocked_not_implicitly_created(self):
        self.probe.rmdir()
        with self.assertRaisesRegex(S.StageOnlyProbeError,
                                    'EXPLICIT_PROBE_ROOT_INVALID'):
            S.inspect(self.module)
        self.assertFalse(self.probe.exists())

    def test_14_cli_error_never_reveals_absolute_path(self):
        buf = StringIO()
        with mock.patch.object(S, 'inspect', side_effect=RuntimeError(
                'C:/private/finance/nine.jsonl')):
            with contextlib.redirect_stdout(buf):
                rc = S.main(['--module-root', str(self.module)])
        self.assertEqual(rc, 3)
        self.assertIn('STAGE_ONLY_LOCAL_PROBE_REVIEW_REQUIRED: RuntimeError',
                      buf.getvalue())
        self.assertNotIn('C:/private', buf.getvalue())

    def test_15_no_download_no_disk_writes_and_no_original_run_bypass(self):
        source = inspect_module.getsource(S)
        for forbidden in ('download_history_data(', 'get_market_data_ex(',
                          'write_bytes(', 'write_table(', 'os.replace(',
                          'mkdir(', 'unlink(', 'rename(', 'GAP.verify_original(',
                          'AUDIT.audit('):
            self.assertNotIn(forbidden, source)
        self.assertEqual(S.PROBE_SUBDIR, 'qmt_1m_probe')
        self.assertEqual(S.DAY, '2026-11-25')
        self.assertEqual(S.GAP.RUN_SHA,
                         '72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837')


if __name__ == '__main__':
    unittest.main()
