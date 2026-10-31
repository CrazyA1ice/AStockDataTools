"""Synthetic historical purchased DAY 2015 and 2016+one verified H5 gap."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"


def load(label,file):
    spec=importlib.util.spec_from_file_location(label,TOOLS/file)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M=load("historical_purchased_day_builder_tests",
       "materialize-private-2011-2025-purchased-year.py")
V=load("historical_purchased_day_independent_tests",
       "verify-private-2011-2025-purchased-year.py")
R=load("historical_2016_existing_orphan_recovery_tests",
       "recover-private-2016-historical-orphan-readonly.py")
D=load("historical_2016_readonly_diagnosis_tests",
       "diagnose-private-2016-purchased-h5-readonly.py")


def ts(day):
    return int(datetime.fromisoformat(day+"T00:00:00+08:00").timestamp()*1000)


def paid(sym,day):
    return {"ts":ts(day),"symbol":sym,
            "open":10.0,"high":11.0,"low":9.0,"close":10.5,
            "volume":300.0,"amount":1000.0}


def h5(sym,day):
    return {**paid(sym,day),"trading_date":day,
            "value_source":"private_h5_mixed_stockday_candidate"}


class HistoricalPrivateAnnualTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        scratch=HERE.parent/"work"/"_union_scratch"
        scratch.mkdir(parents=True,exist_ok=True)
        t=tempfile.TemporaryDirectory(prefix="hist_2016_phys_",dir=scratch)
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.work=self.root/"work"/"unified_parquet"
        self.private_root=self.work/"physical_years"
        self.reports=self.root/"reports"
        self.reports.mkdir()
        self.purchased=self.root/"purchased"
        self.day=self.purchased/"day"
        self.day.mkdir(parents=True)
        self.readme=self.purchased/"【先看我】数据说明.txt"
        self.readme.write_bytes(b"synthetic README")
        self.qdc=self.purchased/"文件校验清单.txt"
        self.qdc.write_bytes(b"synthetic full manifest")
        self.readme_sha=hashlib.sha256(self.readme.read_bytes()).hexdigest()
        self.qdc_sha=hashlib.sha256(self.qdc.read_bytes()).hexdigest()
        purchased_schema=pa.schema([
            pa.field("ts",pa.int64()),pa.field("symbol",pa.string()),
            *(pa.field(f,pa.float64()) for f in M.PHYS.F),
        ])
        self.record={}
        self.sources={}
        for year,rows in [
            (2015,[paid("600001.XSHG","2015-08-17")]),
            (2016,[paid("600001.XSHG","2016-08-17"),
                   paid("000002.XSHE","2016-08-17")]),
        ]:
            p=self.day/f"{year}.parquet"
            pq.write_table(pa.Table.from_pylist(rows,schema=purchased_schema),p)
            self.record[year]={"size":p.stat().st_size,
                               "rows":len(rows),"sha":M.ST.sha(p)}
            self.sources[year]=p
        self.h5_dir=self.root/"source_candidates"/"year=2016"
        self.h5_dir.mkdir(parents=True)
        self.h5_file=self.h5_dir/"day.parquet"
        pq.write_table(pa.Table.from_pylist([
            h5("SH600002","2016-08-18")
        ],schema=M.ST.candidate_schema(pa)),self.h5_file)
        self.candidate_safe=self.reports/"source-safe.json"
        self.candidate_safe.write_bytes(b'{"source":"private_only"}\n')
        self.source_manifest=self.h5_dir.parent/"manifest.json"
        self.source_manifest.write_bytes(b'{"synthetic":true}\n')
        self.candidate_doc={
            "source_version_sha256":M.SOURCE_VERSION,
            "candidate_year_rows":{"2016":1,"2026":22273},
            "partition_sha256":{"2016":M.ST.sha(self.h5_file)},
            "manifest_sha256":M.ST.sha(self.source_manifest),
        }
        self.candidate_sha=hashlib.sha256(self.candidate_safe.read_bytes()).hexdigest()
        self.dir_for_year={}
        self.safes={}

    def mock_input(self,source,year,readme_sha,manifest_sha):
        self.assertEqual(Path(source),self.purchased)
        self.assertEqual(readme_sha,self.readme_sha)
        self.assertEqual(manifest_sha,self.qdc_sha)
        p=self.sources[year]
        return p,self.record[year],self.readme,self.qdc

    def source(self,path):
        self.assertEqual(Path(path),self.candidate_safe)
        return self.candidate_doc,self.candidate_sha,self.h5_dir.parent,self.source_manifest

    def full_gap(self,source,out):
        if getattr(self,"current_year",None)!=2016:
            raise AssertionError("Full 22,274-row H5 audit may only run for 2016")
        Path(out).write_bytes(b'{"all":22274,"offline":true}\n')
        return {"total_h5_only_day_candidates_verified":22274,
                "mixed_date_candidate_rows_verified":83,
                "partition_year_rows_verified":{"2016":1,"2026":22273},
                "candidate_source_units_certified":False}

    def build(self,year):
        self.current_year=year
        folder=self.private_root/f"physical_{year}_{year:012x}"
        gate=self.reports/f"history-gate-{year}.json"
        safe=self.reports/f"history-safe-{year}.json"
        with patch.object(M,"MODULE",self.root),\
             patch.object(M,"WORK",self.work),\
             patch.object(M,"ROOT",self.private_root),\
             patch.object(M,"REPORTS",self.reports),\
             patch.object(M,"purchased_input",side_effect=self.mock_input),\
             patch.object(M.V,"source",side_effect=self.source),\
             patch.object(M.V,"verify",side_effect=self.full_gap):
            result=M.materialize(
                year,self.purchased,self.candidate_safe,self.readme_sha,
                self.qdc_sha,folder,gate,safe)
        self.dir_for_year[year]=folder
        self.safes[year]=safe
        return result

    def check(self,year,out=None):
        target=out or self.reports/f"verified-{year}.json"
        with patch.object(V.M,"MODULE",self.root),\
             patch.object(V.M,"WORK",self.work),\
             patch.object(V.M,"ROOT",self.private_root),\
             patch.object(V.M,"REPORTS",self.reports):
            return V.verify(self.safes[year],target)

    def install_purchased_extension(self,year,extra_fields=1):
        import pyarrow as pa
        import pyarrow.parquet as pq
        rows=([paid("600001.XSHG","2016-08-17"),
               paid("000002.XSHE","2016-08-17")]
              if year==2016 else [paid("600001.XSHG","2015-08-17")])
        ext_names=[f"synthetic_vendor_extension_{i}" for i in range(extra_fields)]
        schema=pa.schema([
            pa.field("ts",pa.int64()),pa.field("symbol",pa.string()),
            *(pa.field(field,pa.float64()) for field in M.PHYS.F),
            *(pa.field(field,pa.string()) for field in ext_names),
        ])
        source_rows=[{**row,**{name:"opaque-private-metadata" for name in ext_names}}
                     for row in rows]
        src=self.sources[year]
        pq.write_table(pa.Table.from_pylist(source_rows,schema=schema),src)
        self.record[year]={"size":src.stat().st_size,
                           "rows":len(source_rows),"sha":M.ST.sha(src)}
        return src

    def test_2016_one_unclassified_vendor_field_keeps_byte_identical_private_shadow(self):
        src=self.install_purchased_extension(2016,1)
        r=self.build(2016)
        self.assertEqual(r["purchased_original_rows"],2)
        self.assertEqual(r["h5_mixed_candidate_rows"],1)
        self.assertEqual(r["unclassified_purchased_extra_field_count"],1)
        self.assertTrue(r["verbatim_original_purchased_extra_field_shadow_created"])
        self.assertFalse(r["unknown_extra_field_semantics_certified"])
        shadow=self.dir_for_year[2016]/"purchased"/"original-with-unclassified-extra.parquet"
        self.assertTrue(shadow.exists())
        self.assertEqual(shadow.read_bytes(),src.read_bytes())
        receipt=self.check(2016)
        self.assertTrue(receipt["private_verbatim_original_purchased_shadow_sha_verified"])
        self.assertTrue(receipt["private_byte_shadow_source_float64_rows_recompared"])
        self.assertEqual(receipt["private_unclassified_purchased_extra_field_count_verified"],1)
        self.assertEqual(receipt["private_total_rows_verified"],3)
        self.assertNotIn("synthetic_vendor_extension_0",self.safes[2016].read_text())

    def test_2016_unclassified_shadow_tamper_blocks_independent_safe(self):
        self.install_purchased_extension(2016,1)
        self.build(2016)
        shadow=self.dir_for_year[2016]/"purchased"/"original-with-unclassified-extra.parquet"
        shadow.write_bytes(shadow.read_bytes()+b"tampered")
        with self.assertRaisesRegex(ValueError,"archive SHA drift"):
            self.check(2016)
        self.assertFalse((self.reports/"verified-2016.json").exists())

    def test_2016_two_unclassified_fields_still_rejected_without_safe(self):
        self.install_purchased_extension(2016,2)
        with self.assertRaisesRegex(ValueError,"footer/schema mismatched"):
            self.build(2016)
        self.assertFalse((self.reports/"history-safe-2016.json").exists())

    def test_2015_one_unclassified_vendor_field_keeps_shadow_without_h5(self):
        src=self.install_purchased_extension(2015,1)
        r=self.build(2015)
        self.assertEqual(r["unclassified_purchased_extra_field_count"],1)
        self.assertEqual(r["h5_mixed_candidate_rows"],0)
        shadow=self.dir_for_year[2015]/"purchased"/"original-with-unclassified-extra.parquet"
        self.assertEqual(M.ST.sha(shadow),M.ST.sha(src))
        audited=self.check(2015)
        self.assertEqual(audited["private_purchased_rows_verified"],1)
        self.assertEqual(audited["private_unclassified_purchased_extra_field_count_verified"],1)

    def recover_without_rebuilding(self):
        folder=self.dir_for_year[2016]
        # The original CLI wrote all private data + manifest but failed only
        # when the final success SAFE was being rendered.
        self.safes[2016].unlink()
        out=self.reports/"recovered-historical-2016-safe.json"
        independent=self.reports/"recovered-historical-2016-audit.json"
        gate=self.reports/"recovered-h5-candidate-recheck.json"
        with patch.object(R.M,"MODULE",self.root),\
             patch.object(R.M,"WORK",self.work),\
             patch.object(R.M,"ROOT",self.private_root),\
             patch.object(R.M,"REPORTS",self.reports),\
             patch.object(R.M,"purchased_input",side_effect=self.mock_input),\
             patch.object(R.M.V,"source",side_effect=self.source),\
             patch.object(R.M.V,"verify",side_effect=self.full_gap),\
             patch.object(R.I.M,"MODULE",self.root),\
             patch.object(R.I.M,"WORK",self.work),\
             patch.object(R.I.M,"ROOT",self.private_root),\
             patch.object(R.I.M,"REPORTS",self.reports):
            v=R.recover(folder,self.purchased,self.candidate_safe,
                        self.readme_sha,self.qdc_sha,gate,out,independent)
        self.assertTrue(out.is_file())
        self.assertTrue(independent.is_file())
        self.assertEqual(v["private_h5_mixed_candidate_rows_verified"],1)
        self.assertEqual(v["private_purchased_rows_verified"],2)
        self.assertTrue(v["private_verbatim_original_purchased_shadow_sha_verified"])
        self.assertTrue(v["private_byte_shadow_source_float64_rows_recompared"])
        self.assertFalse(v["ready_for_h5_mirror"])
        self.assertFalse(v["ready_for_automatic_market_merge"])
        return v

    def test_2016_true_orphan_recovered_from_existing_manifest_without_rebuild(self):
        self.install_purchased_extension(2016,1)
        before=self.build(2016)
        folder=self.dir_for_year[2016]
        orig_parquet=folder/"purchased"/"day.parquet"
        extension=folder/"purchased"/"original-with-unclassified-extra.parquet"
        manifest=folder/"manifest.json"
        from hashlib import sha256
        hashes=[sha256(x.read_bytes()).hexdigest() for x in (orig_parquet,extension,manifest)]
        verified=self.recover_without_rebuilding()
        self.assertEqual(verified["private_total_rows_verified"],3)
        self.assertEqual(hashes,[sha256(x.read_bytes()).hexdigest()
                           for x in (orig_parquet,extension,manifest)])
        self.assertFalse(self.safes[2016].exists())
        self.assertEqual(before["total_private_physical_rows"],3)

    def test_2016_orphan_shadow_tamper_rejected_before_recovery_SAFE(self):
        self.install_purchased_extension(2016,1)
        self.build(2016)
        shadow=self.dir_for_year[2016]/"purchased"/"original-with-unclassified-extra.parquet"
        shadow.write_bytes(shadow.read_bytes()+b"tampered")
        self.safes[2016].unlink()
        with patch.object(R.M,"MODULE",self.root),\
             patch.object(R.M,"WORK",self.work),\
             patch.object(R.M,"ROOT",self.private_root),\
             patch.object(R.M,"REPORTS",self.reports),\
             patch.object(R.M,"purchased_input",side_effect=self.mock_input),\
             patch.object(R.M.V,"source",side_effect=self.source),\
             patch.object(R.M.V,"verify",side_effect=self.full_gap):
            with self.assertRaisesRegex(ValueError,"archive SHA mismatch"):
                R.recover(self.dir_for_year[2016],self.purchased,self.candidate_safe,
                          self.readme_sha,self.qdc_sha,
                          self.reports/"orphan-gate.json",
                          self.reports/"orphan-success.json",
                          self.reports/"orphan-audit.json")
        self.assertFalse((self.reports/"orphan-success.json").exists())

    def test_relative_private_year_and_reports_paths_resolve_before_manifest_SAFE(self):
        import os
        relative=lambda p:Path(os.path.relpath(p,Path.cwd()))
        test_year=2015
        folder=self.private_root/f"physical_{test_year}_{test_year:012x}"
        gate=self.reports/"history-gate-2015.json"
        safe=self.reports/"history-safe-2015.json"
        with patch.object(M,"MODULE",self.root),\
             patch.object(M,"WORK",self.work),\
             patch.object(M,"ROOT",self.private_root),\
             patch.object(M,"REPORTS",self.reports),\
             patch.object(M,"purchased_input",side_effect=self.mock_input),\
             patch.object(M.V,"source",side_effect=self.source),\
             patch.object(M.V,"verify",side_effect=self.full_gap):
            r=M.materialize(2015,self.purchased,self.candidate_safe,
                self.readme_sha,self.qdc_sha,
                relative(folder),relative(gate),relative(safe))
        self.assertTrue(safe.exists())
        self.assertEqual(r["year"],2015)
        self.assertEqual(r["total_private_physical_rows"],1)
        self.assertEqual(r["private_relative_directory"],
            folder.relative_to(self.root).as_posix())
        self.safes[2015]=safe
        v=self.check(2015)
        self.assertEqual(v["private_total_rows_verified"],1)

    def test_2016_purchased_two_and_one_h5_gap_exact_float64(self):
        r=self.build(2016)
        self.assertEqual(r["purchased_original_rows"],2)
        self.assertEqual(r["h5_mixed_candidate_rows"],1)
        self.assertEqual(r["total_private_physical_rows"],3)
        self.assertEqual(set(r["physical_partition_sha256"]),{"purchased","h5_gap_2016"})
        a=self.check(2016)
        self.assertEqual(a["private_purchased_rows_verified"],2)
        self.assertEqual(a["private_h5_mixed_candidate_rows_verified"],1)
        self.assertEqual(a["private_partition_files_verified"],2)
        self.assertTrue(a["original_float64_roundtrip_fingerprint_verified"])

    def test_2015_purchased_only_does_not_require_full_22274_decode(self):
        r=self.build(2015)
        self.assertEqual(r["total_private_physical_rows"],1)
        self.assertEqual(r["h5_mixed_candidate_rows"],0)
        self.assertEqual(set(r["physical_partition_sha256"]),{"purchased"})
        a=self.check(2015)
        self.assertEqual(a["private_total_rows_verified"],1)
        self.assertEqual(a["private_partition_files_verified"],1)
        self.assertFalse(a["original_h5_source_reopened"])

    def test_duplicate_2016_purchased_and_h5_stockday_rejected(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        pq.write_table(pa.Table.from_pylist([
            h5("SH600001","2016-08-17")
        ],schema=M.ST.candidate_schema(pa)),self.h5_file)
        self.candidate_doc["partition_sha256"]["2016"]=M.ST.sha(self.h5_file)
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            self.build(2016)
        self.assertFalse((self.reports/"history-safe-2016.json").exists())

    def test_modified_original_purchased_SHA_fails_before_writes(self):
        self.sources[2015].write_bytes(
            self.sources[2015].read_bytes()+b"modified")
        # Exercise actual source hash gate, not synthetic data import.
        with self.assertRaisesRegex(ValueError,"Original"):
            with patch.object(M.QDC,"parse_manifest",return_value={
                "2015.parquet":self.record[2015]}):
                M.purchased_input(self.purchased,2015,
                                  self.readme_sha,self.qdc_sha)
        self.assertFalse(self.private_root.exists())

    def test_private_written_partition_sha_tamper_rejected(self):
        self.build(2015)
        p=self.dir_for_year[2015]/"purchased"/"day.parquet"
        p.write_bytes(p.read_bytes()+b"modified")
        with self.assertRaisesRegex(ValueError,"SHA"):
            self.check(2015)
        self.assertFalse((self.reports/"verified-2015.json").exists())

    def test_fake_production_ready_safe_rejected(self):
        self.build(2015)
        safe=self.safes[2015]
        payload=json.loads(safe.read_bytes())
        payload["ready_for_h5_mirror"]=True
        safe.write_bytes(json.dumps(payload).encode())
        with self.assertRaisesRegex(ValueError,"Incomplete"):
            self.check(2015)

    def test_historical_unsafe_output_folder_rejected(self):
        with patch.object(M,"MODULE",self.root),\
             patch.object(M,"ROOT",self.private_root),\
             patch.object(M,"REPORTS",self.reports),\
             patch.object(M,"WORK",self.work):
            with self.assertRaisesRegex(ValueError,"fresh private"):
                M.locations(2016,self.root/"outside"/"physical_2016_abcdefabcdef",
                            self.reports/"gate.json",self.reports/"safe.json")

    def test_history_year_outside_received_bundle_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"2011..2025"):
            M.locations(2026,self.root/"x",self.root/"y",self.root/"z")

    def test_original_source_symbol_and_timestamp_preserved(self):
        x=M.PHYS.normalise(paid("600001.XSHG","2015-08-17"),
                           "purchased_parquet",year=2015)
        self.assertEqual(x["symbol"],"SH600001")
        self.assertEqual(x["source_symbol"],"600001.XSHG")
        self.assertEqual(x["ts"],ts("2015-08-17"))

    def test_repeated_private_year_never_overwritten(self):
        self.build(2015)
        with self.assertRaisesRegex(ValueError,"fresh private"):
            self.build(2015)

    def diagnose(self):
        out=self.reports/"diagnostic-only-2016.json"
        with patch.object(D,"REPORTS",self.reports),\
             patch.object(D.M,"purchased_input",side_effect=self.mock_input),\
             patch.object(D.M.V,"source",side_effect=self.source):
            result=D.inspect(self.purchased,self.candidate_safe,
                             self.readme_sha,self.qdc_sha,out)
        self.assertTrue(out.is_file())
        raw=out.read_text(encoding="utf-8")
        self.assertNotIn("SH600001",raw)
        self.assertNotIn("SH600002",raw)
        self.assertNotIn("2016-08-17",raw)
        self.assertNotIn("1000.0",raw)
        self.assertNotIn(str(self.purchased),raw)
        self.assertFalse(result["private_annual_parquet_or_sqlite_created"])
        self.assertFalse(result["ready_for_automatic_market_merge"])
        self.assertFalse(result["ready_for_h5_mirror"])
        return result

    def test_2016_readonly_diagnostic_proves_two_purchased_and_one_gap(self):
        result=self.diagnose()
        self.assertEqual(result["status"],"readonly_2016_historical_preflight_pass")
        self.assertEqual(result["purchased_rows_checked_before_refusal"],2)
        self.assertEqual(result["h5_candidate_rows_checked_before_refusal"],1)
        self.assertTrue(result["all_purchased_h5_candidate_stockdays_unique"])
        self.assertTrue(result["source_shas_and_stats_unchanged_after_complete_scan"])
        self.assertTrue(result["purchased_footer_row_count_matches_received_manifest"])
        self.assertTrue(result["purchased_required_fields_present"])
        self.assertEqual(result["purchased_missing_required_field_count"],0)
        self.assertEqual(result["purchased_additional_field_count"],0)
        self.assertTrue(result["purchased_required_arrow_types_match"])
        self.assertFalse(self.private_root.exists())

    def test_2016_readonly_diagnostic_detects_duplicate_without_stock_ids(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        pq.write_table(pa.Table.from_pylist([
            h5("SH600001","2016-08-17")
        ],schema=M.ST.candidate_schema(pa)),self.h5_file)
        self.candidate_doc["partition_sha256"]["2016"]=M.ST.sha(self.h5_file)
        result=self.diagnose()
        self.assertEqual(result["status"],"readonly_2016_historical_preflight_rejected")
        self.assertEqual(result["failure_stage"],"h5_candidate")
        self.assertEqual(result["failure_code"],"DUPLICATE_STOCKDAY")
        self.assertFalse(self.private_root.exists())

    def test_2016_readonly_diagnostic_classifies_malformed_readme_pin(self):
        out=self.reports/"malformed-pin-diagnostic.json"
        with patch.object(D,"REPORTS",self.reports):
            result=D.inspect(self.purchased,self.candidate_safe,
                             self.readme_sha+"abcdef",self.qdc_sha,out)
        self.assertEqual(result["failure_stage"],"input_source_sha")
        self.assertEqual(result["failure_code"],"INPUT_SHA256_PIN_FORMAT_INVALID")
        self.assertEqual(result["purchased_rows_checked_before_refusal"],0)
        self.assertFalse(result["private_annual_parquet_or_sqlite_created"])
        raw=out.read_text(encoding="utf-8")
        self.assertNotIn(str(self.purchased),raw)

    def test_2016_readonly_diagnostic_distinguishes_footer_rows(self):
        self.record[2016]["rows"]=3
        result=self.diagnose()
        self.assertEqual(result["failure_stage"],"purchased_footer")
        self.assertEqual(result["failure_code"],"PURCHASED_FOOTER_ROW_COUNT_MISMATCH")
        self.assertFalse(result["purchased_footer_row_count_matches_received_manifest"])
        self.assertTrue(result["purchased_required_fields_present"])
        self.assertEqual(result["purchased_additional_field_count"],0)
        self.assertFalse(self.private_root.exists())

    def test_2016_readonly_diagnostic_reports_unexpected_arrow_field_without_values(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        schema=pa.schema([
            pa.field("ts",pa.int64()),pa.field("symbol",pa.string()),
            *(pa.field(field,pa.float64()) for field in M.PHYS.F),
            pa.field("synthetic_additional_field",pa.int32()),
        ])
        rows=[{**paid("600001.XSHG","2016-08-17"),
               "synthetic_additional_field":1},
              {**paid("000002.XSHE","2016-08-17"),
               "synthetic_additional_field":2}]
        pq.write_table(pa.Table.from_pylist(rows,schema=schema),self.sources[2016])
        self.record[2016]["sha"]=M.ST.sha(self.sources[2016])
        self.record[2016]["size"]=self.sources[2016].stat().st_size
        result=self.diagnose()
        self.assertIsNone(result["failure_code"])
        self.assertIsNone(result["failure_stage"])
        self.assertEqual(result["status"],"readonly_2016_historical_preflight_pass")
        self.assertEqual(result["purchased_rows_checked_before_refusal"],2)
        self.assertEqual(result["h5_candidate_rows_checked_before_refusal"],1)
        self.assertTrue(result["purchased_extra_field_requires_byte_identical_private_original_shadow"])
        self.assertFalse(result["purchased_extra_field_business_semantics_certified"])
        self.assertTrue(result["purchased_footer_row_count_matches_received_manifest"])
        self.assertTrue(result["purchased_required_fields_present"])
        self.assertTrue(result["purchased_required_arrow_types_match"])
        self.assertEqual(result["purchased_additional_field_count"],1)
        self.assertEqual(result["purchased_missing_required_field_count"],0)
        self.assertFalse(self.private_root.exists())

    def test_2016_readonly_two_extra_fields_still_rejected(self):
        self.install_purchased_extension(2016,2)
        result=self.diagnose()
        self.assertEqual(result["failure_code"],"PURCHASED_ADDITIONAL_FIELDS_PRESENT")
        self.assertEqual(result["failure_stage"],"purchased_footer")
        self.assertEqual(result["purchased_additional_field_count"],2)
        self.assertFalse(self.private_root.exists())

    def test_2016_readonly_diagnostic_reports_missing_required_arrow_field(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        schema=pa.schema([
            pa.field("ts",pa.int64()),pa.field("symbol",pa.string()),
            *(pa.field(field,pa.float64()) for field in M.PHYS.F if field!="amount"),
        ])
        rows=[paid("600001.XSHG","2016-08-17"),
              paid("000002.XSHE","2016-08-17")]
        pq.write_table(pa.Table.from_pylist(rows,schema=schema),self.sources[2016])
        self.record[2016]["sha"]=M.ST.sha(self.sources[2016])
        self.record[2016]["size"]=self.sources[2016].stat().st_size
        result=self.diagnose()
        self.assertEqual(result["failure_code"],"PURCHASED_REQUIRED_FIELDS_MISSING")
        self.assertEqual(result["purchased_missing_required_field_count"],1)
        self.assertEqual(result["purchased_additional_field_count"],0)

    def test_2016_readonly_diagnostic_reports_wrong_required_arrow_type(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        schema=pa.schema([
            pa.field("ts",pa.int64()),pa.field("symbol",pa.string()),
            *(pa.field(field,pa.int64() if field=="volume" else pa.float64())
              for field in M.PHYS.F),
        ])
        rows=[{**paid("600001.XSHG","2016-08-17"),"volume":300},
              {**paid("000002.XSHE","2016-08-17"),"volume":300}]
        pq.write_table(pa.Table.from_pylist(rows,schema=schema),self.sources[2016])
        self.record[2016]["sha"]=M.ST.sha(self.sources[2016])
        self.record[2016]["size"]=self.sources[2016].stat().st_size
        result=self.diagnose()
        self.assertEqual(result["failure_code"],"PURCHASED_REQUIRED_FIELD_TYPES_MISMATCH")
        self.assertEqual(result["purchased_missing_required_field_count"],0)
        self.assertEqual(result["purchased_additional_field_count"],0)
        self.assertFalse(result["purchased_required_arrow_types_match"])

    def test_2016_readonly_diagnostic_reports_original_sha_tamper(self):
        self.sources[2016].write_bytes(self.sources[2016].read_bytes()+b"tampered")
        result=self.diagnose()
        self.assertEqual(result["failure_stage"],"input_source_sha")
        self.assertEqual(result["failure_code"],"PURCHASED_SOURCE_SHA_INVALID")
        self.assertEqual(result["purchased_rows_checked_before_refusal"],0)
        self.assertFalse(self.private_root.exists())

    def test_2016_readonly_diagnostic_reports_source_geometry_without_values(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        wrong=paid("600001.XSHG","2016-08-17")
        wrong["high"]=1.0
        purchased_schema=pa.schema([
            pa.field("ts",pa.int64()),pa.field("symbol",pa.string()),
            *(pa.field(field,pa.float64()) for field in M.PHYS.F),
        ])
        pq.write_table(pa.Table.from_pylist([
            wrong,paid("000002.XSHE","2016-08-17")
        ],schema=purchased_schema),self.sources[2016])
        self.record[2016]={
            "size":self.sources[2016].stat().st_size,
            "rows":2,"sha":M.ST.sha(self.sources[2016]),
        }
        result=self.diagnose()
        self.assertEqual(result["failure_stage"],"purchased_rows")
        self.assertEqual(result["failure_code"],"SOURCE_PRICE_GEOMETRY_INVALID")
        self.assertFalse(self.private_root.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
