"""Purchased-first offline private 22,274 candidate view synthetic gates."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "private_joined_market_view_synthetic",
    HERE.parent/"tools"/"query-private-purchased-plus-22274-candidates.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
SYM=("SH600000","SZ000001")
START="2026-09-30"
END="2026-10-13"
SHA="e"*64


def ts(day):
    return int(datetime.fromisoformat(day+"T00:00:00+08:00").timestamp()*1000)


def bar(symbol,day,source=None):
    b={"symbol":symbol,"period":"day","trading_date":day,
       "source_timestamp_ms":ts(day),
       "open":10.0,"high":11.0,"low":9.0,
       "close":10.5,"volume":100.0,"amount":1000.0}
    if source is not None:
        b["value_source"]=source
    return b


class UnifiedPrivateCandidateTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        scratch=HERE.parent/"work"/"_union_scratch"
        scratch.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(prefix="joined_22274_test_",dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.reports=self.root/"reports"
        self.reports.mkdir()
        self.source_root=self.root/"stock"
        self.source_root.mkdir()
        self.gate=self.reports/"recheck.json"
        self.out=self.reports/"view.json"
        self.candidate_safe=self.reports/"candidate.json"
        self.candidate_safe.write_bytes(b'{"private":true}\n')
        self.dir=self.root/"candidate"
        (self.dir/"year=2026").mkdir(parents=True)
        self.mf=self.dir/"manifest.json"
        cand=[]
        for symbol in SYM:
            for day in ("2026-10-08","2026-10-09","2026-10-12","2026-10-13"):
                cand.append({
                    "ts":ts(day),"trading_date":day,"symbol":symbol,
                    "open":10.0,"high":11.0,"low":9.0,
                    "close":10.5,"volume":100.0,"amount":1000.0,
                    "value_source":"private_h5_whole_date_candidate",
                })
        pqfile=self.dir/"year=2026"/"day.parquet"
        pq.write_table(pa.Table.from_pylist(
            cand,schema=M.STAGER.candidate_schema(pa)),pqfile)
        self.parquet=pqfile
        self.manifest={"partitions":{
            "2026":{"sha256":M.STAGER.sha(pqfile)}}}
        self.mf.write_bytes(json.dumps(self.manifest).encode())
        self.doc={
            "source_version_sha256":SHA,
            "manifest_sha256":M.STAGER.sha(self.mf),
            "candidate_year_rows":{"2026":8},
            "original_source_stat_sha256":"d"*64,
        }
        self.proof_sha=hashlib.sha256(self.candidate_safe.read_bytes()).hexdigest()
        self.full={
            "state":"all_22274_candidate_rows_partition_sha_schema_and_keys_verified_not_merged",
            "total_h5_only_day_candidates_verified":22274,
            "whole_date_candidate_rows_verified":22191,
            "mixed_date_candidate_rows_verified":83,
            "candidate_source_units_certified":False,
            "full_purchased_parquet_historical_market_included":False,
            "original_market_source_freshness_rechecked":False,
            "source_private_version_sha256":SHA,
            "source_private_manifest_sha256":self.doc["manifest_sha256"],
            "source_materialization_safe_sha256":self.proof_sha,
        }
        self.patches=[
            patch.object(M.V,"REPORTS",self.reports),
            patch.object(M.V,"source",side_effect=lambda _:(
                self.doc,self.proof_sha,self.dir,self.mf)),
            patch.object(M.V,"verify",side_effect=self.fake_verify),
            patch.object(M.STAGER.PRE.KEYS,"state_digest",return_value="d"*64),
            patch.object(M.STAGER.REG,"load_version",return_value={
                "original_source_stat_sha256":"d"*64}),
            patch.object(M.STAGER.REG,"LOCK",self.root/"no-lock"),
            patch.object(M.P,"query_bars",side_effect=self.purchased),
            patch.object(M.P.private_cache,"source_signature",
                         return_value={"file_count":2,"fixed":True}),
        ]
        self.mocks=[p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)

    def fake_verify(self,source,out):
        Path(out).write_bytes(b'{"checked":true}\n')
        return dict(self.full)

    def purchased(self,root,symbol,period,first,last,**options):
        self.assertEqual(root,self.source_root)
        self.assertEqual(period,"day")
        self.assertFalse(options["local_cache"])
        return {"bars":[bar(symbol,START)],
                "safe_summary":{"source_rows_scanned":400,
                                "source_market_files_modified":False,
                                "no_h5_read":True,"no_automatic_gaps_fill":True}}

    def run_it(self,**kwargs):
        return M.query(self.source_root,self.candidate_safe,SYM,START,END,
                       self.gate,self.out,**kwargs)

    def test_two_stocks_ten_bars_one_offline_full_candidate_gate(self):
        r=self.run_it()
        s=r["safe_summary"]
        self.assertEqual(s["returned_stockday_rows"],10)
        self.assertEqual((s["purchased_parquet_rows"],
                          s["whole_h5_candidate_rows"],
                          s["mixed_h5_candidate_rows"]),(2,8,0))
        self.assertEqual(s["requested_stock_count"],2)
        self.assertEqual(s["private_candidate_snapshot_safe_sha256"],self.proof_sha)
        self.assertEqual(self.mocks[2].call_count,1)
        self.assertEqual(self.mocks[6].call_count,2)
        self.assertTrue(s["original_live_h5_keyset_not_rescanned"])
        self.assertFalse(s["candidate_source_units_certified"])
        self.assertFalse(s["ready_for_production_query"])
        safe=self.out.read_text(encoding="utf-8")
        self.assertNotIn("SH600000",safe)
        self.assertNotIn("SZ000001",safe)
        self.assertNotIn("10.5",safe)
        self.assertNotIn(str(self.root),safe)

    def test_reject_duplicate_canonical_stock_before_source_scan(self):
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            M.query(self.source_root,self.candidate_safe,
                    ("SH600000","SH600000"),START,END,self.gate,self.out)
        self.mocks[2].assert_not_called()

    def test_reject_crossyear_window_before_source_scan(self):
        with self.assertRaises(ValueError):
            M.query(self.source_root,self.candidate_safe,SYM,
                    "2025-12-31","2026-01-01",self.gate,self.out)
        self.mocks[2].assert_not_called()

    def test_reject_existing_final_safe_before_any_market_scan(self):
        self.out.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError,"NEW"):
            self.run_it()
        self.assertEqual(self.out.read_bytes(),b"keep")
        self.mocks[2].assert_not_called()

    def test_purchase_private_key_collision_never_overwrites(self):
        def collision(root,sym,period,first,last,**kw):
            return {"bars":[bar(sym,"2026-10-08")],
                    "safe_summary":{"source_rows_scanned":1,
                        "source_market_files_modified":False,
                        "no_h5_read":True,"no_automatic_gaps_fill":True}}
        with patch.object(M.P,"query_bars",side_effect=collision):
            with self.assertRaisesRegex(ValueError,"overlap"):
                self.run_it()
        self.assertFalse(self.out.exists())

    def test_missing_private_source_stat_blocks_before_recheck(self):
        self.doc["original_source_stat_sha256"]="f"*64
        with self.assertRaisesRegex(ValueError,"stat differs"):
            self.run_it()
        self.mocks[2].assert_not_called()
        self.assertFalse(self.out.exists())

    def test_mid_query_source_stat_drift_blocks_final_safe(self):
        self.mocks[3].side_effect=["d"*64,"f"*64]
        with self.assertRaisesRegex(ValueError,"changed during query"):
            self.run_it()
        self.assertFalse(self.out.exists())

    def test_queried_purchased_year_changes_during_read_fails(self):
        self.mocks[7].side_effect=[
            {"file_count":2,"fixed":True},
            {"file_count":3,"fixed":False}]
        with self.assertRaisesRegex(ValueError,"changed during query"):
            self.run_it()
        self.assertFalse(self.out.exists())

    def test_modified_private_partition_sha_blocks_result(self):
        self.parquet.write_bytes(self.parquet.read_bytes()+b"modified")
        # The on-disk SHA gate must reject this BEFORE Arrow touches a
        # corrupted Parquet footer; do not depend on Arrow error wording.
        with patch("pyarrow.parquet.ParquetFile",
                   side_effect=AssertionError("opened corrupt Parquet before SHA")) as opened:
            with self.assertRaisesRegex(ValueError,"changed before selection"):
                self.run_it()
            opened.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_modified_private_manifest_sha_blocks_before_arrow(self):
        self.mf.write_bytes(self.mf.read_bytes()+b"modified")
        with patch("pyarrow.parquet.ParquetFile",
                   side_effect=AssertionError("opened Parquet with bad manifest")) as opened:
            with self.assertRaisesRegex(ValueError,"changed before selection"):
                self.run_it()
            opened.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_forged_full_offline_verification_cannot_bypass(self):
        self.full["candidate_source_units_certified"]=True
        with self.assertRaisesRegex(ValueError,"Unqualified"):
            self.run_it()
        self.assertFalse(self.out.exists())

    def test_purchased_cumulative_source_budget_is_fail_closed(self):
        def exact_budget(root,sym,period,first,last,**kw):
            return {"bars":[bar(sym,START)],
                    "safe_summary":{"source_rows_scanned":100,
                        "source_market_files_modified":False,
                        "no_h5_read":True,"no_automatic_gaps_fill":True}}
        with patch.object(M.P,"query_bars",side_effect=exact_budget):
            with self.assertRaisesRegex(ValueError,"budget exhausted"):
                self.run_it(max_candidate_rows_per_symbol=100,
                            max_total_candidate_rows=100)
        self.assertFalse(self.out.exists())

    def test_private_parquet_query_handles_purchased_only_empty_year(self):
        doc=dict(self.doc)
        doc["candidate_year_rows"]={"2016":1,"2026":8}
        self.doc=doc
        # Without a matching partition, candidate source is empty and
        # purchased data remains authoritative.
        selected,_,_=M.verified_candidate_selection(
            self.candidate_safe,self.full,2025,SYM,
            __import__("datetime").date(2025,9,1),
            __import__("datetime").date(2025,9,30))
        self.assertTrue(all(not any(v.values()) for v in selected.values()))

    def test_mixed_source_category_remains_uncoerced(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        table=pq.read_table(self.parquet)
        rows=table.to_pylist()
        rows[0]["value_source"]="private_h5_mixed_stockday_candidate"
        pq.write_table(pa.Table.from_pylist(
            rows,schema=M.STAGER.candidate_schema(pa)),self.parquet)
        self.manifest["partitions"]["2026"]["sha256"]=M.STAGER.sha(self.parquet)
        self.mf.write_bytes(json.dumps(self.manifest).encode())
        self.doc["manifest_sha256"]=M.STAGER.sha(self.mf)
        self.full["source_private_manifest_sha256"]=self.doc["manifest_sha256"]
        selected,_,_=M.verified_candidate_selection(
            self.candidate_safe,self.full,2026,SYM,
            __import__("datetime").date(2026,9,30),
            __import__("datetime").date(2026,10,13))
        self.assertEqual(len(selected[SYM[0]]["private_h5_mixed_stockday_candidate"]),1)

    def test_optin_shared_purchased_rowgroups_integrates_with_private_view(self):
        def shared(root,symbols,first,last,*budgets):
            self.assertEqual(list(symbols),list(SYM))
            self.assertEqual((first,last),(START,END))
            return {
                "bars_by_symbol":{sym:[bar(sym,START)] for sym in symbols},
                "safe_summary":{
                    "state":"one_physical_purchased_rowgroup_scan_per_requested_batch",
                    "requested_stock_count":2,
                    "shared_physical_source_rows_scanned":400,
                    "shared_physical_candidate_rowgroups":1,
                    "original_market_files_written":False,
                    "original_h5_opened":False,
                    "purchased_values_modified":False,
                },
            }
        with patch.object(M.SHARED,"query_bars",side_effect=shared) as batched:
            result=self.run_it(purchased_shared_rowgroups=True)
        self.mocks[6].assert_not_called()
        batched.assert_called_once()
        self.assertEqual(result["safe_summary"]["returned_stockday_rows"],10)
        self.assertEqual(result["safe_summary"]["purchased_parquet_rows"],2)
        self.assertEqual(result["safe_summary"]["whole_h5_candidate_rows"],8)
        self.assertEqual(result["safe_summary"]["purchased_source_rows_scanned"],400)
        self.assertTrue(result["safe_summary"]["purchased_shared_rowgroup_batch_used"])
        self.assertTrue(result["safe_summary"][
            "purchased_source_rows_scanned_means_unique_physical_rows"])
        self.assertFalse(result["safe_summary"]["ready_for_automatic_market_merge"])

    def test_forged_shared_purchased_summary_fails_before_any_output(self):
        with patch.object(M.SHARED,"query_bars",return_value={
            "bars_by_symbol":{sym:[bar(sym,START)] for sym in SYM},
            "safe_summary":{
                "state":"one_physical_purchased_rowgroup_scan_per_requested_batch",
                "requested_stock_count":2,
                "shared_physical_source_rows_scanned":400,
                "shared_physical_candidate_rowgroups":1,
                "original_market_files_written":True,
                "original_h5_opened":False,
                "purchased_values_modified":False,
            }}):
            with self.assertRaisesRegex(ValueError,"not trusted"):
                self.run_it(purchased_shared_rowgroups=True)
        self.assertFalse(self.out.exists())

    def test_wrong_original_source_flag_rejected_before_merge(self):
        def badp(*a,**k):
            return {"bars":[],"safe_summary":{
                "source_rows_scanned":1,
                "source_market_files_modified":True,
                "no_h5_read":True,"no_automatic_gaps_fill":True}}
        with patch.object(M.P,"query_bars",side_effect=badp):
            with self.assertRaisesRegex(ValueError,"not trusted"):
                self.run_it()
        self.assertFalse(self.out.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
