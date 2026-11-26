"""Real temp-byte and synthetic row tests of pre-admission raw comparison."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import contextlib
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import market_minute_day_raw_pair_readonly as PAIR
import market_native_minute_jsonl_readonly as M
import market_official_day_content_readonly as DAY


CN=timezone(timedelta(hours=8))

def minute_rows(day='2026-11-25', sym='300119.SZ', *, full=True, scale=1):
    return [dict(datetime_cn=datetime.fromisoformat(day).replace(hour=h,minute=m,tzinfo=CN).isoformat(),
                 symbol=sym, open=10.*scale, high=11.*scale, low=9.*scale,
                 close=10.5*scale,volume=100.*scale,amount=1010.*scale)
            for h,m in sorted(M.GRID if full else M.GRID_240)]


def day_row(day='2026-11-25',sym='SZ300119',**fields):
    result=dict(ts=int(datetime.fromisoformat(day).replace(tzinfo=CN).timestamp()*1000),
                symbol=sym,open=10.,high=11.,low=9.,close=10.5,
                volume=24100.,amount=243410.)
    result.update(fields)
    return result


def fixture(root, *, minute=None, day_bytes=b'declared DAY Parquet fixture bytes'):
    path=Path(root);(path/'minute.jsonl').write_bytes(b''.join(
        (json.dumps(x,sort_keys=True)+'\n').encode('utf-8') for x in (minute if minute is not None else minute_rows())))
    (path/'day.parquet').write_bytes(day_bytes)
    return (sha256((path/'minute.jsonl').read_bytes()).hexdigest(),
            sha256((path/'day.parquet').read_bytes()).hexdigest())


def args(root,msha,dsha,**change):
    a=dict(minute_root=root,minute_relative='minute.jsonl',minute_sha256=msha,
           day_root=root,day_relative='day.parquet',day_sha256=dsha,
           symbol='SZ300119',target_day='2026-11-25',
           start_day='2026-11-25',end_day='2026-11-25',
           day_row_reader=lambda path: [day_row()])
    a.update(change)
    return a


class RawPairTests(unittest.TestCase):
    def test_valid_241_local_pair_raw_differences_only(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root)
            r=PAIR.inspect(**args(root,msha,dsha))
            self.assertEqual(r['minute_count'],241)
            self.assertEqual(r['field_raw_differences_not_calibrated']['volume']['raw_signed_difference'],0)
            self.assertEqual(r['field_raw_differences_not_calibrated']['amount']['raw_signed_difference'],0)
            self.assertFalse(r['six_field_comparison_quality_passed'])
            self.assertFalse(r['qmt_native_origin_authenticated'])
            self.assertFalse(r['production_merge_authorized'])
            self.assertFalse(r['market_files_written'])
            self.assertEqual(r['minute_local_bytes_sha256'],msha)

    def test_persistent_raw_unit_difference_does_not_auto_pass(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root,minute=minute_rows(scale=2))
            r=PAIR.inspect(**args(root,msha,dsha))
            self.assertGreater(r['field_raw_differences_not_calibrated']['amount']['raw_signed_difference'],0)
            self.assertFalse(r['minute_paid_scale_or_timestamp_calibrated'])
            self.assertFalse(r['six_field_comparison_quality_passed'])

    def test_240_minus_opening_bucket_cannot_be_certified(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root,minute=minute_rows(full=False))
            r=PAIR.inspect(**args(root,msha,dsha))
            self.assertEqual(r['minute_count'],240)
            self.assertEqual(r['minute_grid'],'EXACT_240_WITHOUT_0930_REVIEW_REQUIRED')
            self.assertFalse(r['producer_quarantine_closed'])

    def test_multi_date_file_selects_actual_target(self):
        with TemporaryDirectory() as root:
            data=minute_rows('2026-11-24')+minute_rows('2026-11-25')
            msha,dsha=fixture(root,minute=data)
            r=PAIR.inspect(**args(root,msha,dsha,start_day='2026-11-24'))
            self.assertEqual(r['target_day'],'2026-11-25')
            self.assertEqual(r['minute_count'],241)

    def test_other_year_and_shanghai_symbol(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root,minute=minute_rows('2019-12-31','600000.SH'))
            r=PAIR.inspect(**args(root,msha,dsha,symbol='600000.SH',target_day='2019-12-31',
                                       start_day='2019-12-31',end_day='2019-12-31',
                                       day_row_reader=lambda path:[day_row('2019-12-31','SH600000')]))
            self.assertEqual(r['target_symbol'],'600000.SH')

    def test_wrong_source_sha_fails_closed(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root)
            with self.assertRaises(ValueError):
                PAIR.inspect(**args(root,'f'*64,dsha))
            with self.assertRaises(ValueError):
                PAIR.inspect(**args(root,msha,'f'*64))

    def test_wrong_declared_symbol_does_not_morph(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root)
            with self.assertRaises(ValueError):
                PAIR.inspect(**args(root,msha,dsha,symbol='600000.SH'))

    def test_wrong_declared_day_parquet_scope_fails(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root)
            with self.assertRaises(ValueError):
                PAIR.inspect(**args(root,msha,dsha,
                    day_row_reader=lambda path: [day_row(sym='SH600000')]))

    def test_reject_minute_data_with_missing_slot(self):
        with TemporaryDirectory() as root:
            data=minute_rows()[:-1]
            msha,dsha=fixture(root,minute=data)
            with self.assertRaises(ValueError):
                PAIR.inspect(**args(root,msha,dsha))

    def test_reject_day_and_minute_root_path_traversal(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root)
            with self.assertRaises(ValueError):
                PAIR.inspect(**args(root,msha,dsha,minute_relative='../minute.jsonl'))
            with self.assertRaises(ValueError):
                PAIR.inspect(**args(root,msha,dsha,day_relative='../day.parquet'))

    def test_file_tamper_during_joint_read_is_detected(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root)
            def attack(path):
                (Path(root)/'minute.jsonl').write_bytes((Path(root)/'minute.jsonl').read_bytes()+b' ')
                return [day_row()]
            with self.assertRaises(ValueError):
                PAIR.inspect(**args(root,msha,dsha,day_row_reader=attack))

    def test_file_path_symlink_rejected(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root)
            p=Path(root)/'link.parquet'
            try:p.symlink_to(Path(root)/'day.parquet')
            except (OSError,NotImplementedError):self.skipTest('symlinks unavailable')
            with self.assertRaises(ValueError):
                PAIR.inspect(**args(root,msha,dsha,day_relative='link.parquet'))

    def test_pair_scope_digest_reproducible(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root)
            first=PAIR.inspect(**args(root,msha,dsha))
            again=PAIR.inspect(**args(root,msha,dsha))
            self.assertEqual(first['source_pair_diagnostic_sha256'],again['source_pair_diagnostic_sha256'])
            self.assertEqual(first,again)

    def test_corrupt_minute_report_scope_is_not_authority(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root)
            orig=PAIR.MINUTE.inspect
            def forged(*a,**k):
                r=orig(*a,**k);r['production_merge_authorized']=True;return r
            with mock.patch.object(PAIR.MINUTE,'inspect',side_effect=forged):
                with self.assertRaisesRegex(PAIR.PairError,'MINUTE_SOURCE_REPORT'):
                    PAIR.inspect(**args(root,msha,dsha))

    def test_corrupt_day_report_scope_is_not_authority(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root)
            orig=PAIR.DAY.inspect_explicit
            def forged(*a,**k):
                r=orig(*a,**k);r['source_independence_authenticated']=True;return r
            with mock.patch.object(PAIR.DAY,'inspect_explicit',side_effect=forged):
                with self.assertRaisesRegex(PAIR.PairError,'DAY_SOURCE_REPORT'):
                    PAIR.inspect(**args(root,msha,dsha))

    def test_mismatched_classification_and_count_fails(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root)
            orig=PAIR.MINUTE.inspect
            def forged(*a,**k):
                r=orig(*a,**k);r['target_minute_rows']=240;return r
            with mock.patch.object(PAIR.MINUTE,'inspect',side_effect=forged):
                with self.assertRaisesRegex(PAIR.PairError,'MINUTE_GRID_COUNT'):
                    PAIR.inspect(**args(root,msha,dsha))

    def test_boolean_numeric_fields_rejected(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root)
            orig=PAIR.DAY.inspect_explicit
            def forged(*a,**k):
                r=orig(*a,**k);r['target_ohlcva']['volume']=True;return r
            with mock.patch.object(PAIR.DAY,'inspect_explicit',side_effect=forged):
                with self.assertRaisesRegex(PAIR.PairError,'DAY_NON_NUMERIC'):
                    PAIR.inspect(**args(root,msha,dsha))

    def test_duplicate_or_unknown_ohlcva_fields_rejected(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root)
            orig=PAIR.MINUTE.inspect
            def forged(*a,**k):
                r=orig(*a,**k);r['raw_uncalibrated_target_ohlcva']['proof_of_origin']=1;return r
            with mock.patch.object(PAIR.MINUTE,'inspect',side_effect=forged):
                with self.assertRaisesRegex(PAIR.PairError,'MINUTE_FIELDS_INVALID'):
                    PAIR.inspect(**args(root,msha,dsha))

    def test_proof_sha_is_not_a_provider_signature(self):
        with TemporaryDirectory() as root:
            msha,dsha=fixture(root)
            r=PAIR.inspect(**args(root,msha,dsha))
            self.assertFalse(r['provider_independence_or_identity_authenticated'])
            self.assertFalse(r['official_stock_day_universe_certified'])
            self.assertFalse(r['backup_materialized'])
            self.assertFalse(r['physical_source_lock_held'])

    def test_error_output_does_not_print_private_path(self):
        stream=StringIO()
        with contextlib.redirect_stdout(stream):
            rc=PAIR.main(['--minute-evidence-root','/secret/private-QMT',
                          '--minute-file-relative','private.jsonl',
                          '--expected-minute-sha256','a'*64,
                          '--day-evidence-root','/secret/official',
                          '--day-file-relative','private.parquet',
                          '--expected-day-sha256','b'*64,'--symbol','300119.SZ',
                          '--target-day','2026-11-25','--minute-start-day','2026-11-25',
                          '--minute-end-day','2026-11-25'])
        self.assertEqual(rc,3)
        self.assertNotIn('/secret',stream.getvalue())

    def test_no_market_writer_or_qmt_query_calls(self):
        import inspect
        src=inspect.getsource(PAIR)
        for forbidden in ('download_history_data(', 'get_market_data_ex(',
                          'write_bytes(', 'write_table(', 'os.replace(',
                          'mkdir(', 'safe_save(', 'open("wb"'):
            self.assertNotIn(forbidden,src)


if __name__ == '__main__':unittest.main()
