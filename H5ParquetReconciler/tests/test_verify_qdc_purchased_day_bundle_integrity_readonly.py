"""Synthetic, fake QDC day Parquet files only; no purchased originals read."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "qdc_purchased_original_day_manifest_test",
    HERE.parent/"tools"/"verify-qdc-purchased-day-bundle-integrity-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def file_hash(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def manifest_entry(name,file,rows=2):
    if name.startswith("2026"):
        year,month=2026,int(name[5:7])
    else:
        year,month=int(name[:4]),1
    first=f"{year}-{month:02d}-04"
    last=f"{year}-{month:02d}-27" if year==2026 else f"{year}-12-30"
    return f"日线    {name} {file.stat().st_size} {rows}  {first}  {last} {file_hash(file)}"


@contextmanager
def prepared():
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp).resolve()
        folder=root/"day"
        folder.mkdir()
        reports=root/"reports"
        reports.mkdir()
        readme=root/"【先看我】数据说明.txt"
        readme.write_text("假想虚构数据包:仅合成测试，不是QDC实际资料",encoding="utf-8")
        table=pa.Table.from_pydict({
            "ts":[1770000000000,1770000600000],
            "symbol":["MOCK","MOCK"],
            "open":[1.1,2.2],
            "amount":[10.3,20.4]})
        for name in sorted(M.EXPECTED_NAMES):
            pq.write_table(table,folder/name)
        manifest=root/"文件校验清单.txt"
        lines=["文件夹 文件名 大小(字节) 行数 起始日 结束日 sha256"]
        lines.extend(manifest_entry(name,folder/name)
                     for name in sorted(M.EXPECTED_NAMES))
        manifest.write_text("\n".join(lines)+"\n",encoding="utf-8")
        target=reports/"QDC-SAFE.json"
        # Test fixture total 2 rows per file; real production total remains fixed.
        with patch.object(M,"REPORTS",reports),patch.object(M,"DAY_TOTAL_ROWS",48):
            yield root,readme,manifest,folder,target,reports


def make_intake(reports,doc_sha,documented=None,unauthenticated=True):
    documented=sorted(documented if documented is not None else
                      M.REQUIRED_DOCUMENTED)
    safe={
        "format":M.INTAKE_FORMAT,
        "status":"vendor_statement_locations_recorded_not_authenticated",
        "private_vendor_document_supplied":True,
        "private_vendor_document_sha256":doc_sha,
        "documented_source_section_role_names_only":documented,
        "undocumented_required_role_names":sorted(M.REQUIRED_UNKNOWN),
        "required_semantic_roles_total":13,
        "independent_document_authenticity_checked":False,
        "document_claims_independently_verified":False,
        "purchased_vendor_physical_units_certified":not unauthenticated,
        "historical_normalized_parquet_authorized":False,
        "hikyuu_h5_mirror_authorized":False,
        "original_purchased_parquet_or_h5_accessed":False,
        "production_or_active_pointer_modified":False,
    }
    path=reports/"source-loci.json"
    path.write_text(json.dumps(safe),encoding="utf-8")
    return path


class OriginalQdcBundleIntegritySyntheticTests(unittest.TestCase):
    def test_full_24_file_fictional_bundle_all_counts_and_bytes_match(self):
        with prepared() as (root,readme,manifest,folder,target,reports):
            before={x.name:(x.stat().st_size,x.stat().st_mtime_ns)
                    for x in folder.iterdir()}
            result=M.inspect(root,file_hash(readme),file_hash(manifest),target)
            self.assertEqual(result["purchased_day_file_count_verified"],24)
            self.assertEqual(result["purchased_day_row_count_verified"],48)
            for flag in ("file_sizes_all_match_received_manifest",
                         "parquet_footer_row_counts_all_match_received_manifest",
                         "all_original_day_file_full_sha256_match_received_manifest",
                         "readme_manifest_and_original_files_unchanged"):
                self.assertTrue(result[flag])
            for flag in ("parquet_market_rows_decoded",
                         "source_vendor_publication_independently_authenticated",
                         "amount_precision_or_rounding_rule_certified",
                         "pre2011_h5_physical_units_and_securities_certified",
                         "historical_normalized_parquet_authorized",
                         "hikyuu_h5_mirror_authorized",
                         "production_market_data_write_authorized"):
                self.assertFalse(result[flag])
            self.assertEqual(before,{
                x.name:(x.stat().st_size,x.stat().st_mtime_ns)
                for x in folder.iterdir()})
            safe=target.read_text(encoding="utf-8")
            for secret in ("MOCK","1770000000000","1.1","2.2",
                           "PRIVATE RECEIPT","2011.parquet"):
                self.assertNotIn(secret,safe)

    def test_private_vendor_intake_receipt_can_be_linked_without_certifying(self):
        with prepared() as (root,readme,manifest,folder,target,reports):
            intake=make_intake(reports,file_hash(readme))
            result=M.inspect(root,file_hash(readme),file_hash(manifest),
                             target,intake)
            self.assertTrue(result[
                "vendor_intake_seven_documented_six_unknown_linked"])
            self.assertEqual(result["vendor_intake_safe_sha256"],file_hash(intake))
            self.assertFalse(result["hikyuu_h5_mirror_authorized"])

    def test_forged_intake_vendor_certification_rejected(self):
        with prepared() as (root,readme,manifest,folder,target,reports):
            intake=make_intake(reports,file_hash(readme),unauthenticated=False)
            with self.assertRaisesRegex(ValueError,"fabricated"):
                M.inspect(root,file_hash(readme),file_hash(manifest),
                          target,intake)
            self.assertFalse(target.exists())

    def test_original_file_byte_tamper_refused(self):
        with prepared() as (root,readme,manifest,folder,target,reports):
            original=folder/"2011.parquet"
            replacement=pa.Table.from_pydict({
                "ts":[1770000000000,1770000600000],
                "symbol":["MOCK","MOCK"],
                "open":[9.9,2.2],
                "amount":[10.3,20.4]})
            pq.write_table(replacement,original)
            with self.assertRaisesRegex(ValueError,"size differs|SHA differs"):
                M.inspect(root,file_hash(readme),file_hash(manifest),target)
            self.assertFalse(target.exists())

    def test_missing_original_file_fails_before_hashing(self):
        with prepared() as (root,readme,manifest,folder,target,reports):
            (folder/"2012.parquet").unlink()
            with self.assertRaisesRegex(ValueError,"inventory differs"):
                M.inspect(root,file_hash(readme),file_hash(manifest),target)
            self.assertFalse(target.exists())

    def test_unexpected_extra_parquet_refused(self):
        with prepared() as (root,readme,manifest,folder,target,reports):
            (folder/"2027.parquet").write_bytes(b"EXTRA BAD")
            with self.assertRaisesRegex(ValueError,"inventory differs"):
                M.inspect(root,file_hash(readme),file_hash(manifest),target)
            self.assertFalse(target.exists())

    def test_bad_manifest_digest_is_refused(self):
        with prepared() as (root,readme,manifest,folder,target,reports):
            with self.assertRaisesRegex(ValueError,"manifest SHA mismatch"):
                M.inspect(root,file_hash(readme),"0"*64,target)
            self.assertFalse(target.exists())

    def test_bad_readme_digest_is_refused(self):
        with prepared() as (root,readme,manifest,folder,target,reports):
            with self.assertRaisesRegex(ValueError,"readme SHA mismatch"):
                M.inspect(root,"0"*64,file_hash(manifest),target)
            self.assertFalse(target.exists())

    def test_manifest_duplicate_daily_item_refused_even_if_rehashed(self):
        with prepared() as (root,readme,manifest,folder,target,reports):
            s=manifest.read_text(encoding="utf-8")
            duplicated=manifest_entry("2011.parquet",folder/"2011.parquet")
            manifest.write_text(s+duplicated+"\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"duplicate"):
                M.inspect(root,file_hash(readme),file_hash(manifest),target)
            self.assertFalse(target.exists())

    def test_manifest_row_count_tampering_detected_even_with_new_manifest_sha(self):
        with prepared() as (root,readme,manifest,folder,target,reports):
            s=manifest.read_text(encoding="utf-8")
            line1=manifest_entry("2011.parquet",folder/"2011.parquet",rows=2)
            line2=manifest_entry("2012.parquet",folder/"2012.parquet",rows=2)
            s=s.replace(line1,manifest_entry("2011.parquet",folder/"2011.parquet",rows=3))
            s=s.replace(line2,manifest_entry("2012.parquet",folder/"2012.parquet",rows=1))
            manifest.write_text(s,encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"row count differs"):
                M.inspect(root,file_hash(readme),file_hash(manifest),target)
            self.assertFalse(target.exists())

    def test_manifest_date_range_outside_filename_rejected(self):
        with prepared() as (root,readme,manifest,folder,target,reports):
            s=manifest.read_text(encoding="utf-8")
            s=s.replace("2026-01-04  2026-01-27","2026-01-04  2026-02-27")
            manifest.write_text(s,encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"date range invalid"):
                M.inspect(root,file_hash(readme),file_hash(manifest),target)
            self.assertFalse(target.exists())

    def test_existing_safe_not_overwritten(self):
        with prepared() as (root,readme,manifest,folder,target,reports):
            target.write_text("PROTECTED",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"NEW"):
                M.inspect(root,file_hash(readme),file_hash(manifest),target)
            self.assertEqual(target.read_text(encoding="utf-8"),"PROTECTED")

    def test_market_row_decoder_is_never_invoked(self):
        source=(HERE.parent/"tools"/
                "verify-qdc-purchased-day-bundle-integrity-readonly.py").read_text(
                    encoding="utf-8")
        for forbidden in ("iter_batches(","read_table(","read_row_group(",
                          ".to_pandas(","h5py.File(","sqlite3.connect(",
                          "os.replace("):
            self.assertNotIn(forbidden,source)
        self.assertIn("hashlib.sha256()",source)
        self.assertIn("pf.metadata.num_rows",source)


if __name__=="__main__":
    unittest.main(verbosity=2)
