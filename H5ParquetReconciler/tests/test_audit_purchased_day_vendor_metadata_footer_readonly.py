"""Synthetic-only licensed day Parquet footer/schema metadata qualification tests.

Never inspect actual purchased market records. The only Parquets below contain
fictional placeholder numeric rows. Metadata is not supplier certification.
"""
import importlib.util
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "purchased_footer_only_unit_hints_test",
    HERE.parent/"tools"/"audit-purchased-day-vendor-metadata-footer-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def write_fake(file,with_metadata=False,ts=True):
    root=pa.schema([
        pa.field("ts",pa.int64()) if ts else pa.field("date",pa.int64()),
        pa.field("open",pa.float64(),metadata=({
            b"vendor.price_unit":b"PRIVATE PRICE UNIT VALUE"
        } if with_metadata else None)),
        pa.field("volume",pa.float64(),metadata=({
            b"volume_unit":b"PRIVATE QUANTITY UNIT VALUE"
        } if with_metadata else None)),
        pa.field("amount",pa.float64()),
        pa.field("secret_field",pa.string(),metadata=({
            b"adjustment_basis":b"PRIVATE ADJUSTMENT POLICY"
        } if with_metadata else None)),
    ],metadata=({
        b"amount_unit":b"PRIVATE AMOUNT UNIT VALUE",
        b"custom_nonstandard_tag":b"PRIVATE SECURITY IDENTIFIER"
    } if with_metadata else None))
    data={
        "ts" if ts else "date":[1780000000000],
        "open":[12345.678],
        "volume":[24680.135],
        "amount":[54321.987],
        "secret_field":["PRIVATE COMPANY 000001"],
    }
    pq.write_table(pa.Table.from_pydict(data,schema=root),file)


@contextmanager
def fake_day_files():
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp).resolve()
        folder=root/"AllCycleAStockData"/"day"
        folder.mkdir(parents=True)
        reports=root/"reports"
        reports.mkdir()
        out=reports/"vendor-footer-hints-safe.json"
        first=folder/"one.parquet"
        second=folder/"two.parquet"
        write_fake(first,with_metadata=True)
        write_fake(second,with_metadata=False)
        with patch.object(M,"REPORTS",reports):
            yield root,folder,out,first,second


class PurchasedVendorMetadataFooterTests(unittest.TestCase):
    def test_role_name_canonical_without_leaking_value(self):
        d={b"vendor.price_unit":b"PRIVATE PRIVATE",
           b"volume_unit":b"share",
           b"ARROW:schema":b"opaque-base64",b"unknown-key":b"private"}
        self.assertEqual(M.metadata_roles(d),{"price_unit","volume_unit"})
        self.assertEqual(M.metadata_roles(None),set())

    def test_full_synthetic_two_footers_only_no_data_leak(self):
        with fake_day_files() as (_root,folder,out,first,second):
            previous={p:p.read_bytes() for p in (first,second)}
            data=M.inspect(_root,out)
            self.assertEqual(data["source_files_footer_only_read"],2)
            self.assertEqual(data["row_groups_footer_only_scanned"],2)
            self.assertEqual(data["total_footer_row_counts_not_row_data_read"],2)
            self.assertEqual(data["public_field_roles_present_file_count"]["amount"],2)
            self.assertEqual(data["metadata_candidate_role_field_occurrences"][
                "price_unit"],1)
            self.assertEqual(data["metadata_candidate_role_field_occurrences"][
                "volume_unit"],1)
            self.assertEqual(data["metadata_candidate_role_field_occurrences"][
                "adjustment_basis"],1)
            self.assertEqual(data["metadata_candidate_role_table_occurrences"][
                "amount_unit"],1)
            self.assertTrue(data["parquet_footer_only_no_market_rows_read"])
            self.assertFalse(data["source_vendor_data_dictionary_attached_and_verified"])
            self.assertFalse(data["historical_physical_price_volume_amount_units_certified"])
            self.assertFalse(data["ready_to_normalize_historical_raw_or_write_h5_mirror"])
            report=out.read_text(encoding="utf-8")
            for secret in ("PRIVATE","12345.678","54321.987","one.parquet",
                           "two.parquet","secret_field","000001",
                           "company"):
                self.assertNotIn(secret,report)
            self.assertEqual(previous,{p:p.read_bytes() for p in previous})

    def test_only_metadata_present_does_not_grant_vendor_certificate(self):
        with fake_day_files() as (root,folder,out,first,second):
            second.unlink()
            data=M.inspect(root,out)
            self.assertEqual(data["source_files_footer_only_read"],1)
            self.assertEqual(data["metadata_candidate_role_table_occurrences"][
                "amount_unit"],1)
            self.assertFalse(data["source_vendor_data_dictionary_attached_and_verified"])
            self.assertTrue(data[
                "candidate_metadata_labels_are_not_authenticated_vendor_definitions"])

    def test_no_day_file_refused(self):
        with fake_day_files() as (root,folder,out,first,second):
            first.unlink()
            second.unlink()
            with self.assertRaisesRegex(ValueError,"No original"):
                M.inspect(root,out)
            self.assertFalse(out.exists())

    def test_missing_timestamp_refused_without_safe(self):
        with fake_day_files() as (root,folder,out,first,second):
            first.unlink()
            second.unlink()
            write_fake(first,ts=False)
            with self.assertRaisesRegex(ValueError,"no ts"):
                M.inspect(root,out)
            self.assertFalse(out.exists())

    def test_existing_safe_does_not_get_overwritten(self):
        with fake_day_files() as (root,folder,out,first,second):
            out.write_text("protected",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"brand-new"):
                M.inspect(root,out)
            self.assertEqual(out.read_text(encoding="utf-8"),"protected")

    def test_footer_budget_refused_before_output(self):
        with fake_day_files() as (root,folder,out,first,second):
            with patch.object(M,"MAX_TOTAL_ROW_GROUPS",1):
                with self.assertRaisesRegex(ValueError,"budget"):
                    M.inspect(root,out)
            self.assertFalse(out.exists())

    def test_binary_metadata_and_unknown_keys_never_exported(self):
        roles=M.metadata_roles({b"\xff\xfe\x01":b"SECRET",
                                b"custom-prefix/amount_unit":b"NOT A UNIT CERT",
                                b"sample_type":b"SECRET"})
        self.assertEqual(roles,{"amount_unit"})
        with self.assertRaisesRegex(ValueError,"unbounded"):
            M.metadata_roles({b"key":b"X"*(1048576+1)})

    def test_code_never_decodes_market_rows(self):
        source=(HERE.parent/"tools"/
                "audit-purchased-day-vendor-metadata-footer-readonly.py").read_text(
                    encoding="utf-8")
        self.assertIn("pq.ParquetFile(source,memory_map=False,pre_buffer=False)",source)
        self.assertNotIn(".iter_batches(",source)
        self.assertNotIn("pq.read_table(",source)
        self.assertNotIn(".to_pandas(",source)
        self.assertNotIn("h5py.File(",source)


if __name__=="__main__":
    unittest.main(verbosity=2)
