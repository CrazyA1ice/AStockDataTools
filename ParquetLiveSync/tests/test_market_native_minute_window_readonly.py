"""Physical temp-file and multi-date census tests; no fake market admission."""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_native_minute_window_readonly as W
import market_native_minute_jsonl_readonly as M

CN=timezone(timedelta(hours=8))

def row(day, hm, sym='300119.SZ', **change):
    data={'datetime_cn':datetime.fromisoformat(day).replace(hour=hm[0],minute=hm[1],tzinfo=CN).isoformat(),
          'symbol':sym, 'open':10., 'high':11., 'low':9., 'close':10.5,
          'volume':100., 'amount':1010.}
    data.update(change)
    return data

def stock_day(day, labels=None, sym='300119.SZ'):
    if labels is None: labels=M.GRID
    return [row(day, t, sym) for t in sorted(labels)]

def write_fixture(root, days=None):
    data=(stock_day('2026-11-10') if days is None else days)
    p=Path(root)/'existing.jsonl'
    blob=b''.join((json.dumps(r,sort_keys=True,allow_nan=False)+'\n').encode('utf-8') for r in data)
    p.write_bytes(blob)
    return sha256(blob).hexdigest()

def call(root, digest, **change):
    args=dict(root=root,relative='existing.jsonl',expected_sha256=digest,
              symbol='SZ300119',start_day='2026-11-10',end_day='2026-11-12')
    args.update(change)
    return W.inspect(**args)


class WindowGridTests(unittest.TestCase):
    def test_one_241_day_and_two_calendar_gaps_are_not_trading_gaps(self):
        with tempfile.TemporaryDirectory() as t:
            digest=write_fixture(t)
            r=call(t,digest)
            self.assertEqual(r['rows_structurally_and_numerically_validated'],241)
            self.assertEqual([d['rows'] for d in r['days']],[241,0,0])
            self.assertEqual(r['days'][0]['grid_status'],'EXACT_241_WITH_0930')
            self.assertEqual(r['days'][1]['grid_status'],'NO_ROWS_CALENDAR_DAY_NOT_PROVED_TRADING')
            self.assertFalse(r['official_exchange_calendar_or_stock_universe_certified'])
            self.assertFalse(r['production_merge_authorized'])

    def test_240_opening_missing_is_distinct_review_status(self):
        with tempfile.TemporaryDirectory() as t:
            dig=write_fixture(t,stock_day('2026-11-10',M.GRID_240))
            r=call(t,dig)
            self.assertEqual(r['days'][0]['rows'],240)
            self.assertEqual(r['days'][0]['missing_native_labels_count'],1)
            self.assertEqual(r['days'][0]['missing_native_labels_examples'],['09:30'])
            self.assertEqual(r['days'][0]['grid_status'],'EXACT_240_WITHOUT_0930_REVIEW_REQUIRED')
            self.assertFalse(r['all_observed_days_exact_241'])

    def test_partial_239_row_file_becomes_review_only_not_corrupt(self):
        with tempfile.TemporaryDirectory() as t:
            dig=write_fixture(t,stock_day('2026-11-10',M.GRID_240-{(10,0)}))
            r=call(t,dig)
            self.assertEqual(r['days'][0]['grid_status'],'PARTIAL_NATIVE_GRID_REVIEW_REQUIRED')
            self.assertEqual(r['days'][0]['missing_native_labels_count'],2)
            self.assertFalse(r['production_quarantine_cleared'])

    def test_240_with_opening_but_missing_another_bar_is_partial(self):
        with tempfile.TemporaryDirectory() as t:
            dig=write_fixture(t,stock_day('2026-11-10',M.GRID-{(10,0)}))
            r=call(t,dig)
            self.assertEqual(r['days'][0]['rows'],240)
            self.assertTrue(r['days'][0]['opening_0930_present'])
            self.assertEqual(r['days'][0]['grid_status'],'PARTIAL_NATIVE_GRID_REVIEW_REQUIRED')

    def test_combined_multi_day_241_240_partial_and_gap_conserve_counts(self):
        with tempfile.TemporaryDirectory() as t:
            rows=stock_day('2026-11-10')+stock_day('2026-11-11',M.GRID_240)+stock_day('2026-11-12',M.GRID-{(9,30),(10,2)})
            dig=write_fixture(t,rows)
            r=call(t,dig)
            self.assertEqual([d['rows'] for d in r['days']],[241,240,239])
            self.assertEqual(r['rows_structurally_and_numerically_validated'],720)
            self.assertEqual(sum(r['grid_status_counts'].values()),3)
            self.assertEqual(r['days'][-1]['grid_status'],'PARTIAL_NATIVE_GRID_REVIEW_REQUIRED')

    def test_start_date_can_be_nontrading_calendar_day(self):
        with tempfile.TemporaryDirectory() as t:
            dig=write_fixture(t,stock_day('2026-11-12'))
            r=call(t,dig)
            self.assertEqual([d['rows'] for d in r['days']],[0,0,241])

    def test_first_date_partial_does_not_hide_later_duplicated_timestamp(self):
        with tempfile.TemporaryDirectory() as t:
            a=stock_day('2026-11-10',M.GRID_240)
            b=stock_day('2026-11-11')
            b.insert(2,dict(b[1]))
            dig=write_fixture(t,a+b)
            with self.assertRaisesRegex(M.NativeMinuteError,'DUPLICATE_TIMESTAMP'):
                call(t,dig)

    def test_first_date_partial_does_not_hide_later_nonfinite(self):
        with tempfile.TemporaryDirectory() as t:
            a=stock_day('2026-11-10',M.GRID_240)
            b=stock_day('2026-11-11')
            b[2]['close']=-100
            dig=write_fixture(t,a+b)
            with self.assertRaises(M.NativeMinuteError):call(t,dig)

    def test_reject_wrong_stock_even_when_241_present(self):
        with tempfile.TemporaryDirectory() as t:
            dig=write_fixture(t,stock_day('2026-11-10',sym='600000.SH'))
            with self.assertRaisesRegex(M.NativeMinuteError,'WRONG_SYMBOL'):call(t,dig)

    def test_reject_date_outside_declared_window(self):
        with tempfile.TemporaryDirectory() as t:
            dig=write_fixture(t,stock_day('2026-11-09'))
            with self.assertRaisesRegex(M.NativeMinuteError,'OUTSIDE_DECLARED_WINDOW'):call(t,dig)

    def test_reject_out_of_session_timestamp(self):
        with tempfile.TemporaryDirectory() as t:
            rows=stock_day('2026-11-10')
            rows[-1]['datetime_cn']='2026-11-10T15:01:00+08:00'
            dig=write_fixture(t,rows)
            with self.assertRaisesRegex(M.NativeMinuteError,'OUTSIDE_NATIVE_GRID'):call(t,dig)

    def test_reject_wrong_sha_and_modified_bytes(self):
        with tempfile.TemporaryDirectory() as t:
            dig=write_fixture(t)
            with self.assertRaisesRegex(W.WindowError,'SHA_MISMATCH'):call(t,'f'*64)
            (Path(t)/'existing.jsonl').write_bytes(b'garbled')
            with self.assertRaisesRegex(W.WindowError,'SHA_MISMATCH'):call(t,dig)

    def test_file_swap_during_stream_is_rejected_by_final_rehash(self):
        with tempfile.TemporaryDirectory() as t:
            dig=write_fixture(t)
            def malicious(p):
                yield from M._file_rows(p)
                p.write_bytes(p.read_bytes()+b' ')
            with self.assertRaisesRegex(W.WindowError,'CHANGED_DURING_AUDIT'):
                call(t,dig,row_reader=malicious)

    def test_path_traversal_and_extension_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            dig=write_fixture(t)
            for p in ('../existing.jsonl','/tmp/existing.jsonl','x.parquet'):
                with self.subTest(path=p),self.assertRaises(ValueError):
                    call(t,dig,relative=p)

    def test_symlink_source_file_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            dig=write_fixture(t)
            p=Path(t)/'alias.jsonl'
            try:p.symlink_to(Path(t)/'existing.jsonl')
            except (OSError,NotImplementedError):self.skipTest('symlink unavailable')
            with self.assertRaises(ValueError):call(t,dig,relative='alias.jsonl')

    def test_bad_request_date_or_window_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            dig=write_fixture(t)
            for change in [dict(start_day='2026-02-30'),dict(end_day='2026-11-09'),
                           dict(end_day='2027-11-12')]:
                with self.subTest(change=change),self.assertRaises(ValueError):
                    call(t,dig,**change)

    def test_bounded_file_budget_rejected_before_hash(self):
        with tempfile.TemporaryDirectory() as t:
            dig=write_fixture(t)
            with mock.patch.object(M,'MAX_BYTES',2):
                with mock.patch.object(W.P,'_hash_stable_file',side_effect=AssertionError('unbounded hash')):
                    with self.assertRaisesRegex(W.WindowError,'FILE_SIZE_LIMIT'):call(t,dig)

    def test_empty_file_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t)/'existing.jsonl').write_bytes(b'')
            with self.assertRaisesRegex(W.WindowError,'FILE_SIZE_LIMIT'):
                call(t,'a'*64)

    def test_jsonl_invalid_fields_never_downgraded_to_partial(self):
        with tempfile.TemporaryDirectory() as t:
            rows=stock_day('2026-11-10',M.GRID_240)
            rows[-1]['unrecognized_authorization']=True
            dig=write_fixture(t,rows)
            with self.assertRaisesRegex(M.NativeMinuteError,'ROW_SCHEMA_INVALID'):
                call(t,dig)

    def test_two_stock_days_out_of_order_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            dig=write_fixture(t,stock_day('2026-11-11')+stock_day('2026-11-10'))
            with self.assertRaisesRegex(M.NativeMinuteError,'UNSORTED'):call(t,dig)

    def test_raw_test_cannot_authenticate_provider_or_ledger(self):
        with tempfile.TemporaryDirectory() as t:
            dig=write_fixture(t)
            result=call(t,dig)
            for key in ('native_qmt_provider_origin_authenticated','purchased_minute_units_or_offset_calibrated',
                        'six_field_official_day_reconciliation_passed','eight_period_aggregation_validated',
                        'production_quarantine_cleared','market_candidate_validated',
                        'production_merge_authorized','market_files_written','qmt_cache_modified'):
                self.assertFalse(result[key])
            self.assertEqual(result['qmt_history_download_calls'],0)

    def test_no_market_writer_or_qmt_network_api(self):
        import inspect
        source=inspect.getsource(W)
        for text in ('download_history_data(', 'get_market_data_ex(',
                     'write_bytes(', 'write_table(', 'mkdir(', 'os.replace('):
            self.assertNotIn(text,source)

    def test_cli_error_message_does_not_leak_private_root(self):
        out=StringIO()
        with contextlib.redirect_stdout(out):
            result=W.main(['--evidence-root','/hidden/private-root','--file-relative','probe.jsonl',
                           '--expected-file-sha256','a'*64,'--symbol','300119.SZ',
                           '--start-day','2026-11-10','--end-day','2026-11-12'])
        self.assertEqual(result,3)
        self.assertNotIn('/hidden/',out.getvalue())


if __name__ == '__main__':unittest.main()
