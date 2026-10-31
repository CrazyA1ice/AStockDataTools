"""Synthetic combined-22274 stockday materialization, v1 reader compatibility."""
import importlib.util
import json
import tempfile
import unittest
from datetime import date,datetime
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M=load("combined_22274_materializer_test",TOOLS/"materialize-private-combined-day-22274-snapshot.py")
READER=load("combined_22274_snapshot_v1_reader_test",TOOLS/"read-private-unified-day-parquet-snapshot.py")
SYM=("SH600000","SZ000001")
VERSION="e"*64


def bar(sym,day,source):
    ts=int(datetime.fromisoformat(day+"T00:00:00+08:00").timestamp()*1000)
    return {"symbol":sym,"period":"day","trading_date":day,
            "source_timestamp_ms":ts,"open":10.0,"high":11.0,
            "low":9.0,"close":10.5,"volume":100.0,"amount":1000.0,
            "value_source":source}


def fake_result(mixed=False):
    rows={}
    for symbol in SYM:
        rows[symbol]=[
            bar(symbol,"2026-09-30","purchased_parquet"),
            bar(symbol,"2026-10-08","private_h5_whole_date_candidate"),
            bar(symbol,"2026-10-09","private_h5_whole_date_candidate"),
            bar(symbol,"2026-10-12","private_h5_whole_date_candidate"),
            bar(symbol,"2026-10-13","private_h5_mixed_stockday_candidate"
                if mixed else "private_h5_whole_date_candidate"),
        ]
    return {"bars_by_symbol":rows,"safe_summary":{
        "format":M.BATCH.FORMAT,
        "state":"explicit_private_combined_day_batch_one_live_gate_passed",
        "private_combined_version_sha256":VERSION,
        "candidate_total_new_stockday_rows_in_immutable_version":22274,
        "full_live_market_keyset_audit_count":1,
        "requested_stock_count":2,
        "same_year_bounded_query":True,
        "quarantined_2026_07_16_stockday_bars_not_included":5,
        "no_raw_ohlcva_or_symbols_in_safe":True,
        "source_priority":"purchased_parquet_first_exact_stockday_fail_closed_on_overlap",
        "source_market_files_written":False,
        "purchased_parquet_replaced":False,
        "private_or_production_active_pointer_modified":False,
        "h5_mirror_created":False,
        "candidate_source_units_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "full_live_recheck_safe_sha256":"f"*64,
        "query_result_stockday_bars":10,
        "purchased_parquet_bars":2,
        "whole_h5_only_candidate_bars":6 if mixed else 8,
        "mixed_h5_only_candidate_bars":2 if mixed else 0,
    }}


class CombinedSnapshotTests(unittest.TestCase):
    def test_whole_only_purchased_priority_exact_counts(self):
        rows,counters,per=M.transform(fake_result(),SYM,"2026-09-30","2026-10-13",VERSION)
        self.assertEqual(len(rows),10)
        self.assertEqual(counters["purchased_parquet"],2)
        self.assertEqual(counters["private_h5_whole_date_candidate"],8)
        self.assertEqual(per["SH600000"]["private_bars"],4)
        self.assertEqual(rows[0]["value_source"],"purchased_parquet")
        self.assertEqual(sum(r["value_source"]=="private_hikyuu_h5_gap_candidate" for r in rows),8)

    def test_mixed_lineage_stays_visible_in_counts(self):
        rows,counters,per=M.transform(fake_result(mixed=True),SYM,
            "2026-09-30","2026-10-13",VERSION)
        self.assertEqual(counters["private_h5_whole_date_candidate"],6)
        self.assertEqual(counters["private_h5_mixed_stockday_candidate"],2)
        self.assertEqual(per["SZ000001"]["private_bars"],4)

    def test_reject_forged_unvalidated_full_gate(self):
        r=fake_result()
        r["safe_summary"]["full_live_market_keyset_audit_count"]=0
        with self.assertRaisesRegex(ValueError,"qualifying live gate"):
            M.transform(r,SYM,"2026-09-30","2026-10-13",VERSION)

    def test_reject_unauthorized_source_label(self):
        r=fake_result()
        r["bars_by_symbol"][SYM[0]][0]["value_source"]="unverified_external"
        with self.assertRaisesRegex(ValueError,"provenance"):
            M.transform(r,SYM,"2026-09-30","2026-10-13",VERSION)

    def test_reject_duplicate_purchased_and_private_stockday(self):
        r=fake_result()
        r["bars_by_symbol"][SYM[0]][1]["trading_date"]="2026-09-30"
        r["bars_by_symbol"][SYM[0]][1]["source_timestamp_ms"]=r["bars_by_symbol"][SYM[0]][0]["source_timestamp_ms"]
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            M.transform(r,SYM,"2026-09-30","2026-10-13",VERSION)

    def test_reject_missing_candidate_row_with_false_source_totals(self):
        r=fake_result()
        r["bars_by_symbol"][SYM[0]].pop()
        with self.assertRaisesRegex(ValueError,"totals"):
            M.transform(r,SYM,"2026-09-30","2026-10-13",VERSION)

    def test_reject_wrong_immutable_version(self):
        with self.assertRaisesRegex(ValueError,"qualifying live gate"):
            M.transform(fake_result(),SYM,"2026-09-30","2026-10-13","a"*64)

    def test_reject_stale_or_false_certification(self):
        r=fake_result()
        r["safe_summary"]["candidate_source_units_certified"]=True
        with self.assertRaisesRegex(ValueError,"qualifying live gate"):
            M.transform(r,SYM,"2026-09-30","2026-10-13",VERSION)

    def test_reject_mismatched_h5_subcategory_count(self):
        r=fake_result(mixed=True)
        r["safe_summary"]["mixed_h5_only_candidate_bars"]=0
        with self.assertRaisesRegex(ValueError,"totals"):
            M.transform(r,SYM,"2026-09-30","2026-10-13",VERSION)

    def test_reject_nonfloat64_source_value(self):
        r=fake_result()
        r["bars_by_symbol"][SYM[0]][0]["amount"]=1000
        with self.assertRaisesRegex(ValueError,"float64"):
            M.transform(r,SYM,"2026-09-30","2026-10-13",VERSION)

    def test_real_arrow_parquet_roundtrip_then_established_reader(self):
        import pyarrow
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            folder=root/"work"/"unified_parquet"/"snapshots"/"snapshot_abcdef012345"
            reports=root/"reports"
            reports.mkdir()
            fresh=reports/"fresh.json"
            batch=reports/"batch.json"
            safe=reports/"snapshot.json"
            read_safe=reports/"read.json"
            data=fake_result(mixed=True)
            def fake_query(*args,**kwargs):
                # The real batched query persists only aggregate SAFE to disk.
                batch.write_text('{"safe":true}\n',encoding="utf-8")
                fresh.write_text('{"source":true}\n',encoding="utf-8")
                return data
            with patch.object(M.BASE,"MODULE",root),\
                 patch.object(M.BASE,"safe_paths",return_value=(folder,safe)),\
                 patch.object(M.BATCH.PRE,"new_report",side_effect=lambda x:Path(x)),\
                 patch.object(M.BATCH,"checked_requests",return_value=(
                     list(SYM),date(2026,9,30),date(2026,10,13))),\
                 patch.object(M.BATCH,"query_batch",side_effect=fake_query) as q:
                result=M.materialize(root,list(SYM),"2026-09-30","2026-10-13",
                    VERSION,None,None,None,None,None,None,fresh,batch,folder,safe)
                self.assertEqual(result["purchased_rows"],2)
                self.assertEqual(result["whole_date_h5_candidate_rows"],6)
                self.assertEqual(result["mixed_date_h5_candidate_rows"],2)
                q.assert_called_once()
            manifest=json.loads((folder/"manifest.json").read_text())
            self.assertEqual(manifest["mixed_date_h5_candidate_rows"],2)
            self.assertFalse(manifest["production_h5_mirror_created"])
            with patch.object(READER,"MODULE",root),\
                 patch.object(READER,"WORK",root/"work"),\
                 patch.object(READER,"ROOT",folder.parent),\
                 patch.object(READER,"REPORTS",reports):
                loaded=READER.read_verified(safe,list(SYM),
                    "2026-09-30","2026-10-13",read_safe)
            self.assertEqual(loaded["safe_summary"]["snapshot_total_rows_verified"],10)
            self.assertEqual(loaded["safe_summary"]["selected_purchased_row_count"],2)
            self.assertEqual(loaded["safe_summary"]["selected_h5_gap_candidate_row_count"],8)
            self.assertTrue(loaded["safe_summary"]["no_live_market_source_freshness_recheck"])
            self.assertTrue(read_safe.is_file())

    def test_invalid_output_prevents_live_query(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            with patch.object(M.BASE,"safe_paths",side_effect=ValueError("Unsafe output")),\
                 patch.object(M.BATCH,"query_batch") as q:
                with self.assertRaisesRegex(ValueError,"Unsafe output"):
                    M.materialize(root,list(SYM),"2026-09-30","2026-10-13",VERSION,
                                  None,None,None,None,None,None,None,None,None,None)
                q.assert_not_called()


if __name__=="__main__":
    unittest.main(verbosity=2)
