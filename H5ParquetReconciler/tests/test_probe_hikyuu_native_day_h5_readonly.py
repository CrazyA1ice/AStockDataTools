"""Synthetic Hikyuu H5 daily schema probe; no user market data access."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np

HERE = Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "probe_native_h5_contract_under_test",
    HERE.parent/"tools"/"probe-hikyuu-native-day-h5-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

DTYPE=np.dtype([
    ("datetime","<u8"),("openPrice","<u4"),("highPrice","<u4"),
    ("lowPrice","<u4"),("closePrice","<u4"),
    ("transAmount","<u8"),("transCount","<u8")
])
START="2026-09-30"
END="2026-10-13"


def sample(root, dtype=DTYPE):
    folder=root/"HikyuuData"
    folder.mkdir(parents=True)
    for venue, stock in (("sh","SH600000"),("sz","SZ000001")):
        with h5py.File(folder/(venue+"_day.h5"),"w") as f:
            g=f.create_group("data")
            d=g.create_dataset(stock, data=np.array([
                (202609300000,12000,12100,11900,12050,1500,120),
                (202610080000,12300,12500,12200,12400,1800,150),
                (202610130000,13000,13100,12800,12900,1900,151)
            ],dtype=dtype))
            d.attrs["CLASS"]=b"TABLE"
    return folder


class HikyuuNativeDayH5ProbeTests(unittest.TestCase):
    def test_expected_uint_struct_and_window_counts_without_market_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            folder=sample(root)
            paths=[folder/"sh_day.h5",folder/"sz_day.h5"]
            states=[(p.stat().st_size,p.stat().st_mtime_ns) for p in paths]
            report=M.probe_native_day_h5(
                root,["SH600000","SZ000001"],START,END)
            self.assertTrue(report["requested_source_structure_candidates"])
            self.assertFalse(report["hikyuu_native_driver_load_tested"])
            self.assertFalse(report["ready_for_full_h5_mirror_write"])
            self.assertFalse(report["h5_daily_units_supplier_certified"])
            self.assertFalse(report["mirror_files_created"])
            for symbol in ("SH600000","SZ000001"):
                node=report["per_symbol_native_h5_contract"][symbol]
                self.assertEqual(node["rows_in_dataset"],3)
                self.assertEqual(node["matched_rows_in_window"],3)
                self.assertTrue(node["pytables_table_class_marker_present"])
                self.assertTrue(node["field_order_matches_legacy_h5record"])
                self.assertTrue(node["integer_width_sign_compatible_with_h5record"])
                self.assertFalse(node["full_history_sortedness_verified"])
            self.assertEqual(
                states,[(p.stat().st_size,p.stat().st_mtime_ns) for p in paths])
            rendered=json.dumps(report)
            self.assertNotIn('"open":',rendered)
            self.assertNotIn('"close":',rendered)
            self.assertNotIn("12050",rendered)

    def test_signed_price_fields_are_not_certified_native_unsigned_record(self):
        signed=np.dtype([
            ("datetime","<u8"),("openPrice","<i4"),("highPrice","<i4"),
            ("lowPrice","<i4"),("closePrice","<i4"),
            ("transCount","<u8"),("transAmount","<u8")
        ])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            sample(root,dtype=signed)
            report=M.probe_native_day_h5(root,["SH600000"],START,END)
            node=report["per_symbol_native_h5_contract"]["SH600000"]
            self.assertEqual(node["matched_rows_in_window"],3)
            self.assertTrue(node["expected_field_set"])
            self.assertFalse(node["field_order_matches_legacy_h5record"])
            self.assertFalse(node["integer_width_sign_compatible_with_h5record"])
            self.assertFalse(node["structural_h5record_candidate"])
            self.assertFalse(report["requested_source_structure_candidates"])

    def test_missing_symbol_yields_no_fabricated_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            sample(root)
            report=M.probe_native_day_h5(root,["SH600001"],START,END)
            node=report["per_symbol_native_h5_contract"]["SH600001"]
            self.assertFalse(node["dataset_present"])
            self.assertFalse(node["structural_h5record_candidate"])
            self.assertNotIn("matched_rows_in_window",node)

    def test_invalid_date_and_symbol_input_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            sample(root)
            args=[
                ([],START,END),(["sh600000"],START,END),
                (["SH600000","SH600000"],START,END),
                (["SH600000"],"2026-09-01",END),
                (["SH600000"],"2026-10-13","2026-09-30"),
            ]
            for symbols,first,last in args:
                with self.subTest(symbols=symbols,first=first,last=last):
                    with self.assertRaises(ValueError):
                        M.probe_native_day_h5(root,symbols,first,last)

    def test_reject_missing_native_data_group(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            folder=root/"HikyuuData"
            folder.mkdir()
            with h5py.File(folder/"sh_day.h5","w") as f:
                f.create_group("other")
            with self.assertRaisesRegex(ValueError,"/data group"):
                M.probe_native_day_h5(root,["SH600000"],START,END)

    def test_original_h5_stat_change_during_inspection_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            sample(root)
            actual=M._file_state
            calls=[0]
            def changed(file):
                calls[0]+=1
                result=actual(file)
                if calls[0]==2:
                    result["mtime_ns"]+=1
                return result
            with patch.object(M,"_file_state",side_effect=changed):
                with self.assertRaisesRegex(ValueError,"changed"):
                    M.probe_native_day_h5(root,["SH600000"],START,END)

    def test_cli_writes_only_new_safe_json_inside_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            sample(root)
            target=root/"module"
            reports=target/"reports"
            reports.mkdir(parents=True)
            with patch.object(M,"MODULE",target),patch.object(M,"REPORTS",reports):
                M.main([str(root),"--symbols","SH600000","SZ000001",
                        "--from-date",START,"--to-date",END,
                        "--out","reports/native-h5-canary.json","--read-only"])
                safe=reports/"native-h5-canary.json"
                self.assertTrue(safe.is_file())
                loaded=json.loads(safe.read_text(encoding="utf-8"))
                self.assertTrue(loaded["no_raw_ohlcva_in_safe_summary"])
                self.assertFalse(loaded["mirror_files_created"])
                with self.assertRaises(SystemExit) as ctx:
                    M.main([str(root),"--symbols","SH600000",
                            "--from-date",START,"--to-date",END,
                            "--out","reports/native-h5-canary.json","--read-only"])
                self.assertEqual(ctx.exception.code,2)


if __name__=="__main__":
    unittest.main(verbosity=2)
