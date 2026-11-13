"""Offline full-market eltdx/QMT 1m audit contracts; no network or market writes."""
from datetime import date,datetime
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location("qmt_eltdx_market_audit",HERE/"qmt_eltdx_market_audit.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def sample(day=date(2026,10,14),qt=True):
    source=[]
    for i,(h,m) in enumerate(sorted(M.P.GRID)):
        if not qt and (h,m)==(9,30):continue
        stamp=int(datetime(day.year,day.month,day.day,h,m,tzinfo=M.P.CN).timestamp()*1000)
        price=10.+((i*37)%53)*.05
        source.append({"ts":stamp,"symbol":"SH600000","open":price,
            "high":price+.02,"low":price-.01,"close":price+.01,
            "volume":100.+(i*37)%170,"amount":10000.+i*73})
    return source


def put_receipt(folder,code="600000.SH",qmt_sha="oldsha",plan=None):
    rows=sample(qt=False)
    evidence=M.X.save_private(folder,code,rows,{"qmt_sha256":qmt_sha,
        "plan_sha256":plan,"endpoint":"fake",
        "dense_days":1},M.make_comparison(sample(),rows,[date(2026,10,14)]))
    return evidence


class Tests(unittest.TestCase):
    def test_score_day_minute_diagnostics_are_explicit(self):
        q,t=sample(),sample(qt=False)
        day=date(2026,10,14)
        result=M.make_comparison(q,t,[day])[str(day)]
        self.assertEqual(result["result"]["status"],"MATCHED_1MIN_OHLCVA")
        self.assertEqual(result["minute_diagnostics"]["compared_minutes"],240)
        self.assertEqual(result["minute_diagnostics"]["unmatched_qmt_minutes"],1)
        self.assertEqual(result["minute_diagnostics"]["field_mismatch_counts"]["amount_raw"],0)
        self.assertEqual(result["minute_diagnostics"]["field_mismatch_counts"]["high"],0)

    def test_minute_mismatch_sample_and_counts(self):
        q,t=sample(),sample(qt=False)
        t[70]["close"]+=2.
        t[71]["amount"]*=2
        day=str(date(2026,10,14))
        proof=M.make_comparison(q,t,[date(2026,10,14)])[day]["minute_diagnostics"]
        self.assertEqual(proof["field_mismatch_counts"]["close"],1)
        self.assertEqual(proof["field_mismatch_counts"]["amount_raw"],1)
        self.assertEqual(len(proof["examples"]),2)

    def test_nonmatching_or_missing_qmt_day_never_certified(self):
        days=[date(2026,10,14),date(2026,10,15)]
        evidence=M.make_comparison([],sample(qt=False),days)
        self.assertEqual(evidence["2026-10-14"]["result"]["status"],"NO_MINUTE_TIME_OVERLAP")
        self.assertEqual(evidence["2026-10-15"]["result"]["status"],"NO_MINUTE_TIME_OVERLAP")
        fake={"day_comparison":evidence}
        summary=M.result_from_receipt(fake,days,"QMT_NO_SOURCE")
        self.assertEqual(summary["strict_matched_days"],0)
        self.assertEqual(summary["qmt_available_days"],0)

    def test_cache_requires_sha_schema_and_original_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            put_receipt(root,plan="sameplan")
            good=M.read_existing(root,"600000.SH","sameplan","oldsha",[date(2026,10,14)])
            self.assertIsNotNone(good)
            with self.assertRaisesRegex(ValueError,"plan changed"):
                M.read_existing(root,"600000.SH","DIFFERENT","oldsha",[date(2026,10,14)])
            with self.assertRaisesRegex(ValueError,"QMT private SHA changed"):
                M.read_existing(root,"600000.SH","sameplan","other",[date(2026,10,14)])
            with (root/"source_parquet"/"600000_SH.parquet").open("ab") as file:
                file.write(b"CORRUPTED")
            with self.assertRaisesRegex(ValueError,"receipt/SHA/guard"):
                M.read_existing(root,"600000.SH","sameplan","oldsha",[date(2026,10,14)])

    def test_existing_pilot_three_anchors_reused_but_no_other_unpinned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            put_receipt(root,plan=None)
            doc=M.read_existing(root,"600000.SH","current","oldsha",[date(2026,10,14)])
            self.assertEqual(doc["rows"],240)
            # A newly acquired non-anchor result MUST include plan SHA.
            with (root/"receipts"/"600000_SH.json").open("r") as f:
                old=json.load(f)
            old["stock"]="600123.SH"
            import shutil
            shutil.copy2(root/"source_parquet"/"600000_SH.parquet",
                         root/"source_parquet"/"600123_SH.parquet")
            (root/"receipts"/"600123_SH.json").write_text(json.dumps(old))
            with self.assertRaisesRegex(ValueError,"Unpinned"):
                M.read_existing(root,"600123.SH","current","oldsha",[date(2026,10,14)])

    def test_one_stock_live_synthetic_in_all_market_plan(self):
        date_one=date(2026,10,14)
        # Full-source audit hard gate requires 2500 QMT stocks; mocked
        # evidence avoids creating any actual purchased or QMT files.
        stocks=["600000.SH"]+[f"{i:06d}.SH" for i in range(1,2501)]
        originals={code:{"sha256":"fake"} for code in stocks}
        daymap={date_one:{code:{"open":10.,"high":10.02,"low":9.99,"close":10.01} for code in stocks}}
        plan={"calibration_sha256":"fake-purchased-sha"}
        class Client:
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            with patch.object(M.P,"BASE",folder),\
                 patch.object(M.R,"load_bound_context",return_value=(daymap,stocks,plan,{})),\
                 patch.object(M.R,"validate_original",return_value=originals),\
                 patch.object(M.D,"source_original",
                              return_value=({"sha256":"QMTsha"},sample(),"QMTsha")),\
                 patch.object(M.X,"connect_host",return_value=Client()),\
                 patch.object(M.X,"fetch_history",
                              return_value=(sample(qt=False),{"dense_days":1,
                                  "complete_22_day_window":False,
                                  "complete_minute_days":1})):
                result=M.audit(folder,limit=1,workspace=folder/"private_market",
                               pause=0,log=lambda x:None)
            self.assertEqual(result["processed_stocks"],1)
            self.assertEqual(result["source_stocks_staged"],1)
            self.assertEqual(result["matched_stock_days"],1)
            self.assertEqual(result["raw_one_minute_pairs_compared"],240)
            self.assertTrue(result["stopped_early"])
            self.assertFalse(result["market_files_modified"])
            self.assertFalse(result["production_merge_authorized"])
            self.assertTrue((folder/"private_market"/"receipts"/"600000_SH.json").is_file())

    def test_network_failure_is_quarantined_not_false_source_agreement(self):
        # Source host errors are captured; three consecutive failures alone
        # do not take down the entire QMT private dataset.
        date_one=date(2026,10,14)
        stocks=["600000.SH"]+[f"{i:06d}.SH" for i in range(1,2501)]
        originals={code:{"sha256":"fake"} for code in stocks}
        daymap={date_one:{code:{"open":10.} for code in stocks}}
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            with patch.object(M.P,"BASE",folder),\
                 patch.object(M.R,"load_bound_context",return_value=(daymap,stocks,{"calibration_sha256":"x"},{})),\
                 patch.object(M.R,"validate_original",return_value=originals),\
                 patch.object(M.D,"source_original",
                              return_value=({"sha256":"QMTsha"},sample(),"QMTsha")),\
                 patch.object(M.X,"connect_host",side_effect=TimeoutError("unavailable")):
                report=M.audit(folder,limit=3,workspace=folder/"failed",
                                pause=0,max_hosts=1,log=lambda x:None)
            self.assertEqual(report["failed_stock_attempts"],3)
            self.assertEqual(report["matched_stock_days"],0)
            self.assertEqual(report["source_stocks_staged"],0)


if __name__=="__main__":
    unittest.main()
