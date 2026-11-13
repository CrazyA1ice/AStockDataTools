"""Offline CSV encoding, timestamp, tick-vs-QMT independent high tests."""
from datetime import date
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location(
    "qmt_241_l2_csv_crossprobe",HERE/"qmt_241_l2_csv_crossprobe.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
from test_qmt_eltdx_auction_241_probe import sample


CSV_HEAD="万得代码,交易所代码,自然日,时间,成交编号,成交代码,委托代码,BS标志,成交价格,成交数量,叫卖序号,叫买序号\n"


def csv_fixture(include_cancel=True):
    values=[
        "688001.SH,688001,20261016,92500100,1,0,0,B,102000,10000,1,1",
        "688001.SH,688001,20261016,93000150,2,0,0,B,101000,10000,2,2",
        "688001.SH,688001,20261016,93000500,3,0,0,S,101000,5000,3,3",
        "688001.SH,688001,20261016,93100300,4,0,0,B,101000,300,4,4",
    ]
    if include_cancel:
        values.append("688001.SH,688001,20261016,93000700,5,C,0,S,999999,100000,5,5")
    return CSV_HEAD+"\n".join(values)+"\n"


def anchors():
    d,q,t=sample()
    # Date source test is pinned to 2026-10-16, adjust mock day.
    shift=(date(2026,10,16)-d).days*86400000
    for b in (*q,*t):b["ts"]+=shift
    q[0].update(open=10.2,high=10.2,low=10.2,close=10.2,
                volume=100,amount=102000)
    q[1].update(open=10.1,high=10.1,low=10.1,close=10.1,
                volume=150,amount=151500)
    t[0].update(open=10.2,high=10.2,low=10.1,close=10.1,
                volume=25000,amount=253500)
    return q,t


class Tests(unittest.TestCase):
    def test_nine_digit_and_eight_digit_millisecond_clock(self):
        self.assertAlmostEqual(M.timestamp("93000150"),9*3600+30*60+.150)
        self.assertAlmostEqual(M.timestamp("093100300"),9*3600+31*60+.3)
        with self.assertRaises(ValueError):M.timestamp("930606000")
        with self.assertRaises(ValueError):M.timestamp("09:31:00")

    def test_l2_csv_event_code_cancel_excluded_and_prices_not_auto_scaled(self):
        q,t=anchors()
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/"逐笔成交.csv"
            file.write_text(csv_fixture(),encoding="utf-8-sig")
            rows,proof=M.read_tick_csv(file)
            self.assertEqual(proof["event_code_counts"],{"0":4,"C":1})
            self.assertEqual(len(rows),4)
            self.assertEqual(proof["price_divisor_user_selected_not_auto_inferred"],10000)
            result=M.compare(rows,q,t)
            self.assertEqual(result["status"],"OBSERVED_L2_EXTREMA_MATCH_QMT_0931")
            self.assertTrue(all(result["regular_0931_matches"].values()))
            self.assertTrue(result["formal_0925_matches"]["volume_strict"])
            self.assertTrue(result["formal_0925_matches"]["amount_strict"])
            self.assertTrue(result["source_0931_high_differs_from_tdx_merged"])
            self.assertFalse(result["L2_first_minute_complete_certified"])
            self.assertFalse(result["production_merge_authorized"])

    def test_l2_gb18030_csv_and_unknown_event_type_rejected_for_trade_calc(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/"tick.csv"
            content=csv_fixture(False).replace(",2,0,0,B,",",2,T,0,B,")
            file.write_bytes(content.encode("gb18030"))
            rows,meta=M.read_tick_csv(file)
            self.assertEqual(meta["event_code_counts"],{"0":3,"T":1})
            self.assertEqual(len(rows),3)

    def test_if_l2_high_matches_tdx_merged_it_is_not_corroborating_unique_high(self):
        q,t=anchors()
        q[1]["high"]=10.2
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/"trades.csv"
            file.write_text(csv_fixture(),encoding="utf-8")
            rows,_=M.read_tick_csv(file)
            result=M.compare(rows,q,t)
            self.assertFalse(result["source_0931_high_differs_from_tdx_merged"])
            self.assertFalse(result["regular_0931_matches"]["regular_0931_high"])
            self.assertFalse(result["production_merge_authorized"])

    def test_guard_wrong_stock_date_encoding_or_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/"逐笔成交.csv"
            file.write_text(csv_fixture().replace("688001.SH","600000.SH"),
                            encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"Wrong stock or date"):
                M.read_tick_csv(file)
            with self.assertRaisesRegex(ValueError,"Only 688001"):
                M.run(file=file,code="600000.SH")
            file.write_text("bad,header\nx,y\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"Unrecognized L2 schema"):
                M.read_tick_csv(file)

    def test_holdout_empty_0930_no_fake_high(self):
        q,t=anchors()
        records=[(9*3600+25*60,10.2,10000)]
        result=M.compare(records,q,t)
        self.assertEqual(result["status"],"NO_REGULAR_0930_L2_EXECUTIONS")
        self.assertFalse(result["L2_first_minute_complete_certified"])


if __name__=="__main__":unittest.main()
