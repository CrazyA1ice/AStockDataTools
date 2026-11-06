"""Synthetic original H5 1990 private historical day pilot tests.

Tests use only fictional 1990 H5 sources and local temp private Parquet.
No user market files or purchased bars are opened; the production root is
never modified and no real OHLCVA values leave the sandbox.
"""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "private_1990_h5_source_staging_contracts",
    HERE.parent/"tools"/"stage-original-h5-1990-private-day-pilot.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
ORIGINAL_PURCHASED_GATE=M.purchased_gate
DT=np.dtype([
    ("datetime","<i8"),
    ("openPrice","<i8"),("highPrice","<i8"),
    ("lowPrice","<i8"),("closePrice","<i8"),
    ("transCount","<i8"),("transAmount","<i8"),
])


class Private1990ResearchStageContracts(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.container=Path(t.name)
        self.root=self.container/"stock"
        self.h5=self.root/"HikyuuData"
        self.h5.mkdir(parents=True)
        for m in M.MARKETS:
            with h5py.File(self.h5/(m+"_day.h5"),"w") as f:
                f.create_group("data")
        self.private=self.container/"gitignored"/"work"/"unified_parquet"/"historical_pre2011_daily_pilots"
        self.private.parent.mkdir(parents=True)
        self.addCleanup(patch.stopall)

    def put(self,market,symbol,stamps,**value_overrides):
        arr=np.zeros(len(stamps),dtype=DT)
        arr["datetime"]=stamps
        for key,value in {
            "openPrice":10000,"highPrice":11000,"lowPrice":9000,
            "closePrice":10050,"transCount":100,"transAmount":2000,
            **value_overrides,
        }.items():
            arr[key]=value
        with h5py.File(self.h5/(market+"_day.h5"),"a") as f:
            f["data"].create_dataset(symbol,data=arr)

    def rows(self):
        self.put("sh","SH600000",[199012200000,199012210000])
        self.put("sh","SH900901",[199012200000])
        # Existing scheme excludes pre-2011 BJ legacy codes.
        self.put("bj","BJ430001",[199012200000])

    def fixtures(self):
        # The production path is gated against the independently observed
        # immutable fingerprints; synthetic tests bind to their own fake.
        proof={
            "source_file_size_mtime_state_sha256":"b"*64,
        }
        p1=patch.object(M,"PARENT",self.private)
        p2=patch.object(M,"EXPECTED_H5_STATE",M.h5_state(self.root))
        p3=patch.object(M,"EXPECTED_PQ_STATE","b"*64)
        p4=patch.object(M,"purchased_gate",return_value=proof)
        p5=patch.object(M,"EXPECT_A_STOCKDAYS",2)
        p6=patch.object(M,"EXPECT_OTHER_STOCKDAYS",2)
        p7=patch.object(M,"EXPECT_A_SYMBOLS",1)
        p8=patch.object(M,"EXPECT_A_DATES",2)
        for p in (p1,p2,p3,p4,p5,p6,p7,p8):
            p.start()

    def test_plan_has_two_private_candidate_rows_no_files_written(self):
        self.rows()
        self.fixtures()
        before={x.name:(x.stat().st_size,x.stat().st_mtime_ns)
                for x in self.h5.iterdir()}
        result=M.stage(self.root)
        self.assertEqual(result["state"],"read_only_1990_private_candidate_preflight_passed_not_staged")
        self.assertEqual(result["candidate_stockday_rows"],2)
        self.assertEqual(result["other_code_source_rows_not_staged"],2)
        self.assertEqual(result["market_candidate_rows"],{"SH":2})
        self.assertFalse(result["historical_security_master_certified"])
        self.assertFalse(result["h5_volume_amount_price_units_certified"])
        self.assertFalse(result["ready_for_production_merge"])
        self.assertFalse(result["private_parquet_written"])
        self.assertFalse(self.private.exists())
        self.assertEqual(before,{x.name:(x.stat().st_size,x.stat().st_mtime_ns)
                                 for x in self.h5.iterdir()})

    def test_explicit_private_write_keeps_market_unmodified_and_roundtrip(self):
        self.rows()
        self.fixtures()
        before={x.name:(x.stat().st_size,x.stat().st_mtime_ns)
                for x in self.h5.iterdir()}
        summary=M.stage(self.root,write=True)
        self.assertEqual(summary["state"],"verified_private_candidate_not_promoted")
        self.assertTrue(summary["private_parquet_written"])
        runs=list(self.private.iterdir())
        self.assertEqual(len(runs),1)
        table=pq.read_table(runs[0]/"day.parquet")
        manifest=json.loads((runs[0]/"manifest.json").read_text("utf-8"))
        self.assertEqual(table.num_rows,2)
        self.assertEqual(manifest["private_parquet_row_count"],2)
        self.assertEqual(table.column("source").to_pylist(),[
            "hikyuu_h5_1990_uncertified_private_candidate"]*2)
        self.assertTrue(manifest["private_parquet_sha256"])
        self.assertNotIn("SH600000",json.dumps(manifest))
        self.assertNotIn('"open":',json.dumps(manifest))
        self.assertFalse(manifest["ready_for_production_merge"])
        self.assertEqual(before,{x.name:(x.stat().st_size,x.stat().st_mtime_ns)
                                 for x in self.h5.iterdir()})

    def test_absent_explicit_write_does_not_create_candidate(self):
        self.rows()
        self.fixtures()
        M.stage(self.root,write=False)
        self.assertFalse(self.private.exists())

    def test_original_h5_state_sha_drift_rejected_before_market_decode(self):
        self.rows()
        self.fixtures()
        with patch.object(M,"EXPECTED_H5_STATE","c"*64),patch.object(
                M,"source_1990",side_effect=AssertionError("no bar reads")):
            with self.assertRaisesRegex(ValueError,"H5 stat SHA changed"):
                M.stage(self.root)

    def test_purchased_physical_2011_absence_gate_rejected_before_h5_decode(self):
        self.rows()
        self.fixtures()
        with patch.object(M,"purchased_gate",
                          side_effect=ValueError("Purchased proof changed")),patch.object(
                M,"source_1990",side_effect=AssertionError("no H5 OHLCVA")):
            with self.assertRaisesRegex(ValueError,"proof changed"):
                M.stage(self.root)

    def test_duplicate_h5_1990_dates_fail_closed(self):
        self.put("sh","SH600000",[199012200000,199012200000])
        with self.assertRaisesRegex(ValueError,"duplicate/not sorted"):
            M.source_1990(self.root)

    def test_malformed_h5_daily_1990_dates_fail_closed(self):
        self.put("sh","SH600000",[199002300000])
        with self.assertRaisesRegex(ValueError,"calendar date invalid"):
            M.source_1990(self.root)

    def test_nonmidnight_h5_daily_1990_keys_fail_closed(self):
        self.put("sh","SH600000",[199012200931])
        with self.assertRaisesRegex(ValueError,"not canonical"):
            M.source_1990(self.root)

    def test_negative_h5_original_price_fails_closed(self):
        self.put("sh","SH600000",[199012200000],openPrice=-1)
        with self.assertRaisesRegex(ValueError,"Negative"):
            M.source_1990(self.root)

    def test_invalid_h5_ohlc_geometry_fails_closed(self):
        self.put("sh","SH600000",[199012200000],highPrice=8000)
        with self.assertRaisesRegex(ValueError,"geometric"):
            M.source_1990(self.root)

    def test_yearly_h5_candidate_count_never_silently_relaxed(self):
        self.rows()
        with self.assertRaisesRegex(ValueError,"24/16 candidate evidence changed"):
            M.source_1990(self.root)

    def test_no_output_root_overlap_with_market_data(self):
        self.rows()
        self.fixtures()
        with patch.object(M,"PARENT",self.root/"private"):
            with self.assertRaisesRegex(ValueError,"overlaps"):
                M.stage(self.root)

    def test_different_native_h5_file_stat_digest_not_staged(self):
        self.rows()
        self.fixtures()
        with patch.object(M,"h5_state",side_effect=[M.EXPECTED_H5_STATE,"c"*64]):
            with self.assertRaisesRegex(ValueError,"source drift"):
                M.stage(self.root)

    def test_pre2011_purchased_absence_requires_explicit_24_139_footer_proof(self):
        self.rows()
        self.fixtures()
        with patch.object(M,"purchased_gate",ORIGINAL_PURCHASED_GATE), patch.object(M.PQ,"audit",return_value={
            "state":"pre2011_purchased_parquet_original_day_keys_audited_readonly",
            "source_file_size_mtime_state_sha256":M.EXPECTED_PQ_STATE,
            "source_files":24,"rowgroups_total":139,
            "rowgroups_pruned_proven_by_min_ts_ge_2011":138,
            "rowgroups_key_projected":1,
            "no_1990_2010_purchased_keys_in_audited_files":True,
            "all_rowgroups_have_trusted_min_ts_ge_2011":False,
            "pre1990_physical_rows_detected":0,
            "source_key_only_no_ohlcva_read":True,
            "market_files_written":False,
            "purchased_original_source_stat_unchanged":True,
        }):
            with self.assertRaisesRegex(ValueError,"physical absence/source SHA gate failed"):
                M.purchased_gate(self.root)


if __name__=="__main__":
    unittest.main(verbosity=2)
