"""Offline official xtdata local 1m adapter tests without QMT installation."""
from datetime import date,datetime,timedelta
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location(
    "qmt_local_dat_241_native_readonly",HERE/"qmt_local_dat_241_native_readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
from test_qmt_eltdx_auction_241_probe import sample


class FakeField:
    """Minimal xtdata field-by-stock frame, no pandas dependency in CI."""
    def __init__(self,code,stamps,values):
        self.index=[code]
        self.columns=list(stamps)
        self.data=dict(zip(stamps,values))
        self.loc=self
    def __getitem__(self,key):
        return self.data[key[1]]


class FakeStockFrame:
    def __init__(self,bars):
        self.bars=bars
        self.columns=(*M.FIELDS,"time")
    def iterrows(self):
        for index,b in enumerate(self.bars):
            yield index,{**{k:b[k] for k in M.FIELDS},"time":b["ts"]}


def xtdata_fields(bars,code="688001.SH"):
    stamps=[b["ts"] for b in bars]
    return {key:FakeField(code,stamps,
                  [b[key] if key!="time" else b["ts"] for b in bars])
            for key in (*M.FIELDS,"time")}


def make_source(root,code="688001.SH"):
    file=M.path_for(root,code)
    file.parent.mkdir(parents=True,exist_ok=True)
    file.write_bytes(b"original-native-DAT")
    return file


class Tests(unittest.TestCase):
    def test_xtdata_field_dataframe_returns_241_original_native_minutes(self):
        day,q,tdx=sample()
        loaded=xtdata_fields(q)
        rows,mode=M.normalize(loaded,"688001.SH")
        self.assertEqual(mode,"XT_FIELD_BY_STOCK_TIMES")
        self.assertEqual(len(rows),241)
        result=M.inspect_day(rows,day,q)
        self.assertEqual(result["format_class"],"QMT_241_LABELS")
        self.assertTrue(result["has_0930_auction_label"])
        self.assertTrue(result["has_0931_regular_label"])
        self.assertEqual(result["reference_validation"]["strict_field_matches"],
                         {x:241 for x in M.FIELDS})
        self.assertTrue(result["reference_validation"][
            "identical_time_labels_to_private_qmt"])

    def test_stock_frame_adaptor_and_240_is_not_mislabelled_241(self):
        day,q,tdx=sample()
        loaded={"688001.SH":FakeStockFrame(q[1:])}
        rows,shape=M.normalize(loaded,"688001.SH")
        self.assertEqual(shape,"XT_STOCK_FRAME")
        self.assertEqual(len(rows),240)
        audit=M.inspect_day(rows,day,q)
        self.assertEqual(audit["format_class"],"TDX_STYLE_240_LABELS")
        self.assertEqual(audit["reference_validation"]["status"],
                         "NOT_A_SEPARATE_241_BAR_CANDIDATE")

    def test_time_interpretation_is_CST_not_windows_timezone(self):
        self.assertEqual(
            M.parse_timestamp("20261014093000").strftime("%Y-%m-%d %H:%M"),
            "2026-10-14 09:30")
        day,q,_=sample()
        self.assertEqual(M.parse_timestamp(q[0]["ts"]).strftime("%H:%M"),"09:30")
        with self.assertRaisesRegex(ValueError,"Unsupported"):
            M.parse_timestamp("not-an-epoch")

    def test_241_label_coverage_not_derived_from_file_bytes(self):
        day,q,_=sample()
        rows,_=M.normalize(xtdata_fields(q),"688001.SH")
        self.assertEqual(M.inspect_day(rows,date(2026,10,16))["format_class"],
                         "DAY_NOT_IN_LOCAL_DAT")
        rows=rows[:-1]
        incomplete=M.inspect_day(rows,day,q)
        self.assertEqual(incomplete["format_class"],"OTHER_GRID")
        self.assertEqual(incomplete["reference_validation"]["status"],
                         "NOT_A_SEPARATE_241_BAR_CANDIDATE")

    def test_original_QMT_DAT_sha_unchanged_after_read_and_report_is_only_console(self):
        day,q,_=sample()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            local=make_source(root)
            logs=[]
            def fake(**kwargs):
                self.assertEqual(kwargs["period"],"1m")
                self.assertEqual(kwargs["data_dir"],str(root))
                self.assertFalse(kwargs["fill_data"])
                self.assertEqual(kwargs["dividend_type"],"none")
                self.assertEqual(kwargs["stock_list"],["688001.SH"])
                return xtdata_fields(q)
            result=M.run(root=root,codes=("688001.SH",),days=(day,),
                         reader=fake,
                         reference_loader=lambda code:(q,"private-qmt-sha"),
                         logger=logs.append)
            self.assertEqual(result["statuses"],{"LOCAL_READ_COMPLETED":1})
            self.assertFalse(result["market_files_modified"])
            self.assertEqual(len(logs),2)
            self.assertTrue(logs[0].startswith("QMT_NATIVE_1M_STOCK="))
            self.assertEqual(local.read_bytes(),b"original-native-DAT")
            self.assertFalse(list(root.rglob("*.json")))

    def test_source_changes_during_read_are_rejected(self):
        day,q,_=sample()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            p=make_source(root)
            def corrupted(**kw):
                p.write_bytes(b"mutated")
                return xtdata_fields(q)
            with self.assertRaisesRegex(ValueError,"mutated"):
                M.run(root=root,codes=("688001.SH",),days=(day,),
                      reader=corrupted,reference_loader=lambda code:(q,"sealed"),
                      logger=lambda _:None)

    def test_missing_sdk_explicitly_classified_and_not_substituted(self):
        day,q,_=sample()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            make_source(root)
            r=M.run(root=root,codes=("688001.SH",),
                    days=(day,),
                    reader=lambda **kw:{},
                    reference_loader=lambda code:(q, "sealed"),
                    logger=lambda _:None)
            self.assertEqual(r["statuses"],{"EMPTY_OR_UNSUPPORTED_SHAPE":1})
            self.assertFalse(r["production_merge_authorized"])

    def test_nan_duplicate_time_or_bad_ohlc_fails_closed(self):
        day,q,_=sample()
        loaded=xtdata_fields(q)
        loaded["high"].data[q[0]["ts"]]=float("nan")
        with self.assertRaisesRegex(ValueError,"Invalid"):
            M.normalize(loaded,"688001.SH")
        rows,_=M.normalize(xtdata_fields(q),"688001.SH")
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            M.normalize({"688001.SH":FakeStockFrame(q+[q[-1]])},"688001.SH")

if __name__=="__main__":
    unittest.main()
