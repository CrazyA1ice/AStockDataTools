"""Strict local read-only quarantine evidence tests; no QMT/network/state writes."""
import importlib.util
import json
from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch

src = Path(__file__).resolve().parents[1] / 'audit_market_quarantine_readonly.py'
spec = importlib.util.spec_from_file_location('audit_quarantine', src)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root/'work'
        self.private = self.work/'market_update'/'daily'
        self.private.mkdir(parents=True)
        self.day = '2026-11-25'
        self.parquet = self.private/(self.day+'.parquet')
        self.parquet.write_bytes(b'fake candidate')
        self.sha = hashlib.sha256(self.parquet.read_bytes()).hexdigest()
        self.q = {'SH605336':'ValueError: Independent official DAY materialized OHLC discrepancy: open',
                  'SZ300119':'ValueError: QMT returned no original OHLCVA 1m: 300119.SZ'}
        self.meta = {'format':'one_command_qmt_market_update_v1','date':self.day,'sha256':self.sha,'rows':5206*240,
                     'stock_days_accepted':5206,'expected_stock_days':5208,'quarantined':self.q}
        self.save_meta()
        self.stage = {'date':self.day,'sha256':self.sha,'accepted':5206,'quarantine':2,'rows':5206*240}
        self.log=self.work/'afternoon-stage.log'
        self.log.write_text(a.MARKER+json.dumps(self.stage)+'\n',encoding='utf-8')
        self.run={'format':'qmt_daily_single_trigger_v3','invocation':'Scheduled',
                  'run_scope':'ALL_FOUR_SECTIONS','history_only':False,
                  'china_start':self.day+'T20:05:02.9370848',
                  'stage_records':{'EIGHT_PERIODS':{'exit_code':0,'log_path':str(self.log)}}}
        self.run_file=self.work/'last-afternoon-unified.json'
        self.save_run()
    def save_meta(self):
        (self.private/(self.day+'.json')).write_text(json.dumps(self.meta),encoding='utf-8')
    def save_run(self):
        self.run_file.write_text(json.dumps(self.run),encoding='utf-8')
        self.run_sha=hashlib.sha256(self.run_file.read_bytes()).hexdigest()
    def run_audit(self, verify=False):
        return a.audit(self.root,self.day,self.run_sha,verify)
    def test_metadata_only_truthful(self):
        o=self.run_audit()
        self.assertEqual(o['quarantined'],2)
        self.assertEqual(o['accepted'],5206)
        self.assertEqual(o['expected'],5208)
        self.assertFalse(o['parquet_content_sha_verified'])
        self.assertFalse(o['data_quality_cleared'])
        self.assertEqual(o['reason_groups'],{'OFFICIAL_DAY_OHLC_MISMATCH':1,'QMT_RAW_ONE_MINUTE_MISSING':1})
    def test_optional_parquet_hash_passes(self):
        self.assertTrue(self.run_audit(verify=True)['parquet_content_sha_verified'])
    def test_parquet_content_tamper_not_covered_by_metadata_only(self):
        self.parquet.write_bytes(b'changed')
        self.assertFalse(self.run_audit()['parquet_content_sha_verified'])
        with self.assertRaisesRegex(a.EvidenceError,'PHYSICAL_PARQUET_SHA_MISMATCH'):
            self.run_audit(verify=True)
    def test_run_hash_required(self):
        with self.assertRaisesRegex(a.EvidenceError,'RUN_RECEIPT_SHA_MISMATCH'):
            a.audit(self.root,self.day,'f'*64)
    def test_wrong_run_rejected(self):
        self.run['invocation']='Manual';self.save_run()
        with self.assertRaisesRegex(a.EvidenceError,'WRONG_SCHEDULED_RUN'):
            self.run_audit()
    def test_off_work_log_rejected(self):
        elsewhere=self.root/'external.log';elsewhere.write_text('test')
        self.run['stage_records']['EIGHT_PERIODS']['log_path']=str(elsewhere);self.save_run()
        with self.assertRaisesRegex(a.EvidenceError,'OUTSIDE_WORK'):
            self.run_audit()
    def test_symlink_log_rejected(self):
        other=self.work/'real.log';other.write_text('x')
        self.log.unlink();self.log.symlink_to(other)
        with self.assertRaisesRegex(a.EvidenceError,'STAGE_LOG_OUTSIDE_WORK'):
            self.run_audit()
    def test_quarantine_count_mismatch_rejected(self):
        self.stage['quarantine']=1
        self.log.write_text(a.MARKER+json.dumps(self.stage)+'\n')
        with self.assertRaisesRegex(a.EvidenceError,'DAILY_METADATA_DISAGREES_WITH_STAGE'):
            self.run_audit()
    def test_quarantine_symbol_rejected(self):
        self.q['SECRET_KEY']='bad';self.meta['expected_stock_days']=5209;self.stage['quarantine']=3;self.log.write_text(a.MARKER+json.dumps(self.stage)+'\n');self.save_meta()
        with self.assertRaisesRegex(a.EvidenceError,'BAD_QUARANTINED_SYMBOL'):
            self.run_audit()
    def test_duplicate_same_day_stage_rejected(self):
        text=self.log.read_text();self.log.write_text(text*2)
        with self.assertRaisesRegex(a.EvidenceError,'STAGED_TARGET_DATE_COUNT_2'):
            self.run_audit()
    def test_no_staged_day_rejected(self):
        self.log.write_text('no stage entry')
        with self.assertRaisesRegex(a.EvidenceError,'STAGED_TARGET_DATE_COUNT_0'):
            self.run_audit()
    def test_bad_meta_sha_rejected(self):
        self.meta['sha256']='f'*64;self.save_meta()
        with self.assertRaisesRegex(a.EvidenceError,'DAILY_METADATA_DISAGREES_WITH_STAGE'):
            self.run_audit()
    def test_historical_receipt_bad_date_rejected(self):
        with self.assertRaisesRegex(a.EvidenceError,'WRONG_SCHEDULED_RUN'):
            a.audit(self.root,'2026-11-24',self.run_sha)
    def test_bad_stage_counts_rejected(self):
        self.stage['rows']=240;self.log.write_text(a.MARKER+json.dumps(self.stage)+'\n')
        with self.assertRaisesRegex(a.EvidenceError,'STAGED_FIELDS_INVALID'):
            self.run_audit()
    def test_optional_missing_parquet_not_silent(self):
        self.parquet.unlink()
        with self.assertRaisesRegex(a.EvidenceError,'PARQUET_MISSING_OR_LINKED'):
            self.run_audit(verify=True)

if __name__ == '__main__':
    unittest.main()
