"""Offline, provider-neutral regression for durable A-share quality rules."""
from __future__ import annotations
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import market_quality_engine as M


def case(day="2025-06-18", symbol="SZ000001", period="1min",
         source_id="qmt-primary"):
    return {
        "format":M.FORMAT, "trading_day":day,
        "symbol":symbol,"period":period,"source_id":source_id,
        "source_state":"READY","official_stock_day":True,
        "observed_bars":241,"expected_bars":241,
        "grid_complete":True,"raw_source_sha256":"a"*64,
        "official_reference_sha256":"b"*64,
        "calibration_verified":True,"receipt_integrity_valid":True,
        "cross_period_consistent":True,"source_conflict":False,
        "zero_prefix_bars":0,"zero_prefix_verified":True,
        "volume_amount_pair_valid":True,
        "fields_within_tolerance":{k:True for k in M.FIELD_SET},
    }


def rules(x, *, status=None):
    return {f["rule_id"] for f in x["findings"]
            if status is None or f["status"]==status}


class GeneralQualityRulesTests(unittest.TestCase):
    def test_regular_complete_stockday_is_unverified_not_automatic_production_pass(self):
        report=M.analyze_case(case())
        self.assertEqual(report["quality_state"],"UNVERIFIED")
        self.assertEqual(report["findings"],[])
        self.assertFalse(report["production_admission_authorized"])
        self.assertFalse(report["market_parquet_or_h5_write_authorized"])
        self.assertFalse(report["qmt_cache_write_authorized"])

    def test_completely_different_period_symbol_and_date_are_supported(self):
        for d,s,p,n in [("2018-03-26","SH600000","5min",48),
                        ("2025-02-12","BJ920021","day",1),
                        ("2026-01-05","SZ300888","60min",4),
                        ("2024-12-31","SH688621","month",1)]:
            with self.subTest(d=d,p=p):
                obs=case(d,s,p);obs["observed_bars"]=obs["expected_bars"]=n
                r=M.analyze_case(obs)
                self.assertEqual(r["scope"]["trading_day"],d)
                self.assertEqual(r["scope"]["symbol"],s)
                self.assertEqual(r["quality_state"],"UNVERIFIED")

    def test_eight_periods_are_explicitly_configured(self):
        self.assertEqual(M.PERIODS,{"1min","5min","15min","30min","60min",
                                     "day","week","month"})

    def test_missing_stockday_requires_independent_official_universe(self):
        o=case("2025-08-13","SH601318");o["observed_bars"]=0
        self.assertIn("MISSING_STOCK_DAY",rules(M.analyze_case(o),status="DETECTED"))
        o["official_stock_day"]=None
        r=M.analyze_case(o)
        self.assertNotIn("MISSING_STOCK_DAY",rules(r,status="DETECTED"))
        self.assertIn("OFFICIAL_DAY_EVIDENCE_MISSING",rules(r))

    def test_provider_unavailable_not_invented_as_stock_no_trades(self):
        o=case();o.update(observed_bars=0,source_state="UNAVAILABLE")
        r=M.analyze_case(o)
        self.assertIn("SOURCE_UNAVAILABLE",rules(r,status="DETECTED"))
        self.assertIn("MISSING_STOCK_DAY",rules(r,status="INSUFFICIENT_EVIDENCE"))
        self.assertNotIn("MISSING_STOCK_DAY",rules(r,status="DETECTED"))

    def test_cache_unknown_state_explicitly_unverified(self):
        o=case();o["source_state"]="UNKNOWN"
        self.assertIn("SOURCE_UNAVAILABLE",
                      rules(M.analyze_case(o),status="INSUFFICIENT_EVIDENCE"))

    def test_missing_native_minute_grid_and_other_mismatch_reported_together(self):
        o=case("2024-05-16","SH600036")
        o["observed_bars"]=239
        o["fields_within_tolerance"]["open"]=False
        r=M.analyze_case(o)
        self.assertIn("INCOMPLETE_TIME_GRID",r["detected_rules"])
        self.assertIn("OHLCVA_MISMATCH",r["detected_rules"])
        self.assertEqual(r["quality_state"],"QUARANTINED")

    def test_time_grid_failure_even_with_matching_rowcount(self):
        o=case();o["grid_complete"]=False
        self.assertIn("INCOMPLETE_TIME_GRID",
                      rules(M.analyze_case(o),status="DETECTED"))

    def test_missing_grid_verification_cannot_imply_grid_pass(self):
        o=case();o["grid_complete"]=None
        self.assertIn("INCOMPLETE_TIME_GRID",
                      rules(M.analyze_case(o),status="INSUFFICIENT_EVIDENCE"))

    def test_six_field_verifier_does_not_stop_at_open_failure(self):
        o=case();o["fields_within_tolerance"].update(open=False,high=False,amount=False)
        r=M.analyze_case(o)
        msg=next(x["detail"] for x in r["findings"]
                 if x["rule_id"]=="OHLCVA_MISMATCH")
        self.assertIn("AMOUNT",msg)
        self.assertIn("HIGH",msg)
        self.assertIn("OPEN",msg)

    def test_partial_ohlcva_comparison_is_unverified_not_success(self):
        o=case();o["fields_within_tolerance"]={"open":True}
        self.assertIn("OHLCVA_MISMATCH",
                      rules(M.analyze_case(o),status="INSUFFICIENT_EVIDENCE"))

    def test_zero_volume_amount_quotebars_are_preserved_not_fabricated(self):
        o=case("2023-01-10","SH600293")
        o["zero_prefix_bars"]=3
        r=M.analyze_case(o)
        self.assertIn("ZERO_TRADE_REFERENCE",rules(r,status="DETECTED"))
        self.assertIn("preserve_reference_quote_without_fabricating_trades",
                      r["suggested_readonly_actions"])
        self.assertFalse(r["automatic_repair_authorized"])

    def test_unproven_zero_quote_is_not_certified(self):
        o=case();o["zero_prefix_bars"]=1;o["zero_prefix_verified"]=False
        self.assertIn("ZERO_TRADE_REFERENCE",
                      rules(M.analyze_case(o),status="INSUFFICIENT_EVIDENCE"))

    def test_first_real_trade_candidate_for_any_day_any_symbol(self):
        for d,s,a,b in [("2022-09-22","SZ300462",9.40,9.59),
                        ("2026-11-25","SH605336",7.62,7.69)]:
            o=case(d,s)
            o.update(zero_prefix_bars=2,zero_prefix_verified=True,
                     quoted_open=b,first_traded_open=a,official_open=a,
                     traded_hlc_verified=True,tail_hlc_verified=True)
            o["fields_within_tolerance"]["open"]=False
            r=M.analyze_case(o)
            self.assertIn("PRE_TRADE_QUOTE_OPEN",rules(r,status="DETECTED"))
            self.assertFalse(r["production_admission_authorized"])
            self.assertEqual(r["quality_state"],"QUARANTINED")

    def test_same_first_trade_open_without_verified_hlc_remains_unverified(self):
        o=case();o.update(zero_prefix_bars=2,quoted_open=9.59,
                            first_traded_open=9.4,official_open=9.4,
                            traded_hlc_verified=None,tail_hlc_verified=True)
        self.assertIn("PRE_TRADE_QUOTE_OPEN",
                      rules(M.analyze_case(o),status="INSUFFICIENT_EVIDENCE"))

    def test_first_trade_not_matching_official_cannot_be_promoted(self):
        o=case();o.update(zero_prefix_bars=1,quoted_open=9.59,
                            first_traded_open=9.5,official_open=9.4,
                            traded_hlc_verified=True,tail_hlc_verified=True)
        self.assertNotIn("PRE_TRADE_QUOTE_OPEN",
                         rules(M.analyze_case(o),status="DETECTED"))

    def test_calibration_missing_does_not_prove_actual_drift(self):
        o=case();o["calibration_verified"]=False
        r=M.analyze_case(o)
        self.assertIn("UNIT_OR_CALIBRATION_DRIFT",
                      rules(r,status="INSUFFICIENT_EVIDENCE"))
        self.assertNotIn("UNIT_OR_CALIBRATION_DRIFT",rules(r,status="DETECTED"))

    def test_independent_calibration_conflict_detected(self):
        o=case();o["calibration_drift_confirmed"]=True
        self.assertIn("UNIT_OR_CALIBRATION_DRIFT",
                      rules(M.analyze_case(o),status="DETECTED"))

    def test_receipt_invalid_blocks_market_admission(self):
        o=case();o["receipt_integrity_valid"]=False
        r=M.analyze_case(o)
        self.assertIn("STORAGE_OR_RECEIPT_INTEGRITY",r["detected_rules"])
        self.assertIn("stop_writes_audit_immutable_source_and_rollback",
                      r["suggested_readonly_actions"])
        self.assertFalse(r["market_parquet_or_h5_write_authorized"])

    def test_provider_conflict_and_cross_period_drift_both_detected(self):
        o=case();o.update(source_conflict=True,cross_period_consistent=False)
        rules_found=M.analyze_case(o)["detected_rules"]
        self.assertIn("SOURCE_CONFLICT",rules_found)
        self.assertIn("CROSS_PERIOD_INCONSISTENCY",rules_found)

    def test_volume_amount_pair_violation_quarantined(self):
        o=case();o["volume_amount_pair_valid"]=False
        self.assertIn("INVALID_VOLUME_AMOUNT_PAIR",
                      rules(M.analyze_case(o),status="DETECTED"))

    def test_no_raw_byte_hash_cannot_claim_authenticated_source(self):
        o=case();o["raw_source_sha256"]=None
        r=M.analyze_case(o)
        self.assertIn("SOURCE_PROVENANCE_UNVERIFIED",
                      rules(r,status="INSUFFICIENT_EVIDENCE"))
        self.assertIn("NOT_PROVIDER_RAW_BYTES",r["digest_scope"])

    def test_batch_sort_is_deterministic_across_sources_periods_days(self):
        a=case("2025-01-03","SZ000001","day",source_id="tdx-official")
        b=case("2019-11-07","BJ920001","5min",source_id="paid-v2")
        x=M.analyze_batch([a,b]);y=M.analyze_batch([b,a])
        self.assertEqual(x,y)
        self.assertEqual(x["case_count"],2)
        self.assertFalse(x["production_admission_authorized"])

    def test_duplicate_source_day_period_symbol_rejected(self):
        a=case()
        with self.assertRaisesRegex(M.QualityPolicyError,"DUPLICATE"):
            M.analyze_batch([a,deepcopy(a)])

    def test_distinct_source_snapshots_same_date_can_coexist(self):
        a=case();b=deepcopy(a);b["raw_source_sha256"]="f"*64
        self.assertEqual(M.analyze_batch([a,b])["case_count"],2)

    def test_invalid_days_symbols_periods_and_bools_fail_closed(self):
        for key,v in [("trading_day","2026-02-29"),("trading_day","2026-1-1"),
                      ("symbol","SZ123"),("symbol","../../etc"),
                      ("period","1hour"),("source_id","../../file"),
                      ("observed_bars",True),("grid_complete","PASS"),
                      ("official_stock_day",1),
                      ("raw_source_sha256","1ab"),
                      ("fields_within_tolerance",{"open":1})]:
            with self.subTest(key=key,v=v):
                o=case();o[key]=v
                with self.assertRaises(M.QualityPolicyError):
                    M.analyze_case(o)

    def test_nonfinite_float_in_reference_fails_closed(self):
        o=case();o["official_open"]=math.inf
        with self.assertRaisesRegex(M.QualityPolicyError,"NONPOSITIVE_OR_NONFINITE"):
            M.analyze_case(o)

    def test_input_evidence_sha_stable_across_object_key_order(self):
        o=case()
        backwards=dict(reversed(list(o.items())))
        self.assertEqual(M.analyze_case(o)["input_evidence_json_sha256"],
                         M.analyze_case(backwards)["input_evidence_json_sha256"])

    def test_invalid_collection_sizes_fail_closed(self):
        for v in ([],{},[case()]*(M.MAX_CASES+1)):
            with self.subTest(length=len(v)):
                with self.assertRaises(M.QualityPolicyError):
                    M.analyze_batch(v)

    def test_cli_on_temporary_evidence_file_never_creates_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/"input.json"
            file.write_text(json.dumps([case(),case("2020-12-31","SH600016")]),
                            encoding="utf-8")
            unchanged=file.read_bytes()
            buf=StringIO()
            with redirect_stdout(buf):
                code=M.main(["--evidence-json",str(file)])
            self.assertEqual(code,0)
            self.assertEqual(json.loads(buf.getvalue())["case_count"],2)
            self.assertEqual(file.read_bytes(),unchanged)
            self.assertEqual({x.name for x in Path(tmp).iterdir()},{"input.json"})

    def test_cli_invalid_evidence_fails_without_creating_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/"input.json";file.write_text('{"invalid":true}')
            before=file.read_bytes()
            buf=StringIO()
            with redirect_stdout(buf):
                code=M.main(["--evidence-json",str(file)])
            self.assertEqual(code,3)
            self.assertIn("REVIEW_REQUIRED",buf.getvalue())
            self.assertEqual(file.read_bytes(),before)
            self.assertEqual(len(list(Path(tmp).iterdir())),1)


if __name__=="__main__":unittest.main()
