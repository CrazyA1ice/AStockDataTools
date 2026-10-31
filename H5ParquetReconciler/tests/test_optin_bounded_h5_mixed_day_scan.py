"""Opt-in bounded H5 stockday scanner: pure synthetic equivalence/safety."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(label,path):
    spec=importlib.util.spec_from_file_location(label,path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


M=load("bounded_h5_scan_under_test",
       HERE.parent/"tools"/"verify-live-mixed-h5-day-keys-readonly.py")
F=load("original_h5_mixed_day_fixtures",
       HERE/"test_verify_live_mixed_h5_day_keys_readonly.py")
PRE=load("bounded_h5_combined_safe_under_test",
         HERE.parent/"tools"/"verify-private-combined-day-22274-readonly.py")
PROOF=load("bounded_h5_full_union_fixture",
           HERE/"test_verify_private_combined_day_22274_readonly.py")


class BoundedH5ScanTests(unittest.TestCase):
    def test_noncontiguous_days_exact_stockday_matches_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"source"
            F.files(root,2026,("2026-04-08","2026-04-09","2026-04-11"))
            dates=[F.day("2026-04-08"),F.day("2026-04-11")]
            original=M.scan_h5_keys(root,2026,dates)
            bounded=M.scan_h5_keys_bounded(root,2026,dates)
            self.assertEqual(bounded,original)
            self.assertEqual(len(bounded),4)
            self.assertFalse(any(k[1]==202604090000 for k in bounded))

    def test_empty_selected_date_identical_to_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"source"
            F.files(root,2026,("2026-04-08","2026-04-09"))
            dates=[F.day("2026-04-10")]
            self.assertEqual(M.scan_h5_keys_bounded(root,2026,dates),
                             M.scan_h5_keys(root,2026,dates))
            self.assertEqual(M.scan_h5_keys_bounded(root,2026,dates),set())

    def test_2016_window_identical_to_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"source"
            F.files(root,2016,("2016-01-05","2016-06-03","2016-11-09"))
            dates=[F.day("2016-01-05"),F.day("2016-11-09")]
            self.assertEqual(M.scan_h5_keys_bounded(root,2016,dates),
                             M.scan_h5_keys(root,2016,dates))

    def test_duplicate_requested_day_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"source"
            F.files(root,2026,("2026-04-08",))
            with self.assertRaisesRegex(ValueError,"Duplicate requested"):
                M.scan_h5_keys_bounded(root,2026,[F.day("2026-04-08")]*2)

    def test_invalid_source_day_year_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"source"
            F.files(root,2026,("2026-04-08",))
            with self.assertRaisesRegex(ValueError,"out-of-year"):
                M.scan_h5_keys_bounded(root,2026,[F.day("2016-04-08")])

    def test_corrupt_duplicate_h5_key_rejected(self):
        import h5py
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"source"
            F.files(root,2026,("2026-04-08","2026-04-09"))
            path=root/"HikyuuData"/"sh_day.h5"
            with h5py.File(path,"r+") as fh:
                grp=fh["data"]
                old=grp["SH600000"][:]
                dup=np.concatenate([old[:1],old[:1],old[1:]])
                del grp["SH600000"]
                grp.create_dataset("SH600000",data=dup)
            with self.assertRaisesRegex(ValueError,"Unsorted/duplicate"):
                M.scan_h5_keys_bounded(root,2026,[F.day("2026-04-08")])

    def test_oversized_bad_h5_window_rejected(self):
        import h5py
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"source"
            F.files(root,2026,("2026-01-01","2026-12-31"))
            path=root/"HikyuuData"/"sh_day.h5"
            with h5py.File(path,"r+") as fh:
                grp=fh["data"]
                old=grp["SH600000"][:]
                bad=np.zeros(1100,dtype=old.dtype)
                # The dataset is malformed: far too many unique intraday
                # stamps within a single daily-key year.
                bad["datetime"]=202601010000+np.arange(1100,dtype=np.int64)
                del grp["SH600000"]
                grp.create_dataset("SH600000",data=bad)
            with self.assertRaisesRegex(ValueError,"Unbounded"):
                M.scan_h5_keys_bounded(root,2026,[
                    F.day("2026-01-01"),F.day("2026-12-31")])

    def test_opt_in_preserves_exact_combined_source_safe_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tester=PROOF.CombinedPrivateUnionTests()
            ref,report_ref=tester.run_fake(Path(tmp)/"reference")
            actual,report_new=tester.run_fake(
                Path(tmp)/"bounded",bounded_h5_scan=True)
            self.assertEqual(ref,actual)
            self.assertEqual(report_ref.read_bytes(),report_new.read_bytes())
            self.assertNotIn("fast_bounded_h5_scan",report_new.read_text())

    def test_scanner_avoids_date_by_date_h5_binary_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"source"
            F.files(root,2026,("2026-04-08","2026-04-09","2026-04-11"))
            dates=[F.day("2026-04-08"),F.day("2026-04-09"),F.day("2026-04-11")]
            original=M.CORE.h5_key_slice
            with patch.object(M.CORE,"h5_key_slice",wraps=original) as bounds:
                actual=M.scan_h5_keys_bounded(root,2026,dates)
                self.assertEqual(len(actual),6)
                self.assertEqual(bounds.call_count,2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
