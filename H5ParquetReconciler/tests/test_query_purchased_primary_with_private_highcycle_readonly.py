"""Synthetic source-priority and physical SHA gates for eight-cycle highcycle opt-in."""
from __future__ import annotations
import importlib.util
import tempfile
import unittest
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "test_oct_highcycle_purchased_first_integration",
    HERE.parent/"tools"/"query-purchased-primary-with-private-highcycle-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
D1="2026-10-08"
D2="2026-10-09"
UTC8=timezone(timedelta(hours=8))

def ms(day,minute=0):
    y,m,d=map(int,day.split("-"))
    return int(datetime(y,m,d,9,30+minute,tzinfo=UTC8).timestamp()*1000)

def purchased(day):
    return {"symbol":"SH600000","period":"15min","trading_date":day,
            "source_timestamp_ms":ms(day),"value_source":"purchased_parquet",
            "source_file_relative_path":"AllCycleAStockData/15min/purchased.parquet",
            "source_row_group":0,"source_beijing_time":day+" 09:30",
            "h5_native_datetime":None,
            "open":1.0,"high":1.1,"low":0.9,"close":1.0,
            "volume":100.0,"amount":1000.0}

def private(day):
    return {"ts":ms(day),"symbol":"SH600000",
            "trading_date":day,"period":"15min",
            "open":1.0,"high":1.1,"low":0.9,"close":1.0,
            "volume":100.0,"amount":1000.0,
            "value_source":M.S.VALUE_SOURCE,
            "source_5min_private_sha256":"b"*64,
            "_private_file_relative_path":"work/unified_parquet/oct_high_cycle_staging/aaaaaaaaaaaa/15min.parquet",
            "time_label_and_vendor_units_certified":False,
            "corporate_adjustments_applied":False,
            "source_period":"5min"}

class PrivateHighcycleEightCycleReadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.bars=[]
        self._patches=[
            patch.object(M.ALL,"query_bars",side_effect=self.query_purchased),
            patch.object(M.N,"existing_stockdays",return_value=(
                frozenset({(D1,"SH600000"),(D2,"SH600000")}),2)),
            patch.object(M.A,"audit",side_effect=self.audit),
            patch.object(M,"_validated_private_rowset",side_effect=self.query_candidate)
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        self.derived=[]

    def query_purchased(self,root,canonical,period,first,last,**kwargs):
        self.assertEqual(canonical,"SH600000")
        return {"bars":list(self.bars),"safe_summary":{"matching_bar_count":len(self.bars)}}

    def audit(self,d):
        self.assertIn(d.isoformat(),(D1,D2))
        return {
            "this_date_coverage_complete":True,
            "this_date_unstaged_complete_stockdays":0,
            "full_existing_receipt_and_parquet_sha_reverified":True}

    def query_candidate(self,root,day,symbol,period,registry):
        self.derived.append(day)
        self.assertEqual(period,"15min")
        self.assertEqual(symbol,"SH600000")
        return [private(day)]

    def query(self,first=D1,last=D2,*,on=True,max_result_bars=1000):
        return M.query_bars(self.root,"SH600000","15min",first,last,
                            allow_private_highcycle=on,
                            max_result_bars=max_result_bars)

    def test_opt_in_reads_existing_candidate_when_no_purchased_bar(self):
        result=self.query()
        self.assertEqual(len(result["bars"]),2)
        self.assertEqual(self.derived,[D1,D2])
        self.assertEqual(result["safe_summary"]["bars_by_source"][M.S.VALUE_SOURCE],2)
        self.assertEqual(result["bars"][0]["source_file_relative_path"],
                         private(D1)["_private_file_relative_path"])
        self.assertFalse(result["safe_summary"]["ready_for_production_query"])
        self.assertFalse(result["safe_summary"]["vendor_physical_units_certified"])

    def test_purchased_day_owns_stockday_entirely_and_h5_only_fills_gap(self):
        self.bars=[purchased(D1)]
        result=self.query()
        self.assertEqual(result["safe_summary"]["bars_by_source"]["purchased_parquet"],1)
        self.assertEqual(self.derived,[D2])
        self.assertEqual(len(result["bars"]),2)
        self.assertEqual(result["bars"][0]["value_source"],"purchased_parquet")

    def test_default_off_no_candidate_lookup_or_new_writes(self):
        self.bars=[purchased(D1)]
        with patch.object(M.N,"existing_stockdays") as registry:
            result=self.query(on=False)
        registry.assert_not_called()
        self.assertEqual(result["bars"],self.bars)
        self.assertFalse(result["safe_summary"]["private_highcycle_explicitly_enabled"])
        self.assertEqual(result["safe_summary"]["bars_by_source"][M.S.VALUE_SOURCE],0)
        self.assertFalse(list(self.root.iterdir()))

    def test_periods_other_than_highcycle_disallow_candidate_route(self):
        with self.assertRaisesRegex(ValueError,"only supports 15/30/60"):
            M.query_bars(self.root,"SH600000","day",D1,D2,
                         allow_private_highcycle=True)

    def test_candidate_requires_completed_source_day_audit(self):
        with patch.object(M.A,"audit",return_value={
            "this_date_coverage_complete":False,
            "this_date_unstaged_complete_stockdays":1,
            "full_existing_receipt_and_parquet_sha_reverified":True}):
            with self.assertRaisesRegex(ValueError,"not fully SHA-verified"):
                self.query()
        self.assertEqual(self.derived,[])

    def test_duplicate_ts_fails_closed(self):
        self.bars=[purchased(D1)]
        # Same period/time but H5 only D2 candidate is valid; now malicious
        # original queried rows in D2 have duplicate purchased raw timestamp.
        self.bars=[purchased(D1),purchased(D1)]
        with self.assertRaisesRegex(ValueError,"timestamp overlap"):
            self.query()

    def test_max_bar_limit_after_source_union(self):
        with self.assertRaisesRegex(ValueError,"output bound"):
            self.query(max_result_bars=1)

    def test_unregistered_stockday_never_falls_back(self):
        with patch.object(M.N,"existing_stockdays",return_value=(frozenset(),3)):
            r=self.query()
        self.assertEqual(r["bars"],[])
        self.assertEqual(self.derived,[])

    def test_private_arrow_schema_16_bar_exact_readback(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"15min.parquet"
            schema=pa.schema([
                pa.field("ts",pa.int64(),nullable=False),
                pa.field("symbol",pa.string(),nullable=False),
                pa.field("trading_date",pa.string(),nullable=False),
                pa.field("period",pa.string(),nullable=False),
                *(pa.field(f,pa.float64(),nullable=False) for f in M.ALL.FIELDS),
                pa.field("value_source",pa.string(),nullable=False),
                pa.field("source_period",pa.string(),nullable=False),
                pa.field("source_5min_private_sha256",pa.string(),nullable=False),
                pa.field("time_label_and_vendor_units_certified",pa.bool_(),nullable=False),
                pa.field("corporate_adjustments_applied",pa.bool_(),nullable=False)])
            rows=[]
            for i in range(16):
                r=dict(private(D1))
                r.pop("_private_file_relative_path")
                r["ts"]=ms(D1)+i*15*60000
                rows.append(r)
            pq.write_table(pa.Table.from_pylist(rows,schema=schema),p)
            recovered=M._private_subset(p,"SH600000",D1,"15min")
        self.assertEqual(len(recovered),16)
        self.assertEqual(recovered,rows)


    def test_four_day_canary_receipt_uses_matching_day_source_not_first_day(self):
        import json
        with tempfile.TemporaryDirectory() as base:
            module=Path(base)/"H5ParquetReconciler"
            run=module/"work"/"unified_parquet"/"oct_high_cycle_staging"/"aaaaaaaaaaaa"
            run.mkdir(parents=True)
            file=run/"15min.parquet"
            file.write_bytes(b"test candidate physical output")
            record=private(D2)
            record.pop("_private_file_relative_path")
            all_dates=["2026-10-08","2026-10-09","2026-10-12","2026-10-13"]
            doc={
                "source_days":all_dates,
                "symbols":["SH600000","SZ000001"],
                "outputs":{"15min":{
                    "sha256":"e"*64,
                    "complete_row_by_row_readback_exact":True,
                    "private_file":file.relative_to(module).as_posix()}},
                "sources":[{"day":day,"sha256":"b"*64 if day==D2 else "c"*64}
                           for day in all_dates]}
            (run/"receipt.json").write_text(json.dumps(doc),encoding="utf-8")
            with (patch.object(M.S,"MODULE",module),
                  patch.object(M.S,"_safe_stage_root",return_value=run.parent),
                  patch.object(M.S,"_sha",return_value="e"*64),
                  patch.object(M.S,"build_candidates",
                               return_value=({"15min":[record]},
                                             {D2:(file,"b"*64)})),
                  patch.object(M,"_private_subset",return_value=[dict(record)])):
                result=M._validated_private_rowset(
                    self.root,D2,"SH600000","15min",frozenset({(D2,"SH600000")}))
            self.assertEqual(len(result),1)
            self.assertEqual(result[0]["_private_file_relative_path"],
                             doc["outputs"]["15min"]["private_file"])

    def test_wrong_arrow_schema_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"15min.parquet"
            pq.write_table(pa.table({"ts":[ms(D1)]}),p)
            with self.assertRaisesRegex(ValueError,"private highcycle schema"):
                M._private_subset(p,"SH600000",D1,"15min")

if __name__=="__main__":
    unittest.main()
