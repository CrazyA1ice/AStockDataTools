"""Read-only probe-style local minute evidence, never QMT origin certification."""
from __future__ import annotations
from datetime import datetime, date, timedelta, timezone
from hashlib import sha256
import contextlib
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_native_minute_jsonl_readonly as M


CN = timezone(timedelta(hours=8))


def row(day='2026-11-25', hm=(9, 30), symbol='300119.SZ', **change):
    moment = datetime.fromisoformat(day).replace(hour=hm[0], minute=hm[1], tzinfo=CN)
    data = {'datetime_cn': moment.isoformat(), 'symbol': symbol,
            'open': 10., 'high': 11., 'low': 9., 'close': 10.5,
            'volume': 100., 'amount': 1010.}
    data.update(change)
    return data


def series(day='2026-11-25', omit_open=False, symbol='300119.SZ'):
    labels = M.GRID_240 if omit_open else M.GRID
    return [row(day, hm, symbol) for hm in sorted(labels)]


def params(day='2026-11-25'):
    return dict(target_symbol='300119.SZ', target_day=day,
                start_day=day, end_day=day)


def write_file(root, rows):
    path = Path(root) / 'probe.jsonl'
    body = b''.join((json.dumps(r, sort_keys=True, ensure_ascii=False,
                                allow_nan=False) + '\n').encode('utf-8') for r in rows)
    path.write_bytes(body)
    return 'probe.jsonl', sha256(body).hexdigest()


class NativeMinuteContentTests(unittest.TestCase):
    def test_241_grid_is_only_local_data_not_provider_authentication(self):
        r = M.check_rows(series(), **params())
        self.assertEqual(r['target_minute_rows'], 241)
        self.assertTrue(r['opening_0930_observed'])
        self.assertTrue(r['exact_241_native_labels_observed'])
        self.assertFalse(r['provider_origin_authenticated'])
        self.assertFalse(r['production_merge_authorized'])
        self.assertFalse(r['minute_adjustment_and_paid_units_calibrated'])
        self.assertFalse(r['six_field_official_day_reconciliation_passed'])
        self.assertEqual(r['raw_uncalibrated_target_ohlcva']['volume'], 24100.)

    def test_240_grid_omits_opening_and_remains_review_only(self):
        r = M.check_rows(series(omit_open=True), **params())
        self.assertEqual(r['target_minute_rows'], 240)
        self.assertFalse(r['opening_0930_observed'])
        self.assertTrue(r['exact_240_without_opening_labels_observed'])
        self.assertIn('REVIEW_REQUIRED', r['target_native_grid_classification'])
        self.assertFalse(r['production_quarantine_cleared'])

    def test_multi_day_export_selected_day_only_grid_certified(self):
        records = series('2026-11-24') + series('2026-11-25')
        r = M.check_rows(records, target_symbol='SZ300119',
                         target_day='2026-11-25', start_day='2026-11-24', end_day='2026-11-25')
        self.assertEqual(r['file_records_structurally_checked'], 482)
        self.assertEqual(r['other_day_records_not_grid_certified'], 241)
        self.assertEqual(r['observed_file_days'], 2)

    def test_missing_slot_in_native_241_rejected(self):
        bad = [r for r in series() if '10:15:00' not in r['datetime_cn']]
        with self.assertRaisesRegex(M.NativeMinuteError, 'TARGET_MINUTE_GRID'):
            M.check_rows(bad, **params())

    def test_extra_invalid_session_rejected(self):
        bad = series() + [row(hm=(12, 0))]
        with self.assertRaisesRegex(M.NativeMinuteError, 'OUTSIDE_NATIVE_GRID'):
            M.check_rows(bad, **params())

    def test_duplicate_timestamp_rejected(self):
        bad = series(); bad.insert(2, dict(bad[1]))
        with self.assertRaisesRegex(M.NativeMinuteError, 'DUPLICATE_TIMESTAMP'):
            M.check_rows(bad, **params())

    def test_unsorted_minutes_rejected(self):
        bad = series(); bad[2], bad[3] = bad[3], bad[2]
        with self.assertRaisesRegex(M.NativeMinuteError, 'UNSORTED'):
            M.check_rows(bad, **params())

    def test_wrong_symbol_rejected(self):
        bad = series(); bad[0] = {**bad[0], 'symbol':'600000.SH'}
        with self.assertRaisesRegex(M.NativeMinuteError, 'WRONG_SYMBOL'):
            M.check_rows(bad, **params())

    def test_time_window_outside_day_rejected(self):
        bad = series(); bad[0] = row('2026-11-24', (9,30))
        with self.assertRaisesRegex(M.NativeMinuteError, 'OUTSIDE_DECLARED_WINDOW'):
            M.check_rows(bad, **params())

    def test_negative_ohlc_and_ohlc_envelope_rejected(self):
        for changes in ({'open':-1}, {'low':12}, {'high':8}, {'close':12}):
            with self.subTest(changes=changes):
                bad=series(); bad[7]={**bad[7], **changes}
                with self.assertRaises(M.NativeMinuteError):
                    M.check_rows(bad, **params())

    def test_nonfinite_and_bools_rejected(self):
        for field,val in [('open',float('nan')),('close',float('inf')),
                          ('volume',True),('amount',-2),('open','10.0')]:
            with self.subTest(field=field):
                bad=series(); bad[0]={**bad[0],field:val}
                with self.assertRaises(M.NativeMinuteError):
                    M.check_rows(bad, **params())

    def test_volume_amount_mismatch_rejected(self):
        bad=series(); bad[0]['amount']=0
        with self.assertRaisesRegex(M.NativeMinuteError, 'PAIR_INVALID'):
            M.check_rows(bad, **params())

    def test_zero_zero_trade_bar_allowed_without_market_admission(self):
        bad=series(); bad[0]['amount']=0;bad[0]['volume']=0
        r=M.check_rows(bad, **params())
        self.assertFalse(r['production_merge_authorized'])

    def test_empty_target_day_rejected_even_if_older_file_is_valid(self):
        with self.assertRaisesRegex(M.NativeMinuteError, 'TARGET_MINUTE_GRID'):
            M.check_rows(series('2026-11-24'), target_symbol='300119.SZ',
                         target_day='2026-11-25', start_day='2026-11-24', end_day='2026-11-25')

    def test_cross_year_and_other_shanghai_stock(self):
        r=M.check_rows(series('2019-12-31',symbol='600000.SH'),
                       target_symbol='SH600000',target_day='2019-12-31',
                       start_day='2019-12-31',end_day='2019-12-31')
        self.assertEqual(r['declared_symbol'],'600000.SH')

    def test_request_date_and_window_invalid(self):
        for change in [dict(target_day='2026-02-30'),
                       dict(start_day='2026-11-26'),
                       dict(end_day='2027-12-31')]:
            with self.subTest(change=change):
                with self.assertRaises(M.NativeMinuteError):
                    M.check_rows(series(), **{**params(),**change})

    def test_timestamp_requires_exact_china_offset_and_minute(self):
        for t in ('2026-11-25T09:30:00', '2026-11-25T01:30:00+00:00',
                  '2026-11-25T09:30:01+08:00', '2026-11-25T09:30:00.001+08:00'):
            bad=series();bad[0]['datetime_cn']=t
            with self.subTest(stamp=t),self.assertRaises(M.NativeMinuteError):
                M.check_rows(bad, **params())

    def test_json_duplicate_fields_and_nonfinite_constants_fail(self):
        with self.assertRaisesRegex(M.NativeMinuteError, 'DUPLICATE_KEY'):
            M.parse_line(b'{"symbol":"a","symbol":"b"}')
        with self.assertRaisesRegex(M.NativeMinuteError, 'NONFINITE_CONSTANT'):
            M.parse_line(b'{"volume":NaN}')

    def test_missing_or_unexpected_fields_fail(self):
        for change in (dict(mystery=1), {'amount':None}):
            bad=series();bad[0].update(change)
            with self.assertRaises(M.NativeMinuteError):
                M.check_rows(bad, **params())

    def test_empty_or_oversized_line_fail(self):
        with TemporaryDirectory() as td:
            p=Path(td)/'x'
            p.write_bytes(b'\n')
            with self.assertRaisesRegex(M.NativeMinuteError, 'EMPTY_LINE'):
                list(M._file_rows(p))
            p.write_bytes(b' '*(M.MAX_LINE_BYTES+1))
            with self.assertRaisesRegex(M.NativeMinuteError, 'LINE_LIMIT'):
                list(M._file_rows(p))

    def test_row_budget_fail_closed(self):
        class Unbounded:
            def __iter__(self):
                for i in range(M.MAX_ROWS+1): yield row('2026-11-25', (9,30))
        with self.assertRaises(M.NativeMinuteError):
            M.check_rows(Unbounded(), **params())

    def test_sha_pinned_real_temp_jsonl_end_to_end_no_write(self):
        with TemporaryDirectory() as td:
            name, digest=write_file(td,series())
            path=Path(td)/name
            before=(path.read_bytes(),path.stat().st_mtime_ns)
            r=M.inspect(td,name,digest,'SZ300119','2026-11-25',
                        '2026-11-25','2026-11-25')
            self.assertEqual(r['physical_local_source_file_sha256'],digest)
            self.assertTrue(r['source_file_bytes_verified'])
            self.assertFalse(r['provider_origin_authenticated'])
            self.assertEqual(before,(path.read_bytes(),path.stat().st_mtime_ns))

    def test_sha_mismatch_rejected(self):
        with TemporaryDirectory() as td:
            name,digest=write_file(td,series())
            with self.assertRaisesRegex(M.NativeMinuteError, 'SHA_CHANGED'):
                M.inspect(td,name,'f'*64,'SZ300119','2026-11-25',
                          '2026-11-25','2026-11-25')

    def test_untrusted_path_and_symlink_rejected(self):
        with TemporaryDirectory() as td:
            name,digest=write_file(td,series())
            for bad in ('../probe.jsonl','/tmp/probe.jsonl','probe.txt'):
                with self.subTest(path=bad), self.assertRaises(ValueError):
                    M.inspect(td,bad,digest,'SZ300119','2026-11-25',
                              '2026-11-25','2026-11-25')
            link=Path(td)/'linked.jsonl'
            try: link.symlink_to(Path(td)/name)
            except (OSError, NotImplementedError): self.skipTest('symlinks unavailable')
            with self.assertRaises(ValueError):
                M.inspect(td,'linked.jsonl',digest,'SZ300119','2026-11-25',
                          '2026-11-25','2026-11-25')

    def test_changed_file_during_read_fails(self):
        with TemporaryDirectory() as td:
            name,digest=write_file(td,series())
            def malicious_reader(p):
                yield from M._file_rows(p)
                p.write_bytes(p.read_bytes()+b' ')
            with self.assertRaisesRegex(M.NativeMinuteError, 'CHANGED_DURING'):
                M.inspect(td,name,digest,'SZ300119','2026-11-25',
                          '2026-11-25','2026-11-25',row_reader=malicious_reader)

    def test_cli_error_does_not_print_private_path(self):
        out=StringIO()
        with contextlib.redirect_stdout(out):
            rc=M.main(['--evidence-root','/private/secret','--file-relative','secret.jsonl',
                       '--expected-file-sha256','f'*64,'--symbol','300119.SZ',
                       '--target-day','2026-11-25','--start-day','2026-11-25',
                       '--end-day','2026-11-25'])
        self.assertEqual(rc,3)
        self.assertNotIn('/private/secret',out.getvalue())

    def test_no_writer_or_qmt_network_api_in_new_module(self):
        import inspect
        source=inspect.getsource(M)
        for forbidden in ('download_history_data(', 'get_market_data_ex(',
                          'write_bytes(', 'write_table(', 'os.replace(',
                          'safe_save(', 'mkdir(', 'open("wb"'):
            self.assertNotIn(forbidden,source)


    def test_grid_matches_existing_qmt_pipeline_clock_contract_when_available(self):
        # The production pipeline requires Arrow; isolate the source-free unit
        # tests when Arrow is unavailable, but check the real contract on Windows.
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            self.skipTest('production Arrow minute pipeline unavailable')
        import qmt_1m_pipeline as P
        self.assertEqual(M.GRID, P.GRID)
        self.assertEqual(len(M.GRID), 241)
        self.assertEqual(M.GRID_240, P.GRID - {(9, 30)})


    def test_physical_file_oversize_rejected_before_hash(self):
        with TemporaryDirectory() as td:
            p=Path(td)/'huge.jsonl'
            with p.open('wb') as f:
                f.truncate(M.MAX_BYTES+1)
            with mock.patch.object(M.PROOF, '_hash_stable_file', side_effect=AssertionError('hashed oversized data')):
                with self.assertRaisesRegex(M.NativeMinuteError, 'BYTE_BUDGET_EXCEEDED'):
                    M.inspect(td,'huge.jsonl','a'*64,'300119.SZ',
                              '2026-11-25','2026-11-25','2026-11-25')

    def test_file_hash_uppercase_input_equivalent(self):
        with TemporaryDirectory() as td:
            name,digest=write_file(td,series())
            result=M.inspect(td,name,digest.upper(),'300119.SZ','2026-11-25',
                             '2026-11-25','2026-11-25')
            self.assertEqual(result['physical_local_source_file_sha256'],digest)


if __name__=='__main__': unittest.main()
