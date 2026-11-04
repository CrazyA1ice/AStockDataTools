"""Only real H5 write probe tests required before local vendor canary."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
T=HERE.parent/"tools"
spec=importlib.util.spec_from_file_location(
    "native_h5_day_mirror_real_write_canary",
    T/"write-private-parquet-day-to-hikyuu-h5-canary.py")
W=importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)


class RealHikyuuH5DayCanaryTests(unittest.TestCase):
    def setUp(self):
        p=HERE.parent/"work"/"_union_scratch"
        p.mkdir(parents=True,exist_ok=True)
        tmp=tempfile.TemporaryDirectory(dir=p,prefix="h5-canary-")
        self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name)
        self.out=self.base/"work"/"h5_mirror"/"canaries"
        self.reports=self.base/"reports"
        self.reports.mkdir()
        self.safe=self.reports/"mirror.json"
        self.sha="a"*64
        dt=datetime.fromisoformat("2026-09-30T00:00:00+08:00")
        self.bar={
            "ts":int(dt.timestamp()*1000),
            "trading_date":"2026-09-30",
            "symbol":"SH600000",
            "source_symbol":"600000.XSHG",
            "value_source":"purchased_parquet",
            "open":10.0,"high":11.0,"low":9.0,"close":10.5,
            "volume":10000.0,"amount":230000.0,
        }

    def fake_reader(self,bar):
        def read(*args,**kwargs):
            return {
                "bars":[dict(bar)],
                "safe_summary":{
                    "local_bars_count":1,
                    "source_all16_private_version_sha256":self.sha,
                    "ready_for_h5_mirror":False,
                    "local_licensed_OHLCVA_values_exported_to_safe":False,
                }
            }
        return SimpleNamespace(read_local_bars=read)

    def run_stage(self,bar):
        with patch.object(W,"MODULE",self.base),\
             patch.object(W,"OUT",self.out),\
             patch.object(W,"REPORTS",self.reports):
            return W.stage(self.fake_reader(bar),"SH600000",
                           self.reports/"synthetic-version.json",self.sha,
                           "2026-09-30","2026-09-30",
                           "123456789abc",self.safe)

    def test_actual_h5_dataset_written_and_compound_roundtrip(self):
        import h5py
        result=self.run_stage(self.bar)
        self.assertEqual(result["written_h5_integer_rows"],1)
        self.assertTrue(result["all_six_fields_exactly_representable_in_h5"])
        self.assertTrue(result["h5py_compound_integer_full_row_readback_verified"])
        self.assertTrue(result["pytables_table_class_marker_and_40byte_layout_verified"])
        self.assertEqual(result["native_hikyuu_amount_value_in_purchased_units_requires_multiplier"],10000)
        self.assertEqual(result["native_hikyuu_volume_value_in_purchased_units_requires_multiplier"],100)
        self.assertFalse(result["hikyuu_cpp_native_reader_verified"])
        self.assertFalse(result["original_hikyuu_h5_rewritten"])
        h5=self.base/result["private_h5_relative_file"]
        with h5py.File(h5,"r") as source:
            ds=source["data"]["SH600000"]
            marker=ds.attrs["CLASS"]
            self.assertEqual(marker.decode("ascii") if isinstance(marker,bytes) else marker,"TABLE")
            self.assertEqual(ds.dtype.itemsize,40)
            self.assertEqual(ds.dtype.names,(
                "closePrice","datetime","highPrice","lowPrice",
                "openPrice","transAmount","transCount"))
            self.assertEqual(tuple(ds.dtype.fields[k][1] for k in ds.dtype.names),
                             (0,4,12,16,20,24,32))
            data=ds[0]
            self.assertEqual(int(data["datetime"]),202609300000)
            self.assertEqual(int(data["openPrice"]),10000)
            self.assertEqual(int(data["transCount"]),100)
            self.assertEqual(int(data["transAmount"]),230)
        contents=self.safe.read_text()
        self.assertNotIn("SH600000",contents)
        self.assertNotIn("230000",contents)

    def test_real_h5_integer_representation_loss_is_explicit_not_silent(self):
        bar=dict(self.bar,amount=230012.25,volume=10025.0)
        result=self.run_stage(bar)
        self.assertFalse(result["all_six_fields_exactly_representable_in_h5"])
        self.assertEqual(result[
            "h5_fixedpoint_source_value_changed_field_counts"],{
                "volume":1,"amount":1
            })
        self.assertFalse(result["ready_for_full_market_mirror"])
        self.assertFalse(result["ready_for_production_query"])

    def test_real_purchased_intraday_timestamp_uses_verified_trading_date(self):
        # Vendor DAY records do not promise midnight timestamps. The
        # original normalizer accepts any Beijing-local time on the day.
        import h5py
        bar=dict(self.bar)
        dt=datetime.fromisoformat("2026-09-30T15:00:00+08:00")
        bar["ts"]=int(dt.timestamp()*1000)
        result=self.run_stage(bar)
        self.assertEqual(result["written_h5_integer_rows"],1)
        with h5py.File(self.base/result["private_h5_relative_file"],"r") as h5:
            self.assertEqual(int(h5["data"]["SH600000"][0]["datetime"]),
                             202609300000)

    def test_purchased_timestamp_and_trading_date_disagreement_is_rejected(self):
        bar=dict(self.bar,trading_date="2026-09-29")
        with self.assertRaisesRegex(ValueError,"differs from trading date"):
            self.run_stage(bar)
        self.assertFalse(self.safe.exists())

    def test_h5_only_candidate_still_requires_midnight_timestamp(self):
        bar=dict(self.bar,value_source="private_h5_mixed_stockday_candidate")
        dt=datetime.fromisoformat("2026-09-30T15:00:00+08:00")
        bar["ts"]=int(dt.timestamp()*1000)
        with self.assertRaisesRegex(ValueError,"must be midnight"):
            self.run_stage(bar)
        self.assertFalse(self.safe.exists())

    def test_bad_run_id_fails_before_h5_write(self):
        with patch.object(W,"MODULE",self.base),\
             patch.object(W,"OUT",self.out),\
             patch.object(W,"REPORTS",self.reports):
            with self.assertRaisesRegex(ValueError,"12-hex"):
                W.stage(self.fake_reader(self.bar),"SH600000",
                        self.reports/"synthetic-version.json",self.sha,
                        "2026-09-30","2026-09-30",
                        "../unsafe",self.safe)
        self.assertFalse(self.out.exists())
        self.assertFalse(self.safe.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
