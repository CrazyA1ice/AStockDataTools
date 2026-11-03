"""Synthetic local 1990-2026 tiered DAY physical-reader contract checks.

NO customer paid data is opened. No real vendor file is modified.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent.parent/"tools"
spec=importlib.util.spec_from_file_location(
    "tiered_local_day_verified_test_reader",
    HERE/"query-private-1990-2026-tiered-day-local.py")
Q=importlib.util.module_from_spec(spec)
spec.loader.exec_module(Q)

class TieredDayTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="tiered-private-day-")
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.private=self.root/"work"/"unified_parquet"/"pre2011_day_candidates"
        self.private.mkdir(parents=True)
        self.report=self.root/"reports"
        self.report.mkdir()
        self.year=2009
        self.child="0123456789ab"
        self.annual=self.private/f"historical_{self.year}_{self.child}"
        self.annual.mkdir()
        self.patches=[
            patch.object(Q,"MODULE",self.root),
            patch.object(Q,"PRIVATE",self.private),
            patch.object(Q,"REPORTS",self.report)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def entry_for(self,path,digest):
        return {
            "candidate_parquet_relative_path":path.relative_to(self.root).as_posix(),
            "candidate_parquet_sha256":digest,
            "quarantine_parquet_relative_path":(
                self.annual/"source_native_quarantine.parquet").relative_to(
                    self.root).as_posix(),
            "quarantine_parquet_sha256":"a"*64,
        }

    def test_cannot_read_1990_2010_without_explicit_optins(self):
        with self.assertRaisesRegex(ValueError,"opt into"):
            Q.check_query("SH600000","2009-01-01","2009-01-02",31,
                          True,False,False)
        with self.assertRaisesRegex(ValueError,"explicit local opt-in"):
            Q.check_query("SH600000","2009-01-01","2009-01-02",31,
                          False,True,False)
        with self.assertRaisesRegex(ValueError,"Only canonical"):
            Q.check_query("sh600000","2009-01-01","2009-01-02",31,
                          True,True,False)

    def test_invalid_day_or_over31_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"1..31 days"):
            Q.check_query("SH600000","2009-01-01","2009-02-03",31,
                          True,True,False)
        with self.assertRaisesRegex(ValueError,"Only 1..31 DAY"):
            Q.check_query("SH600000","2009-01-01","2009-01-02",32,
                          True,True,False)

    def test_real_synthetic_parquet_hypothesis_reads_only_matching_symbol(self):
        file=self.annual/"purchased_schema_day_candidates.parquet"
        schema=Q.STAGE.PHYS.schema(pa)
        row={
            "ts":1230768000000, "trading_date":"2009-01-01",
            "symbol":"SH600000","source_symbol":"SH600000",
            "open":10.0,"high":11.0,"low":9.0,"close":10.0,
            "volume":10000.0,"amount":100000.0,"value_source":Q.HIST_LABEL}
        other=dict(row,symbol="SZ000001",source_symbol="SZ000001")
        pq.write_table(pa.Table.from_pylist([row,other],schema=schema),file)
        ent=self.entry_for(file,Q.sha(file))
        self.assertEqual(Q.historical_file(ent,2009,
                         "purchased_schema_day_candidates"),file)
        records=Q.read_history_part(
            file,"purchased_schema_day_candidates","SH600000",
            __import__("datetime").date(2009,1,1),
            __import__("datetime").date(2009,1,2),31)
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]["value_source"],Q.HIST_LABEL)
        file.write_bytes(file.read_bytes()+b"broken")
        with self.assertRaisesRegex(ValueError,"SHA changed"):
            Q.historical_file(ent,2009,"purchased_schema_day_candidates")

    def test_local_reader_keeps_historical_candidate_separate(self):
        historical={"historical_years":{
            str(y):{} for y in range(1990,2011)}}
        historical["historical_years"]["2010"]={"test":True}
        candidate={
            "ts":1293753600000,"trading_date":"2010-12-31",
            "symbol":"SH600000","source_symbol":"SH600000",
            "open":1.0,"high":1.0,"low":1.0,"close":1.0,
            "volume":100.0,"amount":1000.0,"value_source":Q.HIST_LABEL}
        purchased={
            "ts":1294099200000,"trading_date":"2011-01-04",
            "symbol":"SH600000","source_symbol":"SH600000",
            "open":2.0,"high":2.0,"low":2.0,"close":2.0,
            "volume":200.0,"amount":2000.0,"value_source":"purchased_parquet"}
        with patch.object(Q,"checked_manifest",return_value=historical),patch.object(
             Q,"historical_file",return_value=Path("mock.parquet")),patch.object(
             Q,"read_history_part",return_value=[candidate]),patch.object(
             Q.MODERN,"read_local_bars",return_value={"bars":[purchased]}):
            r=Q.read_local_bars(
                self.report/"history.json","a"*64,
                self.report/"modern.json","b"*64,
                "SH600000","2010-12-30","2011-01-04",
                allow_private_values=True,
                allow_unverified_historical=True,max_result_bars=31)
        self.assertEqual(len(r["bars"]),2)
        self.assertEqual(r["native_quarantine_rows"],[])
        self.assertEqual(r["safe_summary"]["counts_by_data_tier"]["purchased_2011_2026"],1)
        self.assertEqual(r["safe_summary"]["counts_by_data_tier"]["h5_pre2011_unverified_hypothesis"],1)
        self.assertFalse(r["safe_summary"]["ready_for_production_query"])
        self.assertFalse(r["safe_summary"]["historical_vendor_units_or_stock_identity_certified"])

    def test_native_quarantine_never_normalized_into_float_bars(self):
        historical={"historical_years":{str(y):{} for y in range(1990,2011)}}
        native={"symbol":"SH600000","datetime":199012200000,"quarantine_reason":"native_volume_or_amount_zero"}
        with patch.object(Q,"checked_manifest",return_value=historical),patch.object(
             Q,"historical_file",return_value=Path("mock.parquet")),patch.object(
             Q,"read_history_part",return_value=[native]):
            r=Q.read_local_bars(
                self.report/"history.json","a"*64,
                self.report/"modern.json","b"*64,
                "SH600000","1990-12-20","1990-12-20",
                allow_private_values=True,allow_native_quarantine=True)
        self.assertEqual(r["bars"],[])
        self.assertEqual(r["native_quarantine_rows"],[native])
        self.assertTrue(r["safe_summary"]["native_quarantine_kept_separate"])

if __name__=="__main__":
    unittest.main(verbosity=2)
