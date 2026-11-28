"""Paid 241 1min physical contract: synthetic data only; no real QMT writes."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import local_layout as L
import market_month_storage as S
import market_derived_cycles as D
import qmt_1m_private_month_bridge as B
import update_market as U


DAY = date(2026, 11, 13)
MONTH = "2026-11"


def source_rows(day=DAY, symbol="SH600000", opening_volume=3.):
    dt = datetime(day.year, day.month, day.day, tzinfo=L.UTC8)
    result = []
    for i, (hour, minute) in enumerate(sorted(B.P.GRID)):
        timestamp = dt.replace(hour=hour, minute=minute)
        volume = opening_volume if i == 0 else 2.
        amount = volume * 100
        result.append({
            "ts": int(timestamp.timestamp()*1000),
            "symbol": symbol, "open": 10., "high": 10.2,
            "low": 9.8, "close": 10.,
            "volume": volume, "amount": amount
        })
    return result


def table(rows):
    return pa.Table.from_pylist(rows, schema=S.SCHEMA)


class Paid241NativeContractTests(unittest.TestCase):
    def test_01_preserves_native_0930_volume_and_0931_as_separate_bars(self):
        src = table(source_rows())
        converted, n = S.adapt_native_241_private(src, 0, MONTH)
        self.assertEqual((n, converted.num_rows), (1, 241))
        self.assertEqual(converted["ts"].to_pylist()[:2], src["ts"].to_pylist()[:2])
        self.assertEqual(converted["volume"].to_pylist()[:2], [3., 2.])
        self.assertEqual(converted["amount"].to_pylist()[:2], [300., 200.])

    def test_02_zero_opening_bar_is_not_dropped(self):
        src = table(source_rows(opening_volume=0))
        out, n = S.adapt_native_241_private(src, 0, MONTH)
        self.assertEqual((n, out.num_rows), (1, 241))
        self.assertEqual(out["volume"][0].as_py(), 0.)

    def test_03_unpaired_positive_volume_rejected(self):
        rows = source_rows()
        rows[0]["amount"] = 0.
        with self.assertRaisesRegex(ValueError, "UNPAIRED_VOLUME_AMOUNT"):
            S.adapt_native_241_private(table(rows), 0, MONTH)

    def test_04_nonzero_old_tdx_timestamp_calibration_not_assumed_paid(self):
        with self.assertRaisesRegex(ValueError, "OFFSET_NOT_PROVEN"):
            S.adapt_native_241_private(table(source_rows()), 60000, MONTH)

    def test_05_240_input_never_accepted_as_purchased_241(self):
        with self.assertRaisesRegex(ValueError, "STOCKDAY_ROW_COUNT"):
            S.adapt_native_241_private(table(source_rows()[1:]), 0, MONTH)

    def test_06_bad_native_grid_rejected(self):
        rows = source_rows()
        rows[0]["ts"] -= 60000
        with self.assertRaisesRegex(ValueError, "EXACT_0930_TO_1500"):
            S.adapt_native_241_private(table(rows), 0, MONTH)

    def test_07_native_preserved_241_reproduces_48_higher_bars(self):
        src = source_rows()
        for period, width in D.BARS.items():
            with self.subTest(period=period):
                expected, kind = S._fold_241_day(src, 0, MONTH)
                self.assertEqual(len(expected), 240)
                left = D.aggregate_stock_day(src, period,
                                              one_minute_offset_ms=0)
                right = D.aggregate_stock_day(expected, period,
                                               one_minute_offset_ms=0)
                self.assertEqual(left, right)
                self.assertEqual(len(left), 240//width)
                self.assertAlmostEqual(
                    sum(item["volume"] for item in left),
                    sum(item["volume"] for item in src))
                self.assertAlmostEqual(
                    sum(item["amount"] for item in left),
                    sum(item["amount"] for item in src))


class Paid241PhysicalMonthTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.workspace=self.root/"private"
        self.base=self.root/"AllCycleAStockData"
        for period in L.PERIODS:
            (self.base/period).mkdir(parents=True)

    def _install(self, rows, *, source="T1", day=DAY,
                 contract=S.PAID_241_CONTRACT):
        return S.install_month(self.root, MONTH, iter([table(rows)]),
                               source_id=source, days=[day.isoformat()],
                               workspace=self.workspace,
                               minute_contract=contract,
                               progress=lambda _: None)

    def test_08_first_paid_241_month_commits_with_version_marker(self):
        result = self._install(source_rows())
        self.assertEqual(result["status"], "COMMITTED")
        self.assertEqual(pq.ParquetFile(
            self.base/"1min"/"2026-11.parquet").metadata.num_rows, 241)
        state = S.state_for(self.root, workspace=self.workspace)
        self.assertEqual(
            state["periods"]["1min"][MONTH]["minute_grid_contract"],
            S.PAID_241_CONTRACT)

    def test_09_idempotent_same_sha_same_source(self):
        self._install(source_rows())
        again = self._install(source_rows())
        self.assertEqual(again["status"], "ALREADY_INSTALLED")

    def test_10_explicit_241_append_in_same_version_and_no_duplicate(self):
        self._install(source_rows())
        another = date(2026, 11, 16)
        rows = source_rows(another)
        out = self._install(rows, source="T2", day=another)
        self.assertEqual(out["rows"], 482)
        self.assertEqual(S._verify_paid_241_physical_month(
            self.base/"1min"/"2026-11.parquet",MONTH), 2)

    def test_11_legacy_240_month_cannot_be_extended_by_241(self):
        old = S.install_month(
            self.root, MONTH, iter([table(source_rows()[1:])]),
            source_id="LEGACY_240", days=[DAY.isoformat()],
            workspace=self.workspace, progress=lambda _:None)
        path = self.base/"1min"/"2026-11.parquet"
        before=L.hash_file(path)
        another=date(2026,11,16)
        with self.assertRaisesRegex(ValueError,
                                    "EXISTING_240_MONTH_REQUIRES_EXPLICIT"):
            self._install(source_rows(another),source="NEW_241",day=another)
        self.assertEqual(L.hash_file(path),before)
        self.assertEqual(old["status"],"COMMITTED")

    def test_12_incomplete_new_240_physical_month_refused_without_file(self):
        with self.assertRaisesRegex(ValueError,
                                    "INCOMPLETE_OR_MIXED_STOCK_DAY"):
            self._install(source_rows()[1:])
        self.assertFalse((self.base/"1min"/"2026-11.parquet").exists())

    def test_13_duplicate_0930_key_refused_without_file(self):
        rows=source_rows()
        rows[-1]={**rows[-1], "ts":rows[0]["ts"]}
        with self.assertRaisesRegex(ValueError, "Duplicate normalized|DUPLICATE_STOCK_MINUTE_KEY"):
            self._install(rows)
        self.assertFalse((self.base/"1min"/"2026-11.parquet").exists())

    def test_14_preserve_paid_september_original_during_november_append(self):
        source=self.base/"1min"/"2026-09.parquet"
        pq.write_table(table(source_rows(date(2026,9,30))),source)
        before=L.hash_file(source)
        self._install(source_rows())
        self.assertEqual(L.hash_file(source),before)


class Paid241DailyStageTests(unittest.TestCase):
    def test_15_one_stock_private_day_receipt_exact_241_without_qmt(self):
        raw=source_rows()
        mock_rows=[]
        for row in raw:
            stamp=datetime.fromtimestamp(row["ts"]/1000,L.UTC8)
            mock_rows.append({
                "datetime_cn":stamp.isoformat(),"symbol":"600000.SH",
                **{f:row[f] for f in S.FIELDS}})
        expected={"open":10.,"high":10.2,"low":9.8,"close":10.,
                  "volume":sum(r["volume"] for r in raw),
                  "amount":sum(r["amount"] for r in raw)}
        calibration={"providers":{"SH_OTHER":{
            "category":"SH_OTHER","offset_ms":0,
            "volume":{"factor":1.},"amount":{"factor":1.}}}}
        with TemporaryDirectory() as temp:
            with (patch.object(U,"fetch_one",return_value=mock_rows),
                  patch.object(U.X,"sample_check",
                               return_value={"results":{}})):
                path,doc=U.stage_day(
                    temp,DAY,{"SH600000":expected},calibration,
                    {"sample_stocks":1,
                     "minute_cross_checks":{}},workspace=Path(temp),
                    reader=object(),progress=lambda _:None)
            self.assertEqual(doc["rows"],241)
            self.assertEqual(doc["minute_grid_contract"],S.PAID_241_CONTRACT)
            self.assertEqual(pq.ParquetFile(path).metadata.num_rows,241)
            self.assertEqual(pq.read_table(path,columns=["volume"])["volume"][0].as_py(),3.)
            self.assertFalse(doc["production_merge_authorized"])


    def test_16_zero_0930_price_is_used_for_first_purchased_5m(self):
        # A zero-turnover opening quote is still a distinct purchased K.
        # Historical TDX 240 folds would drop it; our paid 241 path must
        # retain its opening OHLC in the first 5m reconstruction.
        rows=source_rows(opening_volume=0.)
        rows[0].update({"open":9.6,"high":10.4,"low":9.5,"close":9.6})
        first_before=dict(rows[0])
        made=D.aggregate_stock_day(rows,"5min",one_minute_offset_ms=0)
        self.assertEqual(len(made),48)
        self.assertEqual(made[0]["open"],9.6)
        self.assertEqual(made[0]["high"],10.4)
        self.assertEqual(made[0]["low"],9.5)
        self.assertAlmostEqual(made[0]["volume"],10.)
        self.assertAlmostEqual(made[0]["amount"],1000.)
        self.assertEqual(rows[0],first_before)


if __name__ == "__main__":
    unittest.main()
