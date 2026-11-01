"""Synthetic immutable all16 private DAY receipt and stockday-year gate tests."""
import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"
spec=importlib.util.spec_from_file_location(
    "private_all16_version_synthetic",
    TOOLS/"certify-private-2011-2026-physical-version-readonly.py")
U=importlib.util.module_from_spec(spec)
spec.loader.exec_module(U)


class PrivateAll16VersionTests(unittest.TestCase):
    def setUp(self):
        temp_root=HERE.parent/"work"/"_union_scratch"
        temp_root.mkdir(parents=True,exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=temp_root,prefix="all16-")
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.reports=self.root/"reports"
        self.reports.mkdir()
        self.batch=self.reports/"historical-batch.json"
        self.target=self.reports/"private-16yr.json"
        self.accepted16=self.reports/"recovered-2016.json"
        self.audit16=self.reports/"recovered-2016-audit.json"
        self.accepted26=self.reports/"physical-2026.json"
        self.audit26=self.reports/"physical-2026-audit.json"
        self.candidate=self.reports/"candidate.json"
        self.candidate.write_text('{"candidate":"fixed"}',encoding="utf-8")
        self.anchors={
            "accepted_2016_recovery_safe_sha256":None,
            "accepted_2016_independent_audit_sha256":None,
            "accepted_2026_materialization_safe_sha256":None,
            "accepted_2026_independent_audit_sha256":None,
            "source_h5_candidate_safe_sha256":"c"*64,
        }
        self.sources={}
        self.material={}
        self.indexes={}
        self.audits={}
        for year in range(2011,2027):
            if year==2016:
                material=self.accepted16
                audit=self.audit16
            elif year==2026:
                material=self.accepted26
                audit=self.audit26
            else:
                material=self.reports/f"remaining14-44edd84e21ee-{year}-physical.json"
                audit=self.reports/f"remaining14-44edd84e21ee-{year}-independent.json"
            self.material[year]=material
            self.audits[year]=audit
            purchased=(U.B.PURCHASED_2016_YEAR if year==2016
                       else U.B.PURCHASED_2026_NINE_MONTHS if year==2026
                       else (U.B.EXPECTED_OTHER14_ROWS if year==2011 else 0))
            h5=(1 if year==2016 else 22273 if year==2026 else 0)
            # All source receipts synthetic; the all-16 conservation gate
            # is exercised using real, consistent synthetic annual data.
            doc={
                "year":year,"purchased_original_rows":purchased,
                "h5_mixed_candidate_rows":h5,
                "total_private_physical_rows":purchased+h5,
                "source_candidate_safe_sha256":"c"*64,
                "private_manifest_sha256":f"{year:064x}",
                "private_sqlite_sha256":f"{year+1:064x}",
                "private_relative_directory":
                    f"work/unified_parquet/physical_years/physical_{year}_44edd84e21ee",
                "source_purchased_original_parquet_sha256":f"{year+2:064x}",
            }
            if year==2026:
                doc["private_stockday_unique_index_sha256"]=doc["private_sqlite_sha256"]
                doc["source_private_candidate_safe_sha256"]="c"*64
            material.write_text(json.dumps(doc)+"\n",encoding="utf-8")
            source_sha=U.M.ST.sha(material)
            self.sources[year]=doc
            audit_doc={
                "status":"independent_historical_private_physical_year_all_rows_sha_and_keys_verified",
                "year":year,
                "source_materialization_safe_sha256":source_sha,
                "source_private_manifest_sha256":doc["private_manifest_sha256"],
                "private_purchased_rows_verified":purchased,
                "private_h5_mixed_candidate_rows_verified":h5,
                "private_total_rows_verified":purchased+h5,
                "original_float64_roundtrip_fingerprint_verified":True,
                "candidate_source_units_certified":False,
                "ready_for_production_query":False,
                "ready_for_automatic_market_merge":False,
                "ready_for_h5_mirror":False,
                "original_market_files_written":False,
                "private_or_production_active_pointer_modified":False,
            }
            if year==2026:
                audit_doc.update({
                    "status":"independent_full_2026_private_physical_parquet_sha_values_keys_verified",
                    "private_purchased_records_verified":purchased,
                    "private_h5_whole_candidate_rows_verified":22191,
                    "private_h5_mixed_candidate_rows_verified":82,
                    "private_total_stockday_rows_verified":purchased+h5,
                    "source_private_physical_manifest_sha256":doc["private_manifest_sha256"],
                    "quarantined_2026_07_16_stockday_bars_not_included":5,
                    "original_market_files_modified":False,
                })
            audit.write_text(json.dumps(audit_doc)+"\n",encoding="utf-8")
            self.indexes[year]=self.root/f"mock-{year}.sqlite3"
        for year,k in [(2016,"accepted_2016"),(2026,"accepted_2026")]:
            self.anchors[f"{k}_{'recovery_safe' if year==2016 else 'materialization_safe'}_sha256"]=U.M.ST.sha(self.material[year])
            self.anchors[f"{k}_independent_audit_sha256"]=U.M.ST.sha(self.audits[year])
        annual={}
        for year in U.B.YEARS:
            doc=self.sources[year]
            annual[str(year)]={
                "private_relative_directory":doc["private_relative_directory"],
                "purchased_rows":doc["purchased_original_rows"],
                "original_purchased_sha256":doc["source_purchased_original_parquet_sha256"],
                "materialization_safe_sha256":U.M.ST.sha(self.material[year]),
                "independent_audit_sha256":U.M.ST.sha(self.audits[year]),
                "private_manifest_sha256":doc["private_manifest_sha256"],
            }
        self.batch_doc={
            "format":U.B.BATCH_FORMAT,
            "status":"all_14_historical_purchased_years_independently_verified_private_not_activated",
            "batch_id":"44edd84e21ee",
            "year_count":14,
            "years":list(U.B.YEARS),
            "historical_purchased_rows_verified":U.B.EXPECTED_OTHER14_ROWS,
            "all_years_independent_full_row_sha_and_key_verified":True,
            "annual":annual,
            "anchors":self.anchors,
            "original_market_files_written":False,
            "private_or_production_active_pointer_modified":False,
            "candidate_source_units_certified":False,
            "ready_for_production_query":False,
            "ready_for_automatic_market_merge":False,
            "ready_for_h5_mirror":False,
        }
        self.batch.write_text(json.dumps(self.batch_doc)+"\n",encoding="utf-8")
        self.batch_sha=U.M.ST.sha(self.batch)

    def historical_source(self,path):
        p=Path(path)
        obj=json.loads(p.read_text())
        year=obj["year"]
        return (obj,U.M.ST.sha(p),
                self.root/obj["private_relative_directory"],
                self.root/f"{year}-manifest.json",
                self.indexes[year],{})

    def source2026(self,path):
        return self.historical_source(path)

    def fake_index(self,index,year,expected):
        return expected

    def under_patches(self):
        from contextlib import ExitStack
        stack=ExitStack()
        for obj,key,value in (
            (U.M,"MODULE",self.root),
            (U.M,"REPORTS",self.reports),
            (U.H,"source",self.historical_source),
            (U.Y,"source_report",self.source2026),
            (U.B,"fixed_anchors",lambda *args:self.anchors),
            (U,"open_index_readonly",self.fake_index),
        ):
            stack.enter_context(patch.object(obj,key,value))
        return stack

    def run_all16(self,sha=None):
        return U.certify(self.batch,sha or self.batch_sha,
                         self.accepted16,self.audit16,
                         self.accepted26,self.audit26,
                         self.candidate,self.target)

    def test_complete_16_disjoint_years_and_14137981_rows_publish_private_only(self):
        with self.under_patches():
            result=self.run_all16()
        self.assertEqual(result["year_count"],16)
        self.assertEqual(result["purchased_original_records"],14115707)
        self.assertEqual(result["verified_h5_only_gap_records"],22274)
        self.assertEqual(result["private_total_stockday_records"],14137981)
        self.assertEqual(set(result["annual"]),{str(y) for y in range(2011,2027)})
        self.assertTrue(result["cross_year_stockday_key_ranges_disjoint"])
        self.assertFalse(result["ready_for_h5_mirror"])
        self.assertFalse(result["private_physical_parquet_or_sqlite_written"])
        self.assertTrue(self.target.exists())

    def test_batch_receipt_sha_tamper_refuses_before_private_version_publication(self):
        with self.under_patches():
            with self.assertRaisesRegex(ValueError,"accepted original 14-year batch"):
                self.run_all16("0"*64)
        self.assertFalse(self.target.exists())

    def test_mutated_2026_audit_sha_refuses_private_version(self):
        a=json.loads(self.audit26.read_text())
        a["ready_for_h5_mirror"]=True
        self.audit26.write_text(json.dumps(a)+"\n")
        with self.under_patches():
            with self.assertRaisesRegex(ValueError,"2026 private independent receipt"):
                self.run_all16()
        self.assertFalse(self.target.exists())

    def test_mutated_single_annual_audit_fails_closed_without_private_version(self):
        y=2019
        a=json.loads(self.audits[y].read_text())
        a["private_purchased_rows_verified"]=999
        self.audits[y].write_text(json.dumps(a)+"\n")
        with self.under_patches():
            with self.assertRaisesRegex(ValueError,"Annual independent full-row"):
                self.run_all16()
        self.assertFalse(self.target.exists())

    def test_unknown_or_changed_2016_anchor_refused(self):
        self.anchors["accepted_2016_recovery_safe_sha256"]="0"*64
        with self.under_patches():
            with self.assertRaisesRegex(ValueError,"Accepted 2016 recovered evidence"):
                self.run_all16()
        self.assertFalse(self.target.exists())

    def test_real_readonly_stockday_index_rejects_cross_year_day_key(self):
        idx=self.root/"real.sqlite3"
        c=sqlite3.connect(idx)
        c.execute("CREATE TABLE stockday(year INTEGER NOT NULL,symbol TEXT,"
                  "trading_date TEXT,kind TEXT,PRIMARY KEY(year,symbol,trading_date))")
        c.execute("INSERT INTO stockday VALUES (?,?,?,?)",
                  (2017,"SH600000","2016-06-01","purchased_parquet"))
        c.commit()
        c.close()
        with self.assertRaisesRegex(ValueError,"out-of-year"):
            U.open_index_readonly(idx,2017,1)

    def test_real_readonly_stockday_index_accepts_disjoint_valid_year(self):
        idx=self.root/"real.sqlite3"
        c=sqlite3.connect(idx)
        c.execute("CREATE TABLE stockday(year INTEGER NOT NULL,symbol TEXT,"
                  "trading_date TEXT,kind TEXT,PRIMARY KEY(year,symbol,trading_date))")
        c.execute("INSERT INTO stockday VALUES (?,?,?,?)",
                  (2017,"SH600000","2017-06-01","purchased_parquet"))
        c.commit()
        c.close()
        self.assertEqual(U.open_index_readonly(idx,2017,1),1)


if __name__=="__main__":
    unittest.main(verbosity=2)
