"""Synthetic bounded native TDX .day update-landing inventory; no real source."""
import importlib.util
import json
import struct
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,file)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


A=load("private_tdx_vipdoc_inventory_test",
       HERE.parent/"tools"/"inventory-tdx-vipdoc-day-update-landing-readonly.py")
S=("SH600000","SZ000001","SH600519")


def native(day):
    return struct.pack("<IIIIIfII",day,1000,1100,900,1050,
                       1025.0,100,0)


def put(root,symbol,days,relative="vipdoc"):
    target=root/relative/symbol[:2].lower()/"lday"
    target.mkdir(parents=True,exist_ok=True)
    file=target/(symbol.lower()+".day")
    file.write_bytes(b"".join(native(day) for day in days))
    return file


@contextmanager
def fresh():
    work=HERE.parent/"work"
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work,prefix="tdx-landing-test-") as t:
        root=Path(t)
        first=root/"known_install"
        second=root/"alternate_install"
        first.mkdir()
        second.mkdir()
        reports=root/"reports"
        reports.mkdir()
        safe=reports/"tdx-landing-safe.json"
        put(first,"SH600000",(20261012,20261013))
        put(first,"SZ000001",(20261012,20261013))
        put(first,"SH600519",(20261012,20261013))
        with patch.object(A,"REPORTS",reports):
            yield root,first,second,safe


def scan(roots,safe,syms=S,baseline="2026-10-13"):
    return A.inventory(list(roots),list(syms),baseline,safe)


class PrivateTDXLandingInventoryTests(unittest.TestCase):
    def test_known_native_tdx_files_found_but_no_new_days(self):
        with fresh() as (base,one,two,safe):
            result=scan([one],safe)
            self.assertEqual(result["vipdoc_candidate_count"],1)
            self.assertEqual(result["existing_selected_native_day_file_count"],3)
            self.assertEqual(result["newer_tail_candidate_count"],0)
            self.assertEqual(result["status"],
                             "no_newer_tdx_tail_observed_in_explicit_roots")
            self.assertEqual(result["candidate_locations"][0][
                "vipdoc_relative_to_root"],"vipdoc")
            self.assertEqual(result["candidate_locations"][0][
                "selected_native_day_file_slots"][0][
                    "source_last_positional_day"],"2026-10-13")
            self.assertFalse(result["original_tdx_h5_purchased_parquet_modified"])
            self.assertFalse(result["production_query_route_modified"])
            self.assertTrue(result["no_market_ohlcva_stock_codes_or_absolute_paths_in_safe"])
            self.assertTrue(safe.exists())
            for secret in ("SH600000","SZ000001","SH600519",
                           "known_install","1000","1025.0"):
                self.assertNotIn(secret,safe.read_text(encoding="utf-8"))

    def test_alternate_explicit_install_can_hold_newer_actual_native_tail(self):
        with fresh() as (base,one,two,safe):
            put(two,"SH600000",(20261013,20261029),relative="program/vipdoc")
            result=scan([one,two],safe)
            self.assertEqual(result["vipdoc_candidate_count"],2)
            self.assertEqual(result["newer_tail_candidate_count"],1)
            matches=result["newer_native_tail_candidates"]
            self.assertEqual(matches[0]["root_slot"],2)
            self.assertEqual(matches[0]["vipdoc_relative_to_root"],
                             "program/vipdoc")
            self.assertEqual(matches[0]["requested_stock_slot"],1)
            self.assertEqual(matches[0]["observed_newer_tail_day"],"2026-10-29")
            self.assertTrue(result["tail_candidate_is_not_verified_latest_data"])

    def test_explicit_vipdoc_directory_works_as_root(self):
        with fresh() as (base,one,two,safe):
            result=scan([one/"vipdoc"],safe)
            self.assertEqual(result["vipdoc_candidate_count"],1)
            self.assertEqual(result["candidate_locations"][0]["vipdoc_relative_to_root"],".")
            self.assertEqual(result["existing_selected_native_day_file_count"],3)

    def test_no_vipdoc_inside_given_roots_reports_scope_not_empty_market(self):
        with fresh() as (base,one,two,safe):
            result=scan([two],safe)
            self.assertEqual(result["vipdoc_candidate_count"],0)
            self.assertEqual(result["existing_selected_native_day_file_count"],0)
            self.assertEqual(result["newer_tail_candidate_count"],0)
            self.assertTrue(result["other_drives_and_unlisted_installations_not_searched"])

    def test_existing_vipdoc_with_missing_some_symbol_files_records_absence(self):
        with fresh() as (base,one,two,safe):
            file=one/"vipdoc"/"sz"/"lday"/"sz000001.day"
            file.unlink()
            result=scan([one],safe)
            self.assertEqual(result["existing_selected_native_day_file_count"],2)
            self.assertIsNone(result["candidate_locations"][0][
                "selected_native_day_file_slots"][1][
                    "source_last_positional_day"])

    def test_native_tail_out_of_order_refused(self):
        with fresh() as (base,one,two,safe):
            put(one,"SH600000",(20261013,20261012))
            with self.assertRaisesRegex(ValueError,"strictly increasing"):
                scan([one],safe)
            self.assertFalse(safe.exists())

    def test_native_tail_duplicate_day_refused(self):
        with fresh() as (base,one,two,safe):
            put(one,"SH600000",(20261013,20261013))
            with self.assertRaisesRegex(ValueError,"strictly increasing"):
                scan([one],safe)
            self.assertFalse(safe.exists())

    def test_bad_32byte_alignment_or_invalid_ohlc_refused(self):
        with fresh() as (base,one,two,safe):
            file=one/"vipdoc"/"sh"/"lday"/"sh600000.day"
            original=file.read_bytes()
            file.write_bytes(original+b"x")
            with self.assertRaisesRegex(ValueError,"32-byte budget"):
                scan([one],safe)
            self.assertFalse(safe.exists())
            file.write_bytes(native(20261013)[:-4]+b"xxxx")
            with self.assertRaises(ValueError):
                scan([one],safe)
            self.assertFalse(safe.exists())

    def test_source_changes_after_tail_decode_are_rejected(self):
        with fresh() as (base,one,two,safe):
            original=A.tail_record
            def after_read(path):
                result=original(path)
                if path.name=="sh600000.day":
                    with path.open("ab") as stream:
                        stream.write(b"modified")
                return result
            with patch.object(A,"tail_record",side_effect=after_read):
                with self.assertRaisesRegex(ValueError,"changed before SAFE"):
                    scan([one],safe)
            self.assertFalse(safe.exists())

    def test_too_many_direct_root_entries_fails_without_recursion(self):
        with fresh() as (base,one,two,safe):
            with patch.object(A,"MAX_CHILD_ENTRIES",0):
                with self.assertRaisesRegex(ValueError,"one-level discovery"):
                    scan([one],safe)
            self.assertFalse(safe.exists())

    def test_invalid_selections_fail_closed(self):
        with fresh() as (base,one,two,safe):
            for roots,syms,day in (
                ([],S,"2026-10-13"),
                ([one],[],"2026-10-13"),
                ([one],["SH600000"]*2,"2026-10-13"),
                ([one],["sh600000"],"2026-10-13"),
                ([one],["BJ899999"],"2026-10-13"),
                ([one],"SH600000","2026-10-13"),
                ([one],[*S],"2026-10-1"),
                ([one],S,"2010-01-01"),
                ([one,one],S,"2026-10-13"),
            ):
                with self.subTest(roots=roots,syms=syms,day=day):
                    with self.assertRaises(ValueError):
                        scan(roots,safe,syms,day)
                    self.assertFalse(safe.exists())

    def test_safe_report_outside_module_or_preexisting_refused(self):
        with fresh() as (base,one,two,safe):
            with self.assertRaises(ValueError):
                scan([one],base/"unsafe.json")
            safe.write_text("protected",encoding="utf-8")
            with self.assertRaises(ValueError):
                scan([one],safe)
            self.assertEqual(safe.read_text(),"protected")

    def test_source_file_symlink_is_rejected_if_platform_supports_it(self):
        with fresh() as (base,one,two,safe):
            file=one/"vipdoc"/"sh"/"lday"/"sh600000.day"
            new=one/"original-day-file.day"
            file.rename(new)
            try:
                file.symlink_to(new)
            except (OSError,NotImplementedError):
                self.skipTest("Creating file symlinks requires local privileges")
            with self.assertRaises(ValueError):
                scan([one],safe)
            self.assertFalse(safe.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
