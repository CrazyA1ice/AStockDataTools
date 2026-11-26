"""Bounded nonrecursive local evidence inventory, not data provenance."""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
import contextlib
from io import StringIO
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_local_evidence_inventory_readonly as I


class InventoryTests(unittest.TestCase):
    def test_existing_minute_file_sha_exact_and_no_authority(self):
        with TemporaryDirectory() as t:
            (Path(t)/'probe.jsonl').write_bytes(b'one-minute-existing\n')
            d=I.inspect(t,'minute')
            self.assertEqual(d['file_count'],1)
            self.assertEqual(d['files'][0]['observed_local_file_sha256'],sha256(b'one-minute-existing\n').hexdigest())
            self.assertFalse(d['files'][0]['contents_validated'])
            self.assertFalse(d['qmt_native_origin_authenticated'])
            self.assertFalse(d['market_files_written'])

    def test_existing_day_parquet_bytes_not_parsed_or_authenticated(self):
        with TemporaryDirectory() as t:
            (Path(t)/'2026-11-25.parquet').write_bytes(b'local-day-claim-not-real-parquet')
            d=I.inspect(t,'day')
            self.assertEqual(d['file_count'],1)
            self.assertFalse(d['official_day_provider_identity_authenticated'])
            self.assertFalse(d['exchange_stock_day_universe_certified'])

    def test_ignores_other_extensions_and_does_not_recurse(self):
        with TemporaryDirectory() as t:
            (Path(t)/'other.txt').write_text('a')
            (Path(t)/'nested').mkdir()
            (Path(t)/'nested'/'qmt.jsonl').write_text('x')
            d=I.inspect(t,'minute')
            self.assertEqual(d['file_count'],0)
            self.assertEqual(d['directories_recursively_scanned'],0)
            self.assertTrue(d['empty_directory_or_no_matching_files'])

    def test_sorted_reproducible_names_and_hashes(self):
        with TemporaryDirectory() as t:
            (Path(t)/'z.jsonl').write_bytes(b'z')
            (Path(t)/'a.jsonl').write_bytes(b'a')
            x=I.inspect(t,'minute');y=I.inspect(t,'minute')
            self.assertEqual(x,y)
            self.assertEqual([r['relative_path'] for r in x['files']],['a.jsonl','z.jsonl'])

    def test_invalid_kind_refused(self):
        with TemporaryDirectory() as t:
            with self.assertRaisesRegex(I.InventoryError,'KIND_INVALID'):
                I.inspect(t,'qmt-cache')

    def test_relative_escaping_of_root_not_attempted(self):
        with self.assertRaises(ValueError):
            I.inspect('/','day')

    def test_root_symlink_refused(self):
        with TemporaryDirectory() as t:
            target=Path(t)/'data';target.mkdir()
            link=Path(t)/'link'
            try:link.symlink_to(target, target_is_directory=True)
            except (OSError,NotImplementedError):self.skipTest('symlinks unavailable')
            with self.assertRaisesRegex(I.InventoryError,'ROOT_INVALID'):
                I.inspect(link,'minute')

    def test_file_symlink_refused(self):
        with TemporaryDirectory() as t:
            (Path(t)/'real.jsonl').write_bytes(b'ok')
            link=Path(t)/'alias.jsonl'
            try:link.symlink_to(Path(t)/'real.jsonl')
            except (OSError,NotImplementedError):self.skipTest('symlinks unavailable')
            with self.assertRaisesRegex(I.InventoryError,'LINK_OR_NONFILE'):
                I.inspect(t,'minute')

    def test_empty_matching_file_rejected(self):
        with TemporaryDirectory() as t:
            (Path(t)/'zero.jsonl').write_bytes(b'')
            with self.assertRaisesRegex(I.InventoryError,'FILE_SIZE_INVALID'):
                I.inspect(t,'minute')

    def test_max_matches_fail_not_silently_truncate(self):
        with TemporaryDirectory() as t:
            for i in range(I.MAX_MATCHED+1):
                (Path(t)/f'{i:03}.jsonl').write_bytes(b'x')
            with self.assertRaisesRegex(I.InventoryError,'MATCHED_LIMIT'):
                I.inspect(t,'minute')

    def test_directory_entries_budget_fail_closed(self):
        with TemporaryDirectory() as t:
            for i in range(I.MAX_ENTRIES+1):
                (Path(t)/f'{i:04}.skip').write_bytes(b'x')
            with self.assertRaisesRegex(I.InventoryError,'ENTRIES_LIMIT'):
                I.inspect(t,'day')

    def test_declared_total_byte_budget_rejected_before_hash(self):
        with TemporaryDirectory() as t:
            (Path(t)/'x.jsonl').write_bytes(b'x')
            with mock.patch.object(I,'MAX_TOTAL_BYTES',0):
                with mock.patch.object(I.PROOF,'_hash_stable_file',side_effect=AssertionError('hash should not run')):
                    with self.assertRaisesRegex(I.InventoryError,'TOTAL_SIZE_LIMIT'):
                        I.inspect(t,'minute')

    def test_one_large_file_size_rejected_before_hash(self):
        with TemporaryDirectory() as t:
            (Path(t)/'x.jsonl').write_bytes(b'x')
            with mock.patch.object(I,'MAX_SINGLE_BYTES',0):
                with self.assertRaisesRegex(I.InventoryError,'FILE_SIZE_INVALID'):
                    I.inspect(t,'minute')

    def test_file_mutation_during_hash_rejected(self):
        with TemporaryDirectory() as t:
            f=Path(t)/'sample.jsonl';f.write_bytes(b'sample')
            real=I.PROOF._hash_stable_file
            def mutate(p):
                digest,n=real(p)
                p.write_bytes(b'different')
                return digest,n
            with mock.patch.object(I.PROOF,'_hash_stable_file',side_effect=mutate):
                with self.assertRaisesRegex(I.InventoryError,'CHANGED_DURING_HASH'):
                    I.inspect(t,'minute')

    def test_no_qmt_sdk_import_or_market_writers(self):
        import inspect
        s=inspect.getsource(I)
        for prohibited in ('get_market_data_ex(', 'download_history_data(',
                           'write_bytes(', 'write_table(', 'os.replace(', 'mkdir('):
            self.assertNotIn(prohibited,s)

    def test_cli_failure_does_not_leak_private_directory(self):
        out=StringIO()
        with contextlib.redirect_stdout(out):
            code=I.main(['--evidence-root','/private/unknown-qmt-root','--kind','minute'])
        self.assertEqual(code,3)
        self.assertNotIn('/private/',out.getvalue())


if __name__=='__main__':unittest.main()
