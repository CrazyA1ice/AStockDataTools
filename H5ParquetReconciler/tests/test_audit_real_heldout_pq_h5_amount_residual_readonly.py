"""Only fictional Parquet/H5 fixture and SAFE; never genuine market sources."""
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,file)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T=load("test_candidate_heldout_amount_residual",
       HERE.parent/"tools"/"audit-real-heldout-pq-h5-amount-residual-readonly.py")
FIX=load("test_candidate_previously_heldout_synthetic",
         HERE/"test_probe_real_h5_parquet_heldout_day_factors_readonly.py")


def pairs(day="2026-09-28",offsets=(0.001,-0.001)):
    parquet={}
    h5={}
    for sym,raw,offset in zip(T.PAIR.SYMBOLS,(100000,200000),offsets):
        row={k:1. for k in T.PAIR.FIELDS}
        row["amount"]=float((raw+offset)*1000)
        original={k:1000 for k in T.PAIR.RAW}
        original["datetime"]=int(day.replace("-","")+"0000")
        original["transAmount"]=raw
        original["transCount"]=1000
        parquet[sym]=row
        h5[sym]=original
    return parquet,h5


def discovery_document():
    counts={
        "sample_positive_pairs":2,
        "would_require_decimal_rounding":2,
        "candidate_exact_original_h5_integer_count":0,
        "nearest_half_even_matches_original_count":2,
        "floor_matches_original_count":0,
        "ceiling_matches_original_count":2,
        "within_previous_relative_tolerance_count":2,
        "candidate_above_original_count":0,
        "candidate_below_original_count":2,
        "absolute_integer_candidate_residual_buckets":{
            name:(2 if name=="le_0p1" else 0) for name in T.AMOUNT.ABS_BUCKETS},
    }
    return {
        "format":T.AMOUNT.FORMAT,
        "trading_day":"2026-09-30",
        "h5_target_day_records_read":2,
        "amount_native_integer_candidate_is_purchased_amount_divided_by":"1000",
        "amount_residual_counts":counts,
        "source_file_stat_unchanged":True,
        "prior_exactness_counts_reverified":True,
        "no_source_values_raw_integers_symbols_or_absolute_paths_exported":True,
        "hypothetical_rounding_is_not_an_approved_policy":True,
        "original_source_parquet_h5_or_sqlite_written":False,
        "real_h5_written":False,
        "vendor_amount_physical_units_certified":False,
        "lossless_native_h5_amount_conversion_certified":False,
        "ready_for_full_market_mirror":False,
        "ready_to_modify_purchased_parquet_or_original_h5":False,
    }


class PureResidualHeldoutTests(unittest.TestCase):
    def test_two_signs_discriminate_half_even_and_direction(self):
        pq,h5=pairs()
        result=T.sample_day(pq,h5,"2026-09-28")
        self.assertEqual(result["sample_positive_pairs"],2)
        self.assertEqual(result["would_require_decimal_rounding"],2)
        self.assertEqual(result["candidate_above_original_count"],1)
        self.assertEqual(result["candidate_below_original_count"],1)
        self.assertEqual(result["nearest_half_even_matches_original_count"],2)
        self.assertEqual(result["ceiling_matches_original_count"],1)
        self.assertEqual(result["floor_matches_original_count"],1)
        self.assertEqual(
            result["rounding_hypotheses_half_even_vs_ceil_differ_count"],1)
        self.assertEqual(
            result["rounding_hypotheses_half_even_vs_floor_differ_count"],1)
        self.assertEqual(result["absolute_integer_candidate_residual_buckets"]["le_0p01"],2)
        self.assertEqual(result["within_previous_relative_tolerance_count"],2)

    def test_not_all_heldout_amount_pairs_must_require_rounding(self):
        pq,h5=pairs(offsets=(0.0,0.0))
        res=T.sample_day(pq,h5,"2026-09-28")
        self.assertEqual(res["candidate_exact_original_h5_integer_count"],2)
        self.assertEqual(res["would_require_decimal_rounding"],0)
        self.assertEqual(res["absolute_integer_candidate_residual_buckets"]["zero"],2)

    def test_large_residual_can_be_reported_not_silenced(self):
        pq,h5=pairs(offsets=(2.0,-2.0))
        res=T.sample_day(pq,h5,"2026-09-28")
        self.assertEqual(res["absolute_integer_candidate_residual_buckets"]["gt_1"],2)
        self.assertEqual(res["within_previous_relative_tolerance_count"],0)

    def test_bad_day_or_missing_pair_is_rejected(self):
        pq,h5=pairs()
        with self.assertRaises(ValueError):
            T.sample_day(pq,h5,"2026-09-30")
        h5[T.PAIR.SYMBOLS[0]]["datetime"]=202609300000
        with self.assertRaisesRegex(ValueError,"invalid fields or day"):
            T.sample_day(pq,h5,"2026-09-28")
        pq.pop(T.PAIR.SYMBOLS[0])
        with self.assertRaisesRegex(ValueError,"two known heldout"):
            T.sample_day(pq,h5,"2026-09-28")

    def test_evaluate_aggregates_two_days_correctly(self):
        a,b=pairs("2026-09-28",(0.001,-0.001))
        c,d=pairs("2026-09-29",(0,0))
        per,total=T.evaluate({
            "2026-09-28":{"parquet":a,"h5":b},
            "2026-09-29":{"parquet":c,"h5":d}})
        self.assertEqual(total["sample_positive_pairs"],4)
        self.assertEqual(total["would_require_decimal_rounding"],2)
        self.assertEqual(total["candidate_exact_original_h5_integer_count"],2)
        self.assertEqual(total["nearest_half_even_matches_original_count"],4)
        self.assertEqual(total["absolute_integer_candidate_residual_buckets"]["zero"],2)
        self.assertEqual(total["absolute_integer_candidate_residual_buckets"]["le_0p01"],2)
        self.assertEqual(set(per),set(T.DAYS))

    def test_invalid_numeric_pair_rejected(self):
        pq,h5=pairs()
        pq[T.PAIR.SYMBOLS[0]]["amount"]=float("inf")
        with self.assertRaises(ValueError):
            T.sample_day(pq,h5,"2026-09-28")
        pq,h5=pairs()
        h5[T.PAIR.SYMBOLS[1]]["transAmount"]=-1
        with self.assertRaises(ValueError):
            T.sample_day(pq,h5,"2026-09-28")


class SyntheticHeldoutOriginalReaderTests(unittest.TestCase):
    def setUp(self):
        self.fixture=FIX.HeldoutSyntheticDaysTests(
            methodName="test_four_out_of_sample_stock_days_match_without_certifying_units")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.reports=self.fixture.reports
        self.heldout=self.reports/"heldout-previous.json"
        self.disc=self.reports/"discovery-amount.json"
        self.out=self.reports/"heldout-new-residual.json"
        p=patch.object(T.AUDIT,"REPORTS",self.reports)
        p.start()
        self.addCleanup(p.stop)
        self.disc.write_text(json.dumps(discovery_document()),encoding="utf-8")
        T.HOLDOUT.run(self.fixture.pqroot,self.fixture.h5root,
                      self.fixture.raw,self.fixture.native,self.heldout)

    def run_it(self):
        return T.run(self.fixture.pqroot,self.fixture.h5root,
                     self.heldout,self.disc,self.out)

    def test_real_reader_equivalent_synthetic_originals_not_modified(self):
        files=[self.fixture.source,*self.fixture.h5root.glob("*.h5")]
        before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        result=self.run_it()
        self.assertEqual(result["heldout_stock_days_compared"],4)
        self.assertEqual(result["original_h5_raw_day_records_read"],4)
        self.assertTrue(result["prior_heldout_factor_counts_reproduced"])
        self.assertEqual(result["heldout_aggregate_residual_counts"][
            "candidate_exact_original_h5_integer_count"],4)
        self.assertEqual(result["heldout_aggregate_residual_counts"][
            "absolute_integer_candidate_residual_buckets"]["zero"],4)
        self.assertFalse(result["lossless_native_h5_amount_conversion_certified"])
        self.assertFalse(result["ready_for_full_market_mirror"])
        self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in files})
        text=self.out.read_text(encoding="utf-8")
        for forbidden in ("SH600000","SZ000001","600000.XSHG",
                          "000001.XSHE","202609280000","202609290000",
                          "AllCycleAStockData","HikyuuData",
                          "420000.0"):
            self.assertNotIn(forbidden,text)

    def test_noninteger_residual_positive_and_negative_while_factor_matches(self):
        data=self.fixture.pq.read_table(self.fixture.source).to_pylist()
        data[0]["amount"]+=1.0
        data[1]["amount"]-=1.0
        self.fixture.pq.write_table(self.fixture.pa.Table.from_pylist(data),
                                    self.fixture.source)
        self.heldout.unlink()
        T.HOLDOUT.run(self.fixture.pqroot,self.fixture.h5root,
                      self.fixture.raw,self.fixture.native,self.heldout)
        result=self.run_it()
        by=result["heldout_aggregate_residual_counts"]
        self.assertEqual(by["would_require_decimal_rounding"],2)
        self.assertEqual(by["candidate_exact_original_h5_integer_count"],2)
        self.assertEqual(by["nearest_half_even_matches_original_count"],4)
        self.assertEqual(by["ceiling_matches_original_count"],3)
        self.assertEqual(by["floor_matches_original_count"],3)

    def test_prior_discovery_safe_forged_certification_rejected(self):
        previous=discovery_document()
        previous["ready_for_full_market_mirror"]=True
        self.disc.write_text(json.dumps(previous),encoding="utf-8")
        with patch.object(T.DAY,"_read_bounded_daily",
                          side_effect=AssertionError("DO NOT read market")):
            with self.assertRaisesRegex(ValueError,"not qualified"):
                self.run_it()
        self.assertFalse(self.out.exists())

    def test_prior_heldout_safe_forged_factor_or_flags_rejected(self):
        doc=json.loads(self.heldout.read_text(encoding="utf-8"))
        doc["aggregate"]["amount_candidate_factor1000_matched"]=3
        self.heldout.write_text(json.dumps(doc),encoding="utf-8")
        with patch.object(T.DAY,"_read_bounded_daily",
                          side_effect=AssertionError("DO NOT read market")):
            with self.assertRaisesRegex(ValueError,"not be used"):
                self.run_it()
        self.assertFalse(self.out.exists())

    def test_changed_sources_after_heldout_safe_rejected_not_falsely_reproduced(self):
        original=T.PAIR._read_single_h5
        def changed(*args,**kw):
            row=original(*args,**kw)
            if args[1]=="SH600000" and args[2]=="2026-09-28":
                return dict(row,transAmount=row["transAmount"]+10)
            return row
        with patch.object(T.PAIR,"_read_single_h5",side_effect=changed):
            with self.assertRaisesRegex(ValueError,"no longer reproduces"):
                self.run_it()
        self.assertFalse(self.out.exists())

    def test_existing_safe_cannot_overwrite(self):
        self.out.write_text("PROTECTED",encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertEqual(self.out.read_text(encoding="utf-8"),"PROTECTED")

    def test_missing_prior_report_rejected_before_market_read(self):
        self.heldout.unlink()
        with patch.object(T.DAY,"_read_bounded_daily",
                          side_effect=AssertionError("DO NOT read market")):
            with self.assertRaises(ValueError):
                self.run_it()

    def test_no_market_writers_in_new_tool(self):
        code=(HERE.parent/"tools"/
              "audit-real-heldout-pq-h5-amount-residual-readonly.py").read_text(
                  encoding="utf-8")
        for forbidden in ("h5py.File(","create_dataset(","sqlite3.connect(",
                          "write_table(","os.replace(","shutil.copyfile("):
            self.assertNotIn(forbidden,code)
        self.assertIn("HOLDOUT.evaluate_holdout",code)
        self.assertIn("AMOUNT.one_amount",code)


if __name__=="__main__":
    unittest.main(verbosity=2)
