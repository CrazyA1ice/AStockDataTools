"""Synthetic-only native TDX day -> established private normalized daily adapter."""
import importlib.util
import json
import struct
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    o=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(o)
    return o


A=load("private_native_tdx_day_intake_test",
       HERE.parent/"tools"/"intake-tdx-native-day-to-private-postclose-json.py")


def raw(day,open_cents=1000,hi=1200,lo=900,close=1100,amount=120000.0,volume=1500):
    return struct.pack("<IIIIIfII",day,open_cents,hi,lo,close,
                       float(amount),int(volume),0)


@contextmanager
def fresh(days=(20261012,20261013,20261014)):
    work=HERE.parent/"work"
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work,prefix="tdx-native-day-test-") as temp:
        root=Path(temp)
        source=root/"sh600000.day"
        source.write_bytes(b"".join(raw(day) for day in days))
        module=root/"module"
        module.mkdir()
        reports=module/"reports"
        reports.mkdir()
        private=module/"work"/"tdx_postclose_native_intake"
        folder=private/"intake_012345abcdef"
        safe=reports/"native-adapter-safe.json"
        with patch.object(A,"MODULE",module), \
             patch.object(A,"WORK",private), \
             patch.object(A,"REPORTS",reports):
            yield source,safe,folder


def run(source,safe,folder=None,day="2026-10-14",copy=False,baseline="2026-10-13"):
    return A.intake(source,"SH600000",day,baseline,folder,safe,copy)


class NativeDayToPrivatePostcloseAdapterTests(unittest.TestCase):
    def test_source_has_genuine_new_day_but_default_does_not_store_values(self):
        with fresh() as (src,safe,folder):
            original=src.read_bytes()
            result=run(src,safe)
            self.assertEqual(result["status"],"native_tdx_stockday_available_not_staged")
            self.assertEqual(result["native_candidate_stockday_rows"],1)
            self.assertEqual(result["source_last_date"],"2026-10-14")
            self.assertFalse(result["normalized_private_json_created"])
            self.assertFalse(result["ready_for_automatic_parquet_h5_union"])
            self.assertFalse(result["production_query_route_modified"])
            self.assertEqual(src.read_bytes(),original)
            self.assertFalse(folder.exists())
            self.assertTrue(safe.exists())
            for secret in ("SH600000","sh600000.day","120000.0",
                           "1500.0","1000","/market/"):
                self.assertNotIn(secret,safe.read_text(encoding="utf-8"))

    def test_opt_in_private_normalized_document_uses_existing_adapter_contract(self):
        with fresh() as (src,safe,folder):
            result=run(src,safe,folder,copy=True)
            self.assertEqual(result["status"],"native_tdx_stockday_available_not_staged")
            self.assertTrue(result["normalized_private_json_created"])
            record,digest=A.POSTCLOSE.load_input(folder/"normalized-day.json")
            self.assertEqual(record["format"],A.POSTCLOSE.DOC_FORMAT)
            self.assertEqual(record["symbol"],"SH600000")
            self.assertEqual(record["date"],"2026-10-14")
            self.assertEqual(record["period"],"day")
            self.assertEqual(record["time_label_policy"],"daily_session_date")
            self.assertEqual(record["bars"][0]["time"],"00:00")
            self.assertEqual(record["bars"][0]["open"],10.0)
            self.assertEqual(record["bars"][0]["high"],12.0)
            self.assertEqual(record["bars"][0]["low"],9.0)
            self.assertEqual(record["bars"][0]["close"],11.0)
            self.assertEqual(record["bars"][0]["amount"],120000.0)
            self.assertEqual(record["bars"][0]["volume"],1500.0)
            self.assertEqual(A.POSTCLOSE.validate(record)["matching_bar_count"],1)
            self.assertEqual(result["private_normalized_file_sha256"],digest)
            self.assertFalse(result["private_active_pointers_read_or_modified"])
            self.assertFalse(result["ready_for_automatic_parquet_h5_union"])
            self.assertNotIn("SH600000",safe.read_text(encoding="utf-8"))
            self.assertNotIn("120000",safe.read_text(encoding="utf-8"))

    def test_missing_new_day_reports_true_source_tail_without_empty_private_copy(self):
        with fresh(days=(20261012,20261013)) as (src,safe,folder):
            result=run(src,safe)
            self.assertEqual(result["source_last_date"],"2026-10-13")
            self.assertEqual(result["native_candidate_stockday_rows"],0)
            self.assertEqual(result["status"],"native_tdx_stockday_not_present")
            self.assertFalse(result["normalized_private_json_created"])
            self.assertFalse(folder.exists())
            self.assertTrue(safe.is_file())

    def test_missing_new_day_refuses_opt_in_empty_private_copy(self):
        with fresh(days=(20261012,20261013)) as (src,safe,folder):
            with self.assertRaisesRegex(ValueError,"Cannot privately copy a missing"):
                run(src,safe,folder,copy=True)
            self.assertFalse(folder.exists())
            self.assertFalse(safe.exists())

    def test_exact_parent_end_or_earlier_is_never_accepted(self):
        with fresh() as (src,safe,folder):
            for day in ("2026-10-13","2026-10-12","2026-10-1","BAD"):
                with self.subTest(day=day):
                    with self.assertRaises(ValueError):
                        run(src,safe,day=day)
                    self.assertFalse(safe.exists())

    def test_native_duplicates_and_malformed_source_fail_before_safe(self):
        for days in ((20261013,20261014,20261014),
                     (20261014,20261013)):
            with self.subTest(days=days):
                with fresh(days=days) as (src,safe,folder):
                    with self.assertRaises(ValueError):
                        run(src,safe)
                    self.assertFalse(safe.exists())
                    self.assertFalse(folder.exists())

    def test_wrong_extension_symbol_or_symlink_escape_refused(self):
        with fresh() as (src,safe,folder):
            with self.assertRaises(ValueError):
                A.intake(src,"SZ000001","2026-10-14","2026-10-13",None,safe)
            wrong=src.with_suffix(".lc5")
            wrong.write_bytes(src.read_bytes())
            with self.assertRaises(ValueError):
                run(wrong,safe)
            self.assertFalse(safe.exists())

    def test_no_private_path_without_optin_or_external_paths(self):
        with fresh() as (src,safe,folder):
            with self.assertRaisesRegex(ValueError,"No private directory"):
                run(src,safe,folder)
            with self.assertRaises(ValueError):
                run(src,safe,src.parent/"intake_012345abcdef",copy=True)
            with self.assertRaises(ValueError):
                run(src,src.parent/"unsafe.json")
            self.assertFalse(safe.exists())

    def test_existing_safe_and_private_dir_are_not_overwritten(self):
        with fresh() as (src,safe,folder):
            safe.write_text("protected",encoding="utf-8")
            with self.assertRaises(ValueError):
                run(src,safe)
            self.assertEqual(safe.read_text(),"protected")
            safe.unlink()
            folder.mkdir(parents=True)
            with self.assertRaises(ValueError):
                run(src,safe,folder,copy=True)
            self.assertFalse(safe.exists())

    def test_changed_source_between_probe_and_extract_refused(self):
        with fresh() as (src,safe,folder):
            old=A.NATIVE.inspect
            def changed(*args,**kwargs):
                result=old(*args,**kwargs)
                with src.open("ab") as f:
                    f.write(b"changed")
                return result
            with patch.object(A.NATIVE,"inspect",side_effect=changed):
                with self.assertRaises(ValueError):
                    run(src,safe)
            self.assertFalse(safe.exists())

    def test_native_volume_or_amount_unit_is_not_certified(self):
        with fresh() as (src,safe,folder):
            result=run(src,safe)
            self.assertTrue(result["tdx_volume_amount_physical_units_unverified"])
            self.assertFalse(result["vendor_original_source_authenticity_certified"])
            self.assertFalse(result["market_source_other_periods_crosschecked"])


if __name__=="__main__":
    unittest.main(verbosity=2)
