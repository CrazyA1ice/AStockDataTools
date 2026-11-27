"""Only temporary synthetic data; direct JSON shard evidence must fail closed."""
from __future__ import annotations

from hashlib import sha256
from io import StringIO
import contextlib
import inspect as inspect_module
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_dense_receipts_direct_json_shards_readonly as S


class DenseDirectJsonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.module = Path(self.tmp.name)
        self.directory = self.module / 'work'
        self.directory.mkdir()
        for part in S.DIRECT_SUBDIR.split('/'):
            self.directory = self.directory / part
            self.directory.mkdir()
        self.payload = b'{"original":"synthetic SHA test only"}'
        self.synthetic_sha = sha256(self.payload).hexdigest()

    def write(self, name, contents=b'{"other":1}'):
        file = self.directory / name
        file.write_bytes(contents)
        return file

    def inspect(self, **kwargs):
        with mock.patch.object(S, 'TARGET_SHA', self.synthetic_sha):
            return S.inspect(self.module, expected_sha=self.synthetic_sha, **kwargs)

    def test_target_original_digest_is_pinned(self):
        self.assertEqual(S.TARGET_SHA,
                         '72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837')

    def test_empty_directory_is_exhaustive_only_for_explicit_scope(self):
        r = self.inspect()
        self.assertEqual(r['direct_json_candidates'], 0)
        self.assertEqual(r['matching_file_count'], 0)
        self.assertTrue(r['scope_exhaustive'])
        self.assertTrue(r['direct_only_no_recursion'])
        self.assertFalse(r['producer_receipt_stage_log_verified'])
        self.assertFalse(r['producer_quarantine_cleared'])

    def test_original_sha_match_is_only_physical_candidate_not_admission(self):
        self.write('receipt-original.json', self.payload)
        r = self.inspect()
        self.assertEqual(r['matching_file_count'], 1)
        hit = r['exact_original_receipt_matches'][0]
        self.assertEqual(hit['receipt_relative_within_work'],
                         S.DIRECT_SUBDIR + '/receipt-original.json')
        self.assertEqual(hit['receipt_bytes_sha256'], self.synthetic_sha)
        self.assertFalse(hit['stage_log_verified'])
        self.assertFalse(hit['candidate_parquet_verified'])
        self.assertFalse(r['market_files_written'])
        self.assertFalse(r['qmt_cache_queried_or_modified'])
        self.assertEqual(r['qmt_download_calls'], 0)

    def test_more_than_768_nonjson_direct_entries_do_not_block_metadata_prefilter(self):
        for i in range(790):
            self.write(f'100000{i:05}.parquet', b'x')
        self.write('needle.json', self.payload)
        r = self.inspect()
        self.assertEqual(r['directory_entries_examined_metadata_only'], 791)
        self.assertEqual(r['direct_json_candidates'], 1)
        self.assertEqual(r['matching_file_count'], 1)
        self.assertTrue(r['scope_exhaustive'])

    def test_all_140_json_checked_in_disjoint_safely_bounded_shards(self):
        for i in range(139):
            self.write(f'r{i:05}.json', str(i).encode())
        self.write('real-original.json', self.payload)
        r = self.inspect()
        self.assertEqual(r['physically_hashed_json_files'], 140)
        self.assertEqual(r['direct_json_candidates'], 140)
        self.assertEqual(r['matching_file_count'], 1)
        self.assertEqual(r['shard_max_json_files'], 128)
        self.assertEqual(r['shard_max_bytes'], 64*1024*1024)
        self.assertEqual(r['single_file_max_bytes'], 24*1024*1024)
        self.assertEqual(r['shards_checked'], 16)

    def test_single_16way_overfull_bucket_refines_to_256way_without_lost_names(self):
        names=[]
        for i in range(10000):
            candidate=f'receipt-{i:06}.json'
            if S._bucket(candidate, 16)==0:
                names.append(candidate)
                if len(names)==129:
                    break
        self.assertEqual(len(names),129)
        for name in names:
            self.write(name, b'x')
        r=self.inspect()
        self.assertEqual(r['physically_hashed_json_files'],129)
        self.assertEqual(r['matching_file_count'],0)
        self.assertEqual(r['shards_checked'],31)
        self.assertTrue(r['scope_exhaustive'])

    def test_256way_overfull_bucket_stops_before_hash(self):
        for i in range(129):
            self.write(f'r{i:03}.json', b'x')
        with mock.patch.object(S, '_bucket', lambda _name, _slots: 0):
            with self.assertRaisesRegex(S.DenseReceiptError,
                                        'DENSE_SHARD_JSON_CANDIDATE_BUDGET'):
                self.inspect()

    def test_direct_entry_count_metadata_budget_still_fails_closed(self):
        self.write('a.json')
        self.write('b.json')
        with mock.patch.object(S,'MAX_DIRECT_ENTRIES_METADATA_ONLY',1):
            with self.assertRaisesRegex(S.DenseReceiptError,
                                        'DENSE_DIRECT_ENTRY_METADATA_BUDGET'):
                self.inspect()

    def test_direct_json_metadata_budget_fails_closed(self):
        self.write('a.json')
        self.write('b.json')
        with mock.patch.object(S,'MAX_DIRECT_JSON_METADATA',1):
            with self.assertRaisesRegex(S.DenseReceiptError,
                                        'DENSE_DIRECT_JSON_METADATA_BUDGET'):
                self.inspect()

    def test_file_size_budget_rejected(self):
        self.write('big.json',b'bytes')
        with mock.patch.object(S,'MAX_SINGLE_JSON_BYTES',3):
            with self.assertRaisesRegex(S.DenseReceiptError,
                                        'DENSE_FILE_BYTES_BUDGET'):
                self.inspect()

    def test_per_shard_byte_budget_rejected(self):
        self.write('one.json',b'four')
        with mock.patch.object(S,'MAX_PER_SHARD_BYTES',3):
            with self.assertRaisesRegex(S.DenseReceiptError,
                                        'DENSE_SHARD_BYTES_BUDGET'):
                self.inspect()

    def test_global_byte_budget_rejected(self):
        self.write('one.json',b'four')
        with mock.patch.object(S,'MAX_GLOBAL_HASH_BYTES',3):
            with self.assertRaisesRegex(S.DenseReceiptError,
                                        'DENSE_GLOBAL_HASH_BYTES_BUDGET'):
                self.inspect()

    def test_empty_json_fails_not_silent_skip(self):
        self.write('empty.json',b'')
        with self.assertRaisesRegex(S.DenseReceiptError,
                                    'DENSE_FILE_BYTES_BUDGET'):
            self.inspect()

    def test_json_symlink_rejected_even_if_not_match_shard(self):
        original=self.write('original.json',self.payload)
        alias=self.directory/'alias.json'
        try:
            alias.symlink_to(original)
        except (OSError,NotImplementedError):
            self.skipTest('Windows symlink privileges unavailable')
        with self.assertRaisesRegex(S.DenseReceiptError,
                                    'DENSE_JSON_LINK_OR_NONREGULAR'):
            self.inspect()

    def test_json_named_directory_rejected(self):
        (self.directory/'folder.json').mkdir()
        with self.assertRaisesRegex(S.DenseReceiptError,
                                    'DENSE_JSON_LINK_OR_NONREGULAR'):
            self.inspect()

    def test_nested_json_not_claimed_by_direct_only_search(self):
        deep=self.directory/'nested'
        deep.mkdir()
        (deep/'original.json').write_bytes(self.payload)
        r=self.inspect()
        self.assertEqual(r['direct_json_candidates'],0)
        self.assertTrue(r['direct_only_no_recursion'])
        self.assertEqual(r['matching_file_count'],0)

    def test_changed_json_during_physical_hash_fails_closed(self):
        self.write('mutable.json',b'first')
        original=S.PROOF._hash_stable_file
        def change(file):
            out=original(file)
            file.write_bytes(b'different-length-change')
            return out
        with mock.patch.object(S.PROOF,'_hash_stable_file',side_effect=change):
            with self.assertRaisesRegex(S.DenseReceiptError,
                                        'DENSE_FILE_CHANGED_DURING_HASH'):
                self.inspect()

    def test_full_snapshot_drift_detected_even_when_not_selected_original(self):
        self.write('x.json',b'x')
        original=S._snapshot
        calls=[0]
        def changed(directory):
            calls[0]+=1
            if calls[0]==2:
                (directory/'new-arrival.json').write_bytes(b'new')
            return original(directory)
        with mock.patch.object(S,'_snapshot',side_effect=changed):
            with self.assertRaisesRegex(S.DenseReceiptError,
                                        'DENSE_DIRECTORY_CHANGED_DURING_HASH'):
                self.inspect()

    def test_missing_explicit_target_refused(self):
        with TemporaryDirectory() as root:
            (Path(root)/'work').mkdir()
            with self.assertRaisesRegex(S.OLD.ReceiptLocateError,
                                        'SEARCH_SUBDIRECTORY_OUTSIDE_WORK_OR_MISSING'):
                S.inspect(root)

    def test_cli_reason_whitelist_never_echoes_private_error_details(self):
        out=StringIO()
        with mock.patch.object(S,'inspect',side_effect=S.DenseReceiptError(
                'C:/Private/secret.json')):
            with contextlib.redirect_stdout(out):
                rc=S.main(['--module-root',str(self.module)])
        self.assertEqual(rc,3)
        self.assertIn('DENSE_UNRECOGNIZED_REASON_WITHHELD',out.getvalue())
        self.assertNotIn('Private',out.getvalue())
        self.assertNotIn(str(self.module),out.getvalue())

    def test_cli_missing_target_only_exposes_error_type_not_private_path(self):
        out=StringIO()
        with TemporaryDirectory() as root:
            with contextlib.redirect_stdout(out):
                rc=S.main(['--module-root',root])
        self.assertEqual(rc,3)
        self.assertIn('DENSE_WORK_ROOT_INVALID',out.getvalue())
        self.assertNotIn(root,out.getvalue())

    def test_no_download_or_market_data_write_in_implementation(self):
        src=inspect_module.getsource(S)
        for forbidden in ('download_history_data(', 'get_market_data_ex(',
                          'write_bytes(', 'write_table(', 'os.replace(',
                          'mkdir(', 'unlink(', 'rename(', 'replace('):
            self.assertNotIn(forbidden,src)


if __name__=='__main__':
    unittest.main()
