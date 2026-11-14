"""Unit tests for no-redownload recovery SHA gate before full-market eltdx."""
from datetime import date
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location("qmt_recovery_receipt_preflight",HERE/"qmt_recovery_receipt_preflight.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def fake_sources():
    a,b=date(2026,10,14),date(2026,10,15)
    expected={a:{"600000.SH":{},"000404.SZ":{}},
              b:{"600000.SH":{},"000404.SZ":{}}}
    stocks=["600000.SH","000404.SZ"]
    plan={"calibration_sha256":"synthetic-pin"}
    originals={"600000.SH":{"traded_days":[str(a),str(b)]}}
    receipt={"approved_days":[str(a)],"quarantined_days":{str(b):{"reason":"OHLC"}}}
    return expected,stocks,plan,originals,receipt


class ReuseTests(unittest.TestCase):
    def test_full_recovery_sha_checked_without_xtquant_or_redownload(self):
        expected,stocks,plan,originals,receipt=fake_sources()
        outputs=[]
        with tempfile.TemporaryDirectory() as tmp,\
             patch.object(M.P,"BASE",Path(tmp)),\
             patch.object(M.R,"load_bound_context",return_value=(expected,stocks,plan,{})),\
             patch.object(M.R,"validate_original",return_value=originals),\
             patch.object(M.R,"validate_recovery_receipt",return_value=receipt) as valid:
            result=M.verify(Path(tmp),logger=outputs.append)
        self.assertEqual(result["original_full_stock_receipts_verified"],1)
        self.assertEqual(result["recovery_receipts_sha_verified"],1)
        self.assertEqual(result["accepted_stock_day_keys"],3)
        self.assertEqual(result["remaining_stock_day_gaps"],1)
        self.assertTrue(result["all_recovery_receipts_present"])
        self.assertEqual(valid.call_count,1)
        self.assertTrue(any("QMT_RECOVERY_SHA_REUSE_SUMMARY=" in x for x in outputs))

    def test_missing_receipt_prevents_full_market_transition(self):
        expected,stocks,plan,originals,receipt=fake_sources()
        with tempfile.TemporaryDirectory() as tmp,\
             patch.object(M.P,"BASE",Path(tmp)),\
             patch.object(M.R,"load_bound_context",return_value=(expected,stocks,plan,{})),\
             patch.object(M.R,"validate_original",return_value=originals),\
             patch.object(M.R,"validate_recovery_receipt",return_value=None):
            with self.assertRaisesRegex(ValueError,"Cannot skip QMT recovery"):
                M.verify(Path(tmp),logger=lambda _:None)

    def test_source_sha_failure_aborts_before_eltdx(self):
        expected,stocks,plan,originals,receipt=fake_sources()
        with tempfile.TemporaryDirectory() as tmp,\
             patch.object(M.P,"BASE",Path(tmp)),\
             patch.object(M.R,"load_bound_context",return_value=(expected,stocks,plan,{})),\
             patch.object(M.R,"validate_original",return_value=originals),\
             patch.object(M.R,"validate_recovery_receipt",side_effect=ValueError("SHA invalid")):
            with self.assertRaisesRegex(ValueError,"SHA invalid"):
                M.verify(Path(tmp),logger=lambda _:None)


if __name__=="__main__":
    unittest.main()
