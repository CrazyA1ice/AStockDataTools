"""Pure and synthetic-file contract tests; real Arrow exercised on Windows."""
from __future__ import annotations
import contextlib
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import market_official_day_content_readonly as D


def record(day='2025-08-13', symbol='SZ300888', **overrides):
    tm = datetime.fromisoformat(day).replace(tzinfo=timezone(timedelta(hours=8)))
    row = {'ts': int(tm.timestamp() * 1000), 'symbol': symbol,
           'open': 10., 'high': 11., 'low': 9., 'close': 10.5,
           'volume': 100., 'amount': 1010.}
    row.update(overrides)
    return row


class DayContentTests(unittest.TestCase):
    def test_legal_day_and_target(self):
        r = D.validate_day_rows([record(), record(symbol='SH600000')],
                                '2025-08-13', 'SZ300888')
        self.assertEqual(r['normalized_exchange_symbols_validated'], 2)
        self.assertEqual(r['target_ohlcva']['open'], 10.)
        self.assertFalse(r['complete_official_exchange_universe_certified'])
        self.assertFalse(r['market_admission_authorized'])

    def test_suffix_spelling_normalized(self):
        r=D.validate_day_rows([record(symbol='300888.SZ')], '2025-08-13','SZ300888')
        self.assertTrue(r['target_present_and_content_consistent'])

    def test_eight_different_dates_and_symbols_not_hardcoded(self):
        for day,sym in [('2011-01-04','SH600000'),('2019-06-12','SZ000001'),
                        ('2026-11-26','BJ920021')]:
            with self.subTest(day=day):
                r=D.validate_day_rows([record(day,sym)],day,sym)
                self.assertEqual(r['target_symbol'],sym)

    def test_missing_target_fails(self):
        with self.assertRaisesRegex(D.DayContentError,'TARGET_EQUITY_NOT_IN_DAY_EXPORT'):
            D.validate_day_rows([record(symbol='SH600000')], '2025-08-13', 'SZ300888')

    def test_normalized_duplicate_fails(self):
        rows=[record(), record(symbol='300888.SZ')]
        with self.assertRaisesRegex(D.DayContentError,'DUPLICATE_NORMALIZED'):
            D.validate_day_rows(rows,'2025-08-13','SZ300888')

    def test_wrong_date_fails(self):
        with self.assertRaisesRegex(D.DayContentError,'MIXED_OR_WRONG_DATES'):
            D.validate_day_rows([record(day='2025-08-14')], '2025-08-13','SZ300888')

    def test_illegal_calendar_date_fails(self):
        with self.assertRaisesRegex(D.DayContentError,'INVALID_TRADING_DAY'):
            D.validate_day_rows([record()], '2026-02-30','SZ300888')

    def test_bad_ohlc_envelope_fails(self):
        for values in ({'high':9.}, {'low':12.}, {'open':11.5}):
            with self.subTest(values=values):
                with self.assertRaisesRegex(D.DayContentError,'DAY_OHLC_ENVELOPE'):
                    D.validate_day_rows([record(**values)],'2025-08-13','SZ300888')

    def test_negative_or_nonfinite_prices_fail(self):
        for row in (record(open=-1.),record(low=float('nan')),
                    record(amount=float('inf'))):
            with self.assertRaises(D.DayContentError):
                D.validate_day_rows([row],'2025-08-13','SZ300888')

    def test_volume_amount_pair_fails(self):
        with self.assertRaisesRegex(D.DayContentError,'DAY_VOLUME_AMOUNT_PAIR'):
            D.validate_day_rows([record(amount=0)],'2025-08-13','SZ300888')

    def test_target_zero_trading_not_accepted_as_active(self):
        with self.assertRaisesRegex(D.DayContentError,'TARGET_DAY_NOT_ACTIVE'):
            D.validate_day_rows([record(volume=0,amount=0)],'2025-08-13','SZ300888')

    def test_non_equity_index_is_counted_but_not_used_as_universe(self):
        result=D.validate_day_rows([record(),record(symbol='SH000300')],
                                   '2025-08-13','SZ300888')
        self.assertEqual(result['normalized_exchange_symbols_validated'],2)
        self.assertFalse(result['complete_official_exchange_universe_certified'])
        result=D.validate_day_rows([record(),record(symbol='IDX000300')],
                                   '2025-08-13','SZ300888')
        self.assertEqual(result['unrecognized_symbol_rows_ignored'],1)

    def test_noninteger_timestamp_fails(self):
        with self.assertRaisesRegex(D.DayContentError,'DAY_TIMESTAMP_INVALID'):
            D.validate_day_rows([record(ts=1.5)], '2025-08-13', 'SZ300888')

    def test_oversized_iterator_fails_closed(self):
        original=D.MAX_ROWS
        try:
            D.MAX_ROWS=2
            with self.assertRaisesRegex(D.DayContentError,'ROW_LIMIT'):
                D.validate_day_rows([record(),record(symbol='SH600000'),record(symbol='SZ000001')],
                                    '2025-08-13','SZ300888')
        finally:
            D.MAX_ROWS=original

    def test_duplicate_or_missing_field_fails(self):
        row=record();del row['low']
        with self.assertRaisesRegex(D.DayContentError,'ROW_FIELDS_MISSING'):
            D.validate_day_rows([row],'2025-08-13','SZ300888')

    def test_manifest_proof_binding_with_injected_parquet_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'QMT').mkdir();(root/'DAY').mkdir()
            native=root/'QMT'/'raw.dat';native.write_bytes(b'fictional raw 1m')
            official=root/'DAY'/'day.parquet';official.write_bytes(b'fictional-day-bytes')
            manifest={'format':'astock_source_byte_evidence_v1',
                      'scope':{'trading_day':'2025-08-13','symbol':'SZ300888','period':'day'},
                      'artifacts':[
                        {'role':'native_minute','source_id':'declared-qmt',
                         'relative_path':'QMT/raw.dat','expected_sha256':sha256(native.read_bytes()).hexdigest()},
                        {'role':'official_day','source_id':'declared-official',
                         'relative_path':'DAY/day.parquet','expected_sha256':sha256(official.read_bytes()).hexdigest()}]}
            mpath=root/'manifest.json';mpath.write_text(json.dumps(manifest))
            def verify(_,rel):
                b=mpath.read_bytes()
                pairs=manifest['artifacts']
                for i in pairs:
                    p=root/i['relative_path']
                    if sha256(p.read_bytes()).hexdigest()!=i['expected_sha256']:
                        raise ValueError('ARTIFACT_BYTES_SHA_MISMATCH')
                return {'manifest_bytes_sha256':sha256(b).hexdigest(),
                        'artifacts':[{'role':i['role'],'bytes_sha256':i['expected_sha256']}
                                     for i in pairs]}
            p=types.SimpleNamespace(verify=verify,_secure_relative=lambda rt,re: rt/re,
                                    _pairs=lambda x:dict(x))
            with mock.patch.dict(sys.modules,{'market_quality_source_proofs':p}):
                result=D.inspect(root,'manifest.json',row_reader=lambda _:iter([record()]))
                self.assertEqual(result['bound_official_day_file_bytes_sha256'],
                                 sha256(official.read_bytes()).hexdigest())
                self.assertFalse(result['official_provider_identity_authenticated'])
                official.write_bytes(b'changed-after-proof')
                with self.assertRaisesRegex(ValueError,'ARTIFACT_BYTES_SHA_MISMATCH'):
                    D.inspect(root,'manifest.json',row_reader=lambda _:iter([record()]))

    def test_non_day_period_refused_before_parsing(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'manifest.json').write_text(json.dumps({'scope':{
                'period':'1min','trading_day':'2025-08-13','symbol':'SZ300888'},
                'artifacts':[{'role':'official_day','relative_path':'ref.parquet'}]}))
            p=types.SimpleNamespace(verify=lambda *a:{'manifest_bytes_sha256':'a'*64,'artifacts':[]},
                                    _secure_relative=lambda rt,re: rt/re,_pairs=lambda x:dict(x))
            with mock.patch.dict(sys.modules,{'market_quality_source_proofs':p}):
                with self.assertRaisesRegex(D.DayContentError,'ONLY_DAY_PARQUET'):
                    D.inspect(root,'manifest.json',row_reader=lambda _:iter([record()]))

    def test_cli_catches_missing_evidence_without_path_leak(self):
        b=StringIO()
        with contextlib.redirect_stdout(b):
            rc=D.main(['--evidence-root','/secret/private/path','--manifest-relative','missing.json'])
        self.assertEqual(rc,3)
        self.assertNotIn('/secret/private/path',b.getvalue())


if __name__=='__main__':unittest.main()

class ExplicitDayFileTests(unittest.TestCase):
    def test_official_day_only_succeeds_without_native_minute_file(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);d=root/'official.parquet';d.write_bytes(b'fictional-day')
            expected=sha256(d.read_bytes()).hexdigest()
            p=types.SimpleNamespace(HEX64=__import__('re').compile(r'[0-9a-fA-F]{64}'),
                                    _secure_relative=lambda root,rel:root/rel,
                                    _hash_stable_file=lambda f:(sha256(f.read_bytes()).hexdigest(),f.stat().st_size))
            with mock.patch.dict(sys.modules, {'market_quality_source_proofs':p}):
                out=D.inspect_explicit(root,'official.parquet',expected,'2025-08-13',
                                       'SZ300888',row_reader=lambda _:iter([record()]))
            self.assertIsNone(out['bound_source_manifest_bytes_sha256'])
            self.assertEqual(out['bound_official_day_file_bytes_sha256'],expected)
            self.assertFalse(out['official_provider_identity_authenticated'])
            self.assertEqual(len(list(root.iterdir())),1)

    def test_unexpected_day_sha_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);d=root/'official.parquet';d.write_bytes(b'fictional-day')
            p=types.SimpleNamespace(HEX64=__import__('re').compile(r'[0-9a-fA-F]{64}'),
                                    _secure_relative=lambda root,rel:root/rel,
                                    _hash_stable_file=lambda f:(sha256(f.read_bytes()).hexdigest(),f.stat().st_size))
            with mock.patch.dict(sys.modules, {'market_quality_source_proofs':p}):
                read=mock.Mock(return_value=iter([record()]))
                with self.assertRaisesRegex(D.DayContentError,'DAY_FILE_SHA_CHANGED'):
                    D.inspect_explicit(root,'official.parquet','f'*64,
                                       '2025-08-13','SZ300888',row_reader=read)
                read.assert_not_called()

    def test_cli_requires_just_one_proof_mode(self):
        b=StringIO()
        with contextlib.redirect_stdout(b):
            rc=D.main(['--evidence-root','/missing','--manifest-relative','x',
                       '--day-file-relative','y.parquet'])
        self.assertEqual(rc,3)
        self.assertIn('REVIEW_REQUIRED',b.getvalue())

    def test_source_mutation_during_read_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);d=root/'official.parquet';d.write_bytes(b'fictional-day')
            expected=sha256(d.read_bytes()).hexdigest()
            p=types.SimpleNamespace(HEX64=__import__('re').compile(r'[0-9a-fA-F]{64}'),
                                    _secure_relative=lambda root,rel:root/rel,
                                    _hash_stable_file=lambda f:(sha256(f.read_bytes()).hexdigest(),f.stat().st_size))
            def modify_then_rows(_):
                d.write_bytes(b'changed')
                return iter([record()])
            with mock.patch.dict(sys.modules, {'market_quality_source_proofs':p}):
                with self.assertRaisesRegex(D.DayContentError,'DAY_FILE_CHANGED_DURING_CONTENT_CHECK'):
                    D.inspect_explicit(root,'official.parquet',expected,'2025-08-13',
                                       'SZ300888',row_reader=modify_then_rows)

class UnrecognizedInstrumentFailClosedTests(unittest.TestCase):
    def test_bad_prices_in_unrecognized_symbol_still_fail(self):
        rows=[record(),record(symbol='IDX000300',high=-1)]
        with self.assertRaises(D.DayContentError):
            D.validate_day_rows(rows,'2025-08-13','SZ300888')

    def test_huge_numeric_integer_is_not_uncaught_overflow(self):
        with self.assertRaises(D.DayContentError):
            D.validate_day_rows([record(amount=10**500)],
                                '2025-08-13','SZ300888')


class RealArrowTemporaryParquetTests(unittest.TestCase):
    @unittest.skipUnless(__import__('importlib').util.find_spec('pyarrow') is not None,
                         'requires pyarrow in the local verification environment')
    def test_real_arrow_parquet_schema_and_row_stream(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        row=record()
        schema=pa.schema([pa.field('ts',pa.int64()),pa.field('symbol',pa.string())]+[
            pa.field(key,pa.float64()) for key in D.FIELDS])
        table=pa.Table.from_pylist([row],schema=schema)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);file=root/'official_day.parquet'
            pq.write_table(table,file)
            import market_quality_source_proofs as P
            expected=P._hash_stable_file(file)[0]
            out=D.inspect_explicit(root,'official_day.parquet',expected,
                                   '2025-08-13','SZ300888')
            self.assertEqual(out['normalized_exchange_symbols_validated'],1)
            self.assertEqual(out['bound_official_day_file_bytes_sha256'],expected)
            self.assertFalse(out['market_admission_authorized'])
            self.assertEqual(out['qmt_history_download_calls'],0)

    @unittest.skipUnless(__import__('importlib').util.find_spec('pyarrow') is not None,
                         'requires pyarrow in the local verification environment')
    def test_real_arrow_wrong_schema_fails_closed(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        row=record()
        schema=pa.schema([pa.field('ts',pa.int32()),pa.field('symbol',pa.string())]+[
            pa.field(key,pa.float64()) for key in D.FIELDS])
        # wrong ts type, but value must fit int32 for file construction
        row['ts']=100
        table=pa.Table.from_pylist([row],schema=schema)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);file=root/'official_day.parquet'
            pq.write_table(table,file)
            import market_quality_source_proofs as P
            expected=P._hash_stable_file(file)[0]
            with self.assertRaisesRegex(ValueError,'schema'):
                D.inspect_explicit(root,'official_day.parquet',expected,
                                   '2025-08-13','SZ300888')
