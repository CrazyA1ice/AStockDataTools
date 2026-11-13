"""Synthetic offline unit tests for SHA-bound targeted source amount triage."""
from datetime import date,datetime
import importlib.util
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location(
    "qmt_eltdx_targeted_triage",HERE/"qmt_eltdx_targeted_triage.py")
T=importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)


def stock_rows():
    q=[]
    for h,m in sorted(T.P.GRID):
        dt=datetime(2026,10,14,h,m,tzinfo=T.P.CN)
        ts=int(dt.timestamp()*1000)
        value=10.+((m*13+h*7)%27)*.01
        q.append({"ts":ts,"symbol":"SH600000",
                  "open":value,"high":value+.02,
                  "low":value-.01,"close":value+.01,
                  "amount":2000.+m*33+h*25,
                  "volume":100.+m+h})
    t=[dict(x) for x in q if
       datetime.fromtimestamp(x["ts"]/1000,T.P.CN).strftime("%H:%M")!="09:30"]
    return q,t


def score(n=240):
    return {"status":"MINUTE_SOURCE_DIFFERENCE_REVIEW",
            "tdx_to_qmt_time_offset_ms":0,"offset_ambiguous":False,
            "compared":n,"ohlc_all_fields_fit":1.,
            "amount_minute_raw_fit":.5}


class Tests(unittest.TestCase):
    def test_boundary_only_amount_is_separate_from_core(self):
        q,t=stock_rows()
        t[0]["amount"]*=2
        t[-1]["amount"]*=2
        result=T.diagnostic(q,t,score())
        self.assertEqual(result["triage"],"SESSION_BOUNDARY_AMOUNT_ONLY")
        self.assertEqual(result["raw_amount_bad_minutes"],2)
        self.assertEqual(result["session_core_amount_bad_minutes"],0)
        self.assertEqual(result["aligned_minutes"],240)
        self.assertFalse(result["merge_calibration_authorized"])

    def test_all_day_stable_ratio_is_research_candidate_not_approval(self):
        q,t=stock_rows()
        for bar in t:
            bar["amount"]*=100
        result=T.diagnostic(q,t,score())
        self.assertEqual(result["triage"],"PERSISTENT_AMOUNT_RATIO_CANDIDATE")
        evidence=result["amount_factor_research_only"]
        self.assertEqual(evidence["candidate_factor_tdx_to_qmt"],.01)
        self.assertFalse(evidence["merge_calibration_authorized"])
        self.assertGreater(result["session_core_amount_bad_minutes"],200)

    def test_price_conflict_is_never_downgraded_to_unit_repair(self):
        q,t=stock_rows()
        for bar in t:
            bar["amount"]*=100
        t[31]["close"]+=2
        result=T.diagnostic(q,t,score())
        self.assertEqual(result["triage"],"PRICE_AND_OR_AMOUNT_DISAGREEMENT")
        self.assertEqual(result["ohlc_bad_minutes"],1)
        self.assertFalse(result["merge_calibration_authorized"])

    def test_ambiguous_time_offset_never_generates_alignment(self):
        q,t=stock_rows()
        result=T.diagnostic(q,t,{**score(),"offset_ambiguous":True})
        self.assertEqual(result["triage"],"TIME_GRID_UNPROVEN")
        self.assertEqual(result["aligned_minutes"],0)
        with self.assertRaisesRegex(ValueError,"Source SHA"):
            T.diagnostic(q,t,score(n=99))

    def test_offline_end_to_end_one_sha_pinned_discrepancy_case(self):
        day=date(2026,10,14)
        code="600000.SH"
        plan={"calibration_sha256":"synthetic-calibration-pin"}
        plan_sha=T.P.sha_bytes(T.P.canonical(plan))
        q,t=stock_rows()
        t[12]["amount"]*=2
        stored={**score(),"amount_factor":{"pairs":220,"matching_fraction":.5},
                "volume_factor":{"pairs":220,"matching_fraction":1.}}
        case_class=T.F.categorize_review(stored)
        with tempfile.TemporaryDirectory() as tmp:
            private=Path(tmp)/"private"
            private.mkdir()
            item={"stock":code,"day":day.isoformat(),
                  "review_class":case_class,"production_merge_authorized":False}
            T.P.safe_save(private/"latest_review_queue.private.json",
                T.P.canonical({"format":T.F.FORMAT,"plan_sha256":plan_sha,
                    "cases":[item],"production_merge_authorized":False,
                    "market_files_modified":False}))
            T.P.safe_save(private/"latest_forensics_report.json",
                T.P.canonical({"review_exclusive_day_classes":{case_class:1}}))
            evidence={day.isoformat():{"result":stored,
                         "minute_diagnostics":{"field_mismatch_counts":{
                             "amount_raw":1}}}}
            T.X.save_private(private,code,t,{"plan_sha256":plan_sha,
                "qmt_sha256":"synthetic-QMT-SHA"},evidence)
            official={day:{code:{"open":10.}}}
            with patch.object(T.P,"BASE",Path(tmp)),\
                 patch.object(T.R,"load_bound_context",
                    return_value=(official,[code],plan,{})),\
                 patch.object(T.R,"validate_original",
                    return_value={code:{"traded_days":[str(day)]}}),\
                 patch.object(T.D,"source_original",
                    return_value=({"sha256":"synthetic-QMT-SHA"},q,
                                  "synthetic-QMT-SHA")):
                result=T.inspect(Path(tmp),workspace=private,logger=lambda _:None)
            self.assertEqual(result["targeted_review_days"],1)
            self.assertEqual(result["raw_amount_bad_minutes"],1)
            self.assertEqual(result["diagnostic_classes"]["INTRADAY_AMOUNT_DIFF_UNEXPLAINED"],1)
            out=json.loads((private/"latest_targeted_triage.private.json").read_bytes())
            self.assertFalse(out["summary"]["production_merge_authorized"])
            self.assertEqual(len(out["cases"]),1)

    def test_insufficient_positive_minutes_cannot_infer_amount_factor(self):
        q,t=stock_rows()
        pairs=[(q[1],t[0])]*10
        proof=T.positive_ratio_evidence(pairs)
        self.assertEqual(proof["status"],"INSUFFICIENT_POSITIVE_MINUTES")
        self.assertIsNone(proof.get("candidate_factor_tdx_to_qmt"))
        self.assertFalse(proof["merge_calibration_authorized"])


if __name__=="__main__":
    unittest.main()
