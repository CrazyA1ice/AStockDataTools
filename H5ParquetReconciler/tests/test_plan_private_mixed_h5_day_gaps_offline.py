"""Synthetic-only 2016/2026 mixed-date H5 gap gate, no raw commercial sources."""
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(label,path):
    spec=importlib.util.spec_from_file_location(label,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M=load("mixed_h5_day_safe_gate",
       HERE.parent/"tools"/"plan-private-mixed-h5-day-gaps-offline.py")
FULL=load("mixed_h5_day_full_history_fixture",
          HERE/"test_plan_parquet_primary_full_history_day_offline.py")


def source(year):
    obj=FULL.annual(year)
    sec=obj["results"][f"day/{year}"]
    first=sec["by_day"][f"{year}0930"]
    sec["by_day"]={f"{year}0930":first}
    sec["h5_rows"]=3
    sec["h5_only_rows"]=0
    if year==2016:
        first["h5_unique"]=4
        first["h5_only"]=1
        first["union_candidate_unique"]=5
        sec["h5_rows"]=4
        sec["h5_only_rows"]=1
    if year==2026:
        first["h5_unique"]=85
        first["h5_only"]=82
        first["union_candidate_unique"]=86
        mixed={
            "h5_unique":7,"parquet_unique":2,"matched":2,
            "h5_only":5,"pq_only":0,"value_mismatch":1,
            "price_mismatch":1,"intersection_unique":2,"union_candidate_unique":7,
        }
        wholly={
            "h5_unique":22191,"parquet_unique":0,"matched":0,
            "h5_only":22191,"pq_only":0,"value_mismatch":0,
            "intersection_unique":0,"union_candidate_unique":22191,
        }
        sec["by_day"][f"{year}1001"]=mixed
        sec["by_day"][f"{year}1008"]=wholly
        sec["h5_rows"]=22283
        sec["pq_rows"]=6
        sec["matched_keys"]=5
        sec["h5_only_rows"]=22278
        sec["pq_only_rows"]=1
        sec["value_mismatch_rows"]=3
        sec["quantity_mismatch_rows"]=3
        sec["price_mismatch_rows"]=1
    return obj


def example():
    raw={}
    inputs=[]
    for year in FULL.M.YEARS:
        obj=source(year)
        payload=json.dumps(obj,sort_keys=True).encode()
        name=f"day-{year}-safe.json"
        raw[name]=payload
        inputs.append((name,payload))
    ledger=FULL.M.plan_reports(inputs,"2026-10-31")
    return json.dumps(ledger,sort_keys=True).encode(),{
        k:v for k,v in raw.items()
        if k in ("day-2016-safe.json","day-2026-safe.json")
    }


class MixedCandidateOfflineGateTests(unittest.TestCase):
    def test_88_candidates_and_price_disagreement_5_rows_quarantined(self):
        ledger,reports=example()
        result=M.analyze(ledger,reports)
        self.assertEqual(result["remaining_mixed_date_h5_only_stockday_candidates"],88)
        self.assertEqual(result["eligible_for_next_live_key_recheck_only"],83)
        self.assertEqual(result["quarantined_pending_price_disagreement_review"],5)
        self.assertEqual(result["full_history_complete_day_candidates_already_separately_handled"],22191)
        self.assertEqual(result["years_with_mixed_date_gaps"],[2016,2026])
        self.assertFalse(result["safe_to_automatically_stage_promote_or_mirror"])

    def test_year_date_classification_avoids_whole_day_stager(self):
        ledger,reports=example()
        result=M.analyze(ledger,reports)
        counts=[[(x["date"],x["h5_only_stockday_candidate_rows"],x["status"])
                 for x in y["mixed_date_candidates"]] for y in result["years"]]
        self.assertEqual(counts[0],[("2016-09-30",1,
                                     "candidate_requires_exact_stockday_live_recheck")])
        self.assertEqual(counts[1][0][1],82)
        self.assertEqual(counts[1][1][1],5)
        self.assertEqual(counts[1][1][2],"quarantined_same_day_price_disagreement")
        self.assertFalse(any(x["date"]=="2026-10-08" for x in
                            result["years"][1]["mixed_date_candidates"]))
        self.assertTrue(result["whole_day_stager_must_not_accept_mixed_dates"])

    def test_raw_symbols_ohlcva_and_absolute_paths_never_exported(self):
        ledger,reports=example()
        doc=M.analyze(ledger,reports)
        encoded=json.dumps(doc)
        self.assertNotIn("SH600000",encoded)
        self.assertNotIn("D:\\",encoded)
        self.assertNotIn("source_timestamp_ms",encoded)
        self.assertTrue(doc["actual_stock_symbols_or_ohlcva_exported"] is False)
        self.assertTrue(doc["market_source_files_read_by_this_offline_gate"] is False)

    def test_changed_2016_source_sha_rejected(self):
        ledger,reports=example()
        reports["day-2016-safe.json"]+=b" "
        with self.assertRaisesRegex(ValueError,"SHA"):
            M.analyze(ledger,reports)

    def test_changed_2026_source_sha_rejected(self):
        ledger,reports=example()
        reports["day-2026-safe.json"]+=b" "
        with self.assertRaisesRegex(ValueError,"SHA"):
            M.analyze(ledger,reports)

    def test_removed_or_duplicate_year_source_rejected(self):
        ledger,reports=example()
        with self.assertRaisesRegex(ValueError,"two distinct"):
            M.analyze(ledger,{next(iter(reports)):next(iter(reports.values()))})
        with self.assertRaisesRegex(ValueError,"two distinct"):
            M.analyze(ledger,{})

    def test_missing_historical_year_or_false_merged_status_rejected(self):
        ledger,reports=example()
        for key,value in (("annual_exact_day_audits_accepted",15),
                          ("full_2011_to_2026_as_of_source_key_coverage_audited",False),
                          ("historical_unified_parquet_materialized",True),
                          ("ready_to_automatically_union_or_mirror",True)):
            obj=json.loads(ledger)
            obj[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):
                M.analyze(json.dumps(obj).encode(),reports)

    def test_wrong_total_mixed_or_complete_count_is_blocked(self):
        ledger,reports=example()
        for field in ("h5_only_mixed_date_candidates",
                      "h5_only_complete_absent_date_candidates"):
            obj=json.loads(ledger)
            obj["audited_totals_only_for_accepted_years"][field]+=1
            with self.subTest(field=field), self.assertRaisesRegex(
                    ValueError,"totals inconsistent"):
                M.analyze(json.dumps(obj).encode(),reports)

    def test_original_2016_by_day_corruption_fails_even_after_rehashed_ledger(self):
        ledger,reports=example()
        target=json.loads(reports["day-2016-safe.json"])
        target["results"]["day/2016"]["by_day"]["20160930"]["h5_only"]=2
        payload=json.dumps(target,sort_keys=True).encode()
        reports["day-2016-safe.json"]=payload
        entry=json.loads(ledger)
        entry["yearly_exact_source_coverage"][5]["audit_source_report_sha256"]=hashlib.sha256(payload).hexdigest()
        with self.assertRaises(ValueError):
            M.analyze(json.dumps(entry).encode(),reports)

    def test_replaced_year_filename_cannot_bypass_sha_binding(self):
        ledger,reports=example()
        reports["alias-2016.json"]=reports.pop("day-2016-safe.json")
        with self.assertRaisesRegex(ValueError,"SHA-linked"):
            M.analyze(ledger,reports)

    def test_no_stock_day_staging_or_promotion_authorized_by_plan(self):
        ledger,reports=example()
        doc=M.analyze(ledger,reports)
        self.assertFalse(doc["unified_parquet_or_h5_mirror_created"])
        self.assertFalse(doc["private_stage_or_overlay_pointer_modified"])
        self.assertFalse(doc["original_market_files_modified"])
        self.assertFalse(doc["license_or_unit_conversion_certified"])

    def test_main_works_only_inside_module_reports_and_refuses_overwrite(self):
        ledger,reports=example()
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)/"H5ParquetReconciler"/"reports"
            directory.mkdir(parents=True)
            ledgerpath=directory/"history.json"
            s2016=directory/"day-2016-safe.json"
            s2026=directory/"day-2026-safe.json"
            out=directory/"plan.json"
            ledgerpath.write_bytes(ledger)
            s2016.write_bytes(reports[s2016.name])
            s2026.write_bytes(reports[s2026.name])
            with patch.object(M,"REPORTS",directory):
                M.main(["--history-ledger",str(ledgerpath),
                        "--source-2016",str(s2016),"--source-2026",str(s2026),
                        "--out",str(out),"--offline-reports-only"])
                saved=json.loads(out.read_text(encoding="utf-8"))
                self.assertEqual(saved["eligible_for_next_live_key_recheck_only"],83)
                self.assertEqual(saved["quarantined_pending_price_disagreement_review"],5)
                with self.assertRaises(SystemExit):
                    M.main(["--history-ledger",str(ledgerpath),
                            "--source-2016",str(s2016),"--source-2026",str(s2026),
                            "--out",str(out),"--offline-reports-only"])
                with self.assertRaises(ValueError):
                    M.valid_path(Path(root)/"elsewhere.json")
            self.assertEqual(hashlib.sha256(ledgerpath.read_bytes()).hexdigest(),
                             saved["full_history_ledger_sha256"])


if __name__=="__main__":
    unittest.main(verbosity=2)
