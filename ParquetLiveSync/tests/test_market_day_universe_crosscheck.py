"""Synthetic read-only source-universe crosschecks, with actual temporary file hashes."""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_day_universe_crosscheck as U
import market_live_day_overlay_audit as O


def row(day='2026-11-25', symbol='SH605336', *, close=7.95, volume=1000., amount=8000.):
    stamp = int(datetime.fromisoformat(day).replace(
        tzinfo=timezone(timedelta(hours=8))).timestamp() * 1000)
    return {'ts': stamp, 'symbol': symbol,
            'open': 7.62, 'high': 8.31, 'low': 7.62, 'close': close,
            'volume': volume, 'amount': amount}


def item(symbol, state='TRADED'):
    return {'symbol': symbol, 'trading_state': state}


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'ParquetLiveSync'
        self.work = self.root / 'work'
        self.work.mkdir(parents=True)
        self.refroot = Path(self.tmp.name) / 'External' / 'reference'
        self.refroot.mkdir(parents=True)
        self.day = '2026-11-25'
        self.anchor = 'SH605336'
        self.rows = [row(), row(symbol='SZ300462'), row(symbol='SZ300119')]
        self.reference = {'format': U.FORMAT, 'trading_day': self.day,
                          'source_id': 'declared-external-v1',
                          'coverage_claim': 'PARTIAL_DECLARED',
                          'symbols': [item('SH605336'), item('SZ300462'),
                                      item('SZ300120'), item('SZ300119', 'NO_TRADE')]}
        self.build_overlay()
        self.write_reference()

    def build_overlay(self):
        rel = f'incremental/day/year={self.day[:4]}/{self.day}.parquet'
        path = self.work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('temporary synthetic day ' + self.day).encode())
        data_sha = sha256(path.read_bytes()).hexdigest()
        rec = {'date': self.day, 'file': rel, 'sha256': data_sha,
               'rows': len(self.rows), 'raw_zip_sha256': 'b' * 64,
               'origin': 'local-test-synthetic-only',
               'base_dataset_sha256': O.BASE_SHA,
               'original_Parquet_files_unchanged': True,
               'source_values_adj': 'none', 'calibration': {'factor': 1.0}}
        receipt = path.with_suffix('.json')
        receipt.write_text(json.dumps(rec))
        state = {'format': O.FORMAT, 'base_dataset_sha256': O.BASE_SHA,
                 'base_day': O.BASE_DAY.isoformat(), 'production_activated': False,
                 'days': {self.day: {'file': rel, 'sha256': data_sha,
                                    'rows': len(self.rows),
                                    'source_zip_sha256': 'b' * 64,
                                    'receipt_sha256': sha256(receipt.read_bytes()).hexdigest()}}}
        (self.work / 'state.json').write_text(json.dumps(state))
        self.parquet = path
        self.receipt = receipt

    def write_reference(self):
        file = self.refroot / 'reference.json'
        file.write_text(json.dumps(self.reference, sort_keys=True), encoding='utf-8')
        self.ref_sha = sha256(file.read_bytes()).hexdigest()
        self.ref_file = file

    def audit(self, *, rows=None, reference_sha=None):
        if rows is None:
            rows = self.rows
        return U.inspect(self.root, self.day, self.anchor,
                         reference_root=self.refroot,
                         reference_relative='reference.json',
                         reference_sha256=reference_sha or self.ref_sha,
                         row_reader=lambda _: iter(rows))

    def test_two_source_crosscompare_precise_buckets(self):
        out = self.audit()
        c = out['counts']
        self.assertEqual(c['declared_traded_missing_in_overlay'], 1)
        self.assertEqual(out['groups']['declared_traded_missing_in_overlay'], ['SZ300120'])
        self.assertEqual(c['declared_no_trade_but_active_in_overlay'], 1)
        self.assertEqual(c['declared_traded_and_overlay_active'], 2)
        self.assertEqual(out['rows_checked'], 3)
        self.assertTrue(out['has_declared_conflict'])
        for flag in ('reference_full_stock_day_universe_certified',
                     'independent_reference_provider_authenticated',
                     'tdx_provider_identity_authenticated',
                     'source_independence_authenticated',
                     'market_write_authorized', 'market_files_written',
                     'native_qmt_1min_certified',
                     'original_producer_quarantines_cleared'):
            self.assertFalse(out[flag], flag)
        self.assertEqual(out['qmt_history_download_calls'], 0)
        self.assertEqual(out['comparison_json_sha256'],
                         U.sha({k: v for k, v in out.items()
                                if k != 'comparison_json_sha256'}))

    def test_reference_full_claim_never_certifies_universe(self):
        self.reference['coverage_claim'] = 'FULL_DECLARED'
        self.write_reference()
        out = self.audit()
        self.assertEqual(out['declared_reference_coverage_claim'], 'FULL_DECLARED')
        self.assertFalse(out['reference_full_stock_day_universe_certified'])
        self.assertFalse(out['instrument_membership_authenticated'])

    def test_reference_sha_tamper_before_content_scan(self):
        self.ref_file.write_bytes(b'changed')
        with self.assertRaisesRegex(U.CrosscheckError, 'REFERENCE_BYTES_SHA_MISMATCH'):
            self.audit()

    def test_reference_sha_forgery_rejected(self):
        with self.assertRaisesRegex(U.CrosscheckError, 'REFERENCE_BYTES_SHA_MISMATCH'):
            self.audit(reference_sha='a' * 64)

    def test_date_mismatch_reference_is_rejected(self):
        self.reference['trading_day'] = '2026-11-24'
        self.write_reference()
        with self.assertRaisesRegex(U.CrosscheckError, 'REFERENCE_DATE_DISAGREES'):
            self.audit()

    def test_duplicate_json_key_is_rejected(self):
        self.ref_file.write_text('{"format":"garbage",' + self.ref_file.read_text()[1:])
        self.ref_sha = sha256(self.ref_file.read_bytes()).hexdigest()
        with self.assertRaisesRegex(O.OverlayError, 'DUPLICATE_JSON_KEY'):
            self.audit()

    def test_duplicate_symbol_rejected(self):
        self.reference['symbols'].append(item('SH605336'))
        self.write_reference()
        with self.assertRaisesRegex(U.CrosscheckError, 'DUPLICATE_SYMBOL'):
            self.audit()

    def test_invalid_symbol_or_state_rejected(self):
        for rec in (item('SH000'), item('SZ300119', 'MISSING'), item('../../bad')):
            self.reference['symbols'] = [rec]
            self.write_reference()
            with self.assertRaises(U.CrosscheckError):
                self.audit()

    def test_missing_declared_status_not_mistaken_as_nontrade(self):
        self.reference['symbols'] = [item('SZ300120', 'UNKNOWN')]
        self.write_reference()
        r = self.audit()
        self.assertFalse(r['has_declared_conflict'])
        self.assertEqual(r['counts']['declared_no_trade_absent_from_overlay'], 0)

    def test_declared_no_trade_absent_expected_without_false_conflict(self):
        self.reference['symbols'] = [item('SZ300120', 'NO_TRADE')]
        self.write_reference()
        r = self.audit()
        self.assertEqual(r['counts']['declared_no_trade_absent_from_overlay'], 1)
        self.assertFalse(r['has_declared_conflict'])

    def test_overlay_code_absent_declared_reference_is_uncertain_not_extra_equity(self):
        self.reference['symbols'] = [item('SH605336')]
        self.write_reference()
        r = self.audit()
        self.assertEqual(r['groups']['overlay_code_not_in_declared_reference'],
                         ['SZ300119', 'SZ300462'])
        self.assertFalse(r['instrument_membership_authenticated'])
        self.assertFalse(r['reference_full_stock_day_universe_certified'])

    def test_reference_symlink_escape_is_rejected(self):
        ref = self.refroot / 'link.json'
        try:
            ref.symlink_to(self.ref_file)
        except (OSError, NotImplementedError):
            self.skipTest('symlink unsupported')
        with self.assertRaises((ValueError, O.OverlayError)):
            U.parse_reference(self.refroot, 'link.json', self.ref_sha, self.day)

    def test_reference_parent_path_escape_rejected(self):
        with self.assertRaises((ValueError, O.OverlayError)):
            U.parse_reference(self.refroot, '../reference/reference.json',
                              self.ref_sha, self.day)

    def test_tdx_overlay_parquet_source_digest_is_still_bound(self):
        self.parquet.write_bytes(b'changed')
        with self.assertRaisesRegex(Exception, 'DAY_FILE_SHA_CHANGED'):
            self.audit()

    def test_tdx_state_mutation_blocks_snapshot(self):
        p = self.work / 'state.json'
        state = json.loads(p.read_text())
        state['base_dataset_sha256'] = 'f' * 64
        p.write_text(json.dumps(state))
        with self.assertRaisesRegex(O.OverlayError, 'OVERLAY_STATE_IDENTITY'):
            self.audit()

    def test_different_dates_and_symbols_same_logic(self):
        for day, anchor, second in [('2026-10-14', 'SZ300888', 'SH600000'),
                                    ('2027-01-08', 'BJ920021', 'SZ300462')]:
            with self.subTest(day=day):
                self.day, self.anchor = day, anchor
                self.rows = [row(day, symbol=anchor), row(day, symbol=second)]
                self.reference['trading_day'] = day
                self.reference['symbols'] = [item(anchor), item(second)]
                self.build_overlay()
                self.write_reference()
                self.assertEqual(self.audit()['counts']['declared_traded_and_overlay_active'], 2)

    def test_zero_vol_and_zero_amount_in_day_is_valid_nontrade(self):
        self.rows = [row(), row(symbol='SZ300462', volume=0, amount=0)]
        self.reference['symbols'] = [item('SH605336'), item('SZ300462', 'NO_TRADE')]
        self.build_overlay()
        self.write_reference()
        self.assertFalse(self.audit()['has_declared_conflict'])

    def test_declared_traded_zero_in_overlay_is_conflict(self):
        self.rows = [row(), row(symbol='SZ300462', volume=0, amount=0)]
        self.reference['symbols'] = [item('SH605336'), item('SZ300462')]
        self.build_overlay()
        self.write_reference()
        self.assertEqual(self.audit()['counts']['declared_traded_zero_in_overlay'], 1)

    def test_invalid_ohlcva_does_not_get_discarded(self):
        self.rows = [row(), row(symbol='UNRECOGNIZED', close=20.)]
        self.build_overlay()
        with self.assertRaisesRegex(Exception, 'OHLC_ENVELOPE'):
            self.audit()

    def test_same_normalized_code_with_suffix_rejected(self):
        self.rows = [row(), row(symbol='605336.SH')]
        self.build_overlay()
        with self.assertRaisesRegex(Exception, 'DUPLICATE_NORMALIZED'):
            self.audit()

    def test_wrong_timestamp_fails(self):
        self.rows = [row(), row('2026-11-24', 'SZ300462')]
        self.build_overlay()
        with self.assertRaisesRegex(Exception, 'WRONG_DATE'):
            self.audit()

    def test_different_reference_source_labels_never_claim_independence(self):
        self.reference['source_id'] = 'other-trusted-looking-label'
        self.write_reference()
        out = self.audit()
        self.assertFalse(out['source_independence_authenticated'])

    def test_summary_cli_requires_all_proof_fields_and_exposes_no_paths(self):
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            code = U.main(['--module-root', str(self.root), '--trading-day', self.day,
                           '--anchor-symbol', self.anchor,
                           '--reference-root', str(self.refroot),
                           '--reference-relative', 'nonexistent.json',
                           '--reference-sha256', 'a' * 64, '--summary-only'])
        self.assertEqual(code, 3)
        self.assertNotIn(str(self.refroot), buf.getvalue())

    def test_readonly_files_unchanged_after_inspection(self):
        before = {str(x): (x.read_bytes(), x.stat().st_mtime_ns)
                  for x in Path(self.tmp.name).rglob('*') if x.is_file()}
        self.audit()
        after = {str(x): (x.read_bytes(), x.stat().st_mtime_ns)
                 for x in Path(self.tmp.name).rglob('*') if x.is_file()}
        self.assertEqual(before, after)

    def test_reference_changes_during_overlay_comparison_rejected(self):
        def mutate_then_read(_):
            self.reference['source_id'] = 'altered-while-scanning'
            self.write_reference()
            return iter(self.rows)
        with self.assertRaises(U.CrosscheckError):
            U.inspect(self.root, self.day, self.anchor,
                      reference_root=self.refroot,
                      reference_relative='reference.json',
                      reference_sha256=self.ref_sha,
                      row_reader=mutate_then_read)

    def test_unknown_absent_and_present_are_separate_noncertifying_buckets(self):
        self.reference['symbols'] = [item('SZ300120', 'UNKNOWN'),
                                     item('SZ300119', 'UNKNOWN')]
        self.write_reference()
        out = self.audit()
        self.assertEqual(out['groups']['declared_unknown_absent_from_overlay'], ['SZ300120'])
        self.assertEqual(out['groups']['declared_unknown_present_in_overlay'], ['SZ300119'])
        self.assertFalse(out['has_declared_conflict'])

    def test_zero_amount_positive_volume_fails_closed(self):
        self.rows = [row(), row(symbol='SZ300462', amount=0)]
        self.build_overlay()
        with self.assertRaisesRegex(Exception, 'VOLUME_AMOUNT'):
            self.audit()

    def test_invalid_source_label_rejected_even_with_valid_sha(self):
        self.reference['source_id'] = '../../not-an-origin'
        self.write_reference()
        with self.assertRaisesRegex(U.CrosscheckError, 'REFERENCE_SOURCE_LABEL_INVALID'):
            self.audit()

    def test_empty_or_bad_reference_records_fail(self):
        for records in ([], [{'symbol': 'SH605336'}]):
            self.reference['symbols'] = records
            self.write_reference()
            with self.assertRaises(U.CrosscheckError):
                self.audit()

    def test_overlay_authority_changed_fail_closed(self):
        real = O.inspect(self.root, self.day, self.anchor,
                         day_reader=lambda _: iter(self.rows))
        bad = dict(real)
        bad['market_data_write_authorized'] = True
        with self.assertRaisesRegex(U.CrosscheckError, 'AUTHORITY_OR_IDENTITY_CHANGED'):
            U.inspect(self.root, self.day, self.anchor,
                      reference_root=self.refroot,
                      reference_relative='reference.json',
                      reference_sha256=self.ref_sha,
                      row_reader=lambda _: iter(self.rows),
                      overlay_checker=lambda *a, **kw: bad)

    def test_reference_changed_only_during_second_pass_is_rejected(self):
        count = 0
        def second_pass_mutation(_):
            nonlocal count
            count += 1
            if count == 2:
                self.reference['source_id'] = 'changed-while-overlay-scanning'
                self.write_reference()
            return iter(self.rows)
        with self.assertRaisesRegex(U.CrosscheckError, 'REFERENCE_BYTES_SHA_MISMATCH'):
            U.inspect(self.root, self.day, self.anchor,
                      reference_root=self.refroot,
                      reference_relative='reference.json',
                      reference_sha256=self.ref_sha,
                      row_reader=second_pass_mutation)
        self.assertEqual(count, 2)

    @unittest.skipUnless(__import__('importlib').util.find_spec('pyarrow') is not None,
                         'requires pyarrow for real temporary ParquetFile batch streaming')
    def test_real_temporary_arrow_parquet_and_reference_json(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        schema = pa.schema([pa.field('ts', pa.int64()),
                            pa.field('symbol', pa.string())] + [
            pa.field(k, pa.float64()) for k in
            ('open', 'high', 'low', 'close', 'volume', 'amount')])
        pq.write_table(pa.Table.from_pylist(self.rows, schema=schema), self.parquet)
        digest = sha256(self.parquet.read_bytes()).hexdigest()
        receipt = json.loads(self.receipt.read_text())
        receipt['sha256'] = digest
        self.receipt.write_text(json.dumps(receipt))
        stpath = self.work / 'state.json'
        state = json.loads(stpath.read_text())
        state['days'][self.day]['sha256'] = digest
        state['days'][self.day]['receipt_sha256'] = sha256(self.receipt.read_bytes()).hexdigest()
        stpath.write_text(json.dumps(state))
        output = U.inspect(self.root, self.day, self.anchor,
                           reference_root=self.refroot,
                           reference_relative='reference.json',
                           reference_sha256=self.ref_sha)
        self.assertEqual(output['rows_checked'], 3)
        self.assertFalse(output['market_files_written'])
        self.assertEqual(output['qmt_history_download_calls'], 0)


if __name__ == '__main__':
    unittest.main()
