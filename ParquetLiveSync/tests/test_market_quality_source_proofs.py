"""Actual temporary file byte verification, no market-provider IO or writes."""
from __future__ import annotations
from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import os
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import market_quality_source_proofs as M


class SourceProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'QMT').mkdir()
        (self.root/'DAY').mkdir()
        self.raw = self.root/'QMT'/'snapshot.raw'
        self.official = self.root/'DAY'/'ref.dat'
        self.raw.write_bytes(b'synthetic-one-minute-bars-2025-04-08')
        self.official.write_bytes(b'synthetic-official-day-reference-2025-04-08')
        self.manifest = {
            'format':M.FORMAT,
            'scope':{'trading_day':'2025-04-08','symbol':'SZ300888','period':'1min'},
            'artifacts':[
                {'role':'native_minute','source_id':'qmt-label','relative_path':'QMT/snapshot.raw',
                 'expected_sha256':sha256(self.raw.read_bytes()).hexdigest()},
                {'role':'official_day','source_id':'official-label','relative_path':'DAY/ref.dat',
                 'expected_sha256':sha256(self.official.read_bytes()).hexdigest()}],
        }
        self.write_manifest()

    def write_manifest(self):
        (self.root/'manifest.json').write_text(json.dumps(self.manifest,ensure_ascii=False),encoding='utf-8')

    def test_actual_two_file_hashes_match_and_no_provider_assertion(self):
        result=M.verify(self.root,'manifest.json')
        self.assertEqual(result['verified_local_file_count'],2)
        self.assertEqual(result['status'],M.STATUS)
        self.assertTrue(all(i['local_file_bytes_verified'] for i in result['artifacts']))
        self.assertFalse(result['provider_identity_independently_authenticated'])
        self.assertFalse(result['official_day_content_or_trading_universe_validated'])
        self.assertFalse(result['native_qmt_origin_proven'])
        self.assertFalse(result['market_data_content_validated'])
        self.assertFalse(result['production_admission_authorized'])
        self.assertFalse(result['market_files_written'])
        self.assertEqual(result['qmt_download_calls'],0)

    def test_all_bytes_and_mtime_unchanged_on_read(self):
        before={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        M.verify(self.root,'manifest.json')
        after={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_report_digest_canonical_and_not_self_ref(self):
        r=M.verify(self.root,'manifest.json')
        last=r.pop('report_sha256')
        self.assertEqual(last,M.digest(r))
        self.assertIn('NOT_TRUSTED_SIGNATURE',r['manifest_digest_scope'])

    def test_tampered_file_sha_rejected(self):
        self.raw.write_bytes(b'changed payload')
        with self.assertRaisesRegex(M.ProofError,'ARTIFACT_BYTES_SHA_MISMATCH'):
            M.verify(self.root,'manifest.json')

    def test_tampered_declared_digest_rejected(self):
        self.manifest['artifacts'][0]['expected_sha256']='a'*64
        self.write_manifest()
        with self.assertRaisesRegex(M.ProofError,'ARTIFACT_BYTES_SHA_MISMATCH'):
            M.verify(self.root,'manifest.json')

    def test_different_days_and_symbols_supported_without_fixed_date(self):
        for day,symbol in [('2015-06-11','SH600000'),('2026-11-26','BJ920021')]:
            with self.subTest(day=day):
                self.manifest['scope'].update(trading_day=day,symbol=symbol)
                self.write_manifest()
                self.assertEqual(M.verify(self.root,'manifest.json')['scope']['trading_day'],day)

    def test_all_eight_periods_supported(self):
        for p in M.PERIODS:
            with self.subTest(period=p):
                self.manifest['scope']['period']=p
                self.write_manifest()
                self.assertEqual(M.verify(self.root,'manifest.json')['scope']['period'],p)

    def test_bad_dates_symbols_periods_rejected(self):
        for key,value in [('trading_day','2026-02-30'),('symbol','../../bad'),('period','hour')]:
            with self.subTest(key=key):
                self.manifest['scope'][key]=value
                self.write_manifest()
                with self.assertRaises(M.ProofError):M.verify(self.root,'manifest.json')
                self.manifest['scope'][key]={'trading_day':'2025-04-08','symbol':'SZ300888','period':'1min'}[key]

    def test_relative_traversal_is_rejected(self):
        for bad in ['../secret','/etc/passwd','QMT/../../secret','QMT/./snapshot.raw','C:/secret','QMT\\snapshot.raw']:
            with self.subTest(path=bad):
                self.manifest['artifacts'][0]['relative_path']=bad
                self.write_manifest()
                with self.assertRaises(M.ProofError):M.verify(self.root,'manifest.json')

    def test_symlink_artifact_is_rejected(self):
        shortcut=self.root/'QMT'/'link.raw'
        try:shortcut.symlink_to(self.raw)
        except (OSError,NotImplementedError):self.skipTest('symlink unsupported')
        self.manifest['artifacts'][0]['relative_path']='QMT/link.raw'
        self.write_manifest()
        with self.assertRaisesRegex(M.ProofError,'SYMLINK'):
            M.verify(self.root,'manifest.json')

    def test_symlink_intermediate_directory_rejected(self):
        shortcut=self.root/'ALIAS'
        try:shortcut.symlink_to(self.root/'QMT',target_is_directory=True)
        except (OSError,NotImplementedError):self.skipTest('symlink unsupported')
        self.manifest['artifacts'][0]['relative_path']='ALIAS/snapshot.raw'
        self.write_manifest()
        with self.assertRaisesRegex(M.ProofError,'SYMLINK'):
            M.verify(self.root,'manifest.json')

    def test_hardlink_duplicate_physical_file_rejected(self):
        copy=self.root/'DAY'/'hardlink.raw'
        try:os.link(self.raw,copy)
        except OSError:self.skipTest('hardlink unsupported')
        self.manifest['artifacts'][1]['relative_path']='DAY/hardlink.raw'
        self.manifest['artifacts'][1]['expected_sha256']=sha256(copy.read_bytes()).hexdigest()
        self.write_manifest()
        with self.assertRaisesRegex(M.ProofError,'DUPLICATE_ARTIFACT_INODE'):
            M.verify(self.root,'manifest.json')

    def test_identical_contents_different_filenames_rejected(self):
        self.official.write_bytes(self.raw.read_bytes())
        self.manifest['artifacts'][1]['expected_sha256']=sha256(self.official.read_bytes()).hexdigest()
        self.write_manifest()
        with self.assertRaisesRegex(M.ProofError,'IDENTICAL_ARTIFACT_CONTENTS'):
            M.verify(self.root,'manifest.json')

    def test_same_source_label_not_evidence_of_independence(self):
        self.manifest['artifacts'][1]['source_id']='qmt-label'
        self.write_manifest()
        with self.assertRaisesRegex(M.ProofError,'DUPLICATE_DECLARED_SOURCE_ID'):
            M.verify(self.root,'manifest.json')

    def test_duplicate_role_and_missing_role_rejected(self):
        self.manifest['artifacts'][1]['role']='native_minute'
        self.write_manifest()
        with self.assertRaisesRegex(M.ProofError,'DUPLICATE_ARTIFACT_ROLE'):
            M.verify(self.root,'manifest.json')

    def test_invalid_expected_hash_rejected(self):
        self.manifest['artifacts'][0]['expected_sha256']='not-a-sha'
        self.write_manifest()
        with self.assertRaisesRegex(M.ProofError,'INVALID_ARTIFACT_SHA'):
            M.verify(self.root,'manifest.json')

    def test_duplicate_json_object_key_rejected(self):
        (self.root/'manifest.json').write_text('{"format": "bad",'+(self.root/'manifest.json').read_text()[1:])
        with self.assertRaisesRegex(M.ProofError,'DUPLICATE_MANIFEST_JSON_KEY'):
            M.verify(self.root,'manifest.json')

    def test_no_existing_manifest_rejected(self):
        with self.assertRaises(M.ProofError):M.verify(self.root,'missing.json')

    def test_empty_source_artifact_rejected(self):
        self.raw.write_bytes(b'')
        self.manifest['artifacts'][0]['expected_sha256']=sha256(b'').hexdigest()
        self.write_manifest()
        with self.assertRaisesRegex(M.ProofError,'ARTIFACT_EMPTY'):
            M.verify(self.root,'manifest.json')

    def test_unsupported_metadata_field_fail_closed(self):
        self.manifest['approved_for_production']=True
        self.write_manifest()
        with self.assertRaisesRegex(M.ProofError,'UNKNOWN_MANIFEST_FORMAT'):
            M.verify(self.root,'manifest.json')

    def test_source_sha_report_is_local_byte_claim_only(self):
        r=M.verify(self.root,'manifest.json')
        for x in r['artifacts']:
            self.assertFalse(x['provider_identity_independently_authenticated'])
            self.assertEqual(len(x['bytes_sha256']),64)
        self.assertTrue(r['distinct_declared_provider_labels_do_not_prove_independence'])

    def test_cli_success_without_writing_report(self):
        s=StringIO()
        with redirect_stdout(s):code=M.main(['--evidence-root',str(self.root),'--manifest-relative','manifest.json'])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(s.getvalue())['verified_local_file_count'],2)
        self.assertFalse((self.root/'proof.json').exists())

    def test_cli_fails_closed_without_leaking_absolute_path(self):
        s=StringIO()
        with redirect_stdout(s):code=M.main(['--evidence-root',str(self.root),'--manifest-relative','secret.dat'])
        self.assertEqual(code,3)
        self.assertNotIn(str(self.root),s.getvalue())

    def test_malformed_json_rejected(self):
        (self.root/'manifest.json').write_text('{broken')
        with self.assertRaisesRegex(M.ProofError,'MANIFEST_INVALID_JSON'):
            M.verify(self.root,'manifest.json')

    def test_no_external_provider_or_market_writer_dependency(self):
        import inspect
        text=inspect.getsource(M)
        for bad in ('xtquant','download_history_data(', 'pyarrow', 'pq.write_table(', 'os.replace('):
            self.assertNotIn(bad,text)

if __name__=='__main__': unittest.main()
