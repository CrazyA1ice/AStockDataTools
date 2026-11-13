"""Source-only forensic audit tests: no network, no purchased market writes."""
from datetime import date,datetime
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location("qmt_eltdx_forensics",HERE/"qmt_eltdx_forensics.py")
F=importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)


class ForensicTests(unittest.TestCase):
    def test_reason_types_are_diagnostic_and_not_exclusive(self):
        score={"status":"MINUTE_SOURCE_DIFFERENCE_REVIEW",
               "offset_ambiguous":True,"ohlc_all_fields_fit":.92,
               "amount_minute_raw_fit":.7,
               "volume_factor":{"status":"NO_UNIQUE_STABLE_VENDOR_FACTOR",
                                "matching_fraction":.5},
               "amount_factor":{"status":"NO_UNIQUE_STABLE_VENDOR_FACTOR",
                                "matching_fraction":.6},
               "qmt_count":241,"tdx_count":240}
        reasons=F.review_reason(score)
        self.assertIn("TIME_OFFSET_AMBIGUOUS",reasons)
        self.assertIn("OHLC_FIT_BELOW_GATE",reasons)
        self.assertIn("RAW_MINUTE_AMOUNT_BELOW_GATE",reasons)
        self.assertIn("VOLUME_FACTOR_BELOW_GATE",reasons)
        self.assertIn("AMOUNT_FACTOR_AMBIGUOUS",reasons)

    def test_incomplete_240_bars_never_confused_with_241_qmt(self):
        reference={"open":10,"high":10.2,"low":9.9,"close":10.1}
        frames=[{"open":10,"high":10.2,"low":9.9,"close":10.1}]*240
        ok=F.independently_compare_tdx_day_to_official(frames,reference)
        self.assertTrue(ok["all_four_fit"])
        self.assertTrue(ok["auction_0930_not_reconstructed"])
        short=F.independently_compare_tdx_day_to_official(frames[:239],reference)
        self.assertEqual(short["status"],"TDX_DAY_NOT_240_BARS")

    def test_gap_receipt_sha_and_day_ohlc_only_for_official_source(self):
        code="600000.SH"
        day=date(2026,10,14)
        when=[datetime(day.year,day.month,day.day,h,m,tzinfo=F.P.CN)
              for h,m in sorted(F.P.GRID) if (h,m)!=(9,30)]
        source=[{"ts":int(x.timestamp()*1000),"symbol":"SH600000",
                 "open":10.,"high":10.2,"low":9.9,"close":10.1,
                 "volume":100.,"amount":10000.} for x in when]
        plan={"format":"test","calibration_sha256":"sha"}
        fingerprint=F.P.sha_bytes(F.P.canonical(plan))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"private"
            path.mkdir()
            proof={"2026-10-14":{"result":{
                "status":"NO_MINUTE_TIME_OVERLAP","qmt_count":0,
                "tdx_count":240,"compared":0}}}
            F.X.save_private(path,code,source,{"plan_sha256":fingerprint,
                     "qmt_sha256":"qmt-sha"},proof)
            official={day:{code:{"open":10.,"high":10.2,"low":9.9,"close":10.1}}}
            report={"format":F.M.FORMAT,"plan_sha256":fingerprint,
                    "expected_stocks":1,"market_files_modified":False,
                    "production_merge_authorized":False}
            F.P.safe_save(path/"latest_market_report.json",F.P.canonical(report))
            with patch.object(F.P,"BASE",Path(tmp)),\
                 patch.object(F.R,"load_bound_context",
                    return_value=(official,[code],plan,{})):
                result=F.inspect(Path(tmp),workspace=path,logger=lambda _:None)
            self.assertEqual(result["qmt_no_overlap_stock_days_with_eltdx"],1)
            self.assertEqual(result["tdx_gap_days_all_four_official_day_ohlc_fit"],1)
            self.assertFalse(result["production_merge_authorized"])
            self.assertTrue((path/"latest_forensics_report.json").exists())
            (path/"source_parquet"/"600000_SH.parquet").open("ab").write(b"ALTERED")
            with patch.object(F.P,"BASE",Path(tmp)),\
                 patch.object(F.R,"load_bound_context",
                     return_value=(official,[code],plan,{})):
                with self.assertRaisesRegex(ValueError,"Changed private minute source"):
                    F.inspect(Path(tmp),workspace=path,logger=lambda _:None)

    def test_missing_eltdx_receipt_reports_official_first_trade_date(self):
        code="688827.SH"
        day=date(2026,11,10)
        plan={"calibration_sha256":"sha"}
        stamp=F.P.sha_bytes(F.P.canonical(plan))
        official={day:{code:{"open":10,"high":10,"low":10,"close":10}}}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"private"
            path.mkdir()
            F.P.safe_save(path/"latest_market_report.json",F.P.canonical({
                "format":F.M.FORMAT,"plan_sha256":stamp,
                "expected_stocks":1,"market_files_modified":False,
                "production_merge_authorized":False}))
            with patch.object(F.P,"BASE",Path(tmp)),\
                 patch.object(F.R,"load_bound_context",
                     return_value=(official,[code],plan,{})):
                result=F.inspect(Path(tmp),workspace=path,logger=lambda _:None)
        self.assertEqual(result["source_not_available_stocks"],1)
        self.assertEqual(result["source_failure_first_trading_dates"][code]["first_certified_trading_day"],
                         "2026-11-10")
        self.assertEqual(result["source_not_available_stock_days"],1)


if __name__=="__main__":
    unittest.main()
