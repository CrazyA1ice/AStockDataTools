"""Offline QMT extra-data tests; never contact live QMT or Windows scheduler."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

import local_layout as L
import qmt_extra_data as E


class FakeFrame:
    def __init__(self, rows, index=None):
        self.rows = [dict(v) for v in rows]
        self.index = index if index is not None else range(len(rows))

    def to_dict(self, orient=None):
        if orient != "records":
            raise ValueError("Unexpected frame serialization")
        return [dict(row) for row in self.rows]


class FakeXt:
    def __init__(self):
        self.download_calls = []
        self.names = ["沪深A股", "沪深指数", "沪深基金", "ETF", "测试板块"]
        self.sectors = {
            "沪深A股": ["600000.SH"],
            "沪深指数": ["000001.SH"],
            "板块指数": [],
            "沪深基金": ["510050.SH", "160000.SZ"],
            "ETF": ["510050.SH"],
            "ETF基金": [],
            "沪深ETF": [],
            "测试板块": ["600000.SH", "510050.SH"],
        }

    def get_stock_list_in_sector(self, name):
        return self.sectors.get(name, [])

    def get_instrument_type(self, code):
        return {"ETF": code == "510050.SH", "LOF": code == "160000.SZ"}

    def download_sector_data(self):
        self.download_calls.append(("sectors",))

    def get_sector_list(self):
        return self.names

    def download_etf_info(self):
        self.download_calls.append(("etf_info",))

    def get_etf_info(self):
        return {"510050.SH": {"nav": 2.0, "stocks": [{"code": "600000.SH"}]}}

    def get_instrument_detail(self, code):
        return {"instrument": code, "name": "test"}

    def get_index_weight(self, code):
        return {"600000.SH": .31}

    def download_financial_data(self, codes, names):
        self.download_calls.append(("financial", tuple(codes), tuple(names)))

    def get_financial_data(self, codes, names, **kwargs):
        return {codes[0]: {
            "Balance": FakeFrame([{"m_timetag": 20260930, "assets": 12.5}]),
            "Income": FakeFrame([{"m_timetag": 20260930, "income": 5.}]),
        }}

    def get_divid_factors(self, code):
        return FakeFrame([{"interest": .1, "allotNum": 0.}])

    def download_history_data(self, code, period, start_time, end_time):
        self.download_calls.append(("history", code, period, start_time, end_time))

    def get_market_data_ex(self, *, stock_list, period, **kwargs):
        code = stock_list[0]
        d = date(2026, 11, 13)
        if period == "1mon":
            d = date(2026, 10, 30)
        ts = int(datetime(d.year, d.month, d.day, 15, 0,
                          tzinfo=L.UTC8).timestamp() * 1000)
        bar = {"time": ts, "open": 10., "high": 10.1, "low": 9.9,
               "close": 10.01, "volume": 200., "amount": 2000.}
        return {code: FakeFrame([bar])}


def fixture_root(tmp):
    root = Path(tmp) / "stock"
    base = root / "AllCycleAStockData"
    for period in L.PERIODS:
        (base / period).mkdir(parents=True)
    return root


class QmtExtraTests(unittest.TestCase):
    def test_discovery_separates_index_etf_fund_and_stock(self):
        result = E.discover(FakeXt())
        self.assertEqual(result["financial"], ["600000.SH"])
        self.assertEqual(result["adjustments"], ["600000.SH"])
        self.assertEqual(result["index"], ["000001.SH"])
        self.assertEqual(result["etf"], ["510050.SH"])
        self.assertNotIn("160000.SZ", result["etf"])

    def test_reject_malformed_asset_symbols(self):
        for bad in ("SH600000", "../../passwd", "AAA.SZ", "600000.BANK"):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "security code"):
                    E.valid_code(bad)

    def test_snapshot_payload_keeps_source_columns_and_index(self):
        df = FakeFrame([{"cash": 5., "asset": None}], index=["20260930"])
        rows = E.dataframe_records(df)
        self.assertEqual(rows[0]["_index"], "20260930")
        table = E.snapshot_table("2026-11-15", "600000.SH", "Balance", rows)
        self.assertIn('"cash":5.0', table["payload_json"][0].as_py())

    def test_no_unknown_or_noninteger_qmt_quote_timestamp(self):
        stamp = int(datetime(2026, 11, 13, 15, tzinfo=L.UTC8).timestamp()*1000)
        with self.assertRaisesRegex(ValueError, "Fractional"):
            E._normalize_quote("510050.SH",
                               FakeFrame([{"time": stamp + .5}]),
                               until=date(2026, 11, 15))
        with self.assertRaisesRegex(ValueError, "timestamp"):
            E._normalize_quote("510050.SH", FakeFrame([{"time": 123}]),
                               until=date(2026, 11, 15))

    def test_reject_bad_quote_high_low(self):
        stamp = int(datetime(2026, 11, 13, 15, tzinfo=L.UTC8).timestamp()*1000)
        data = {"time": stamp, "open": 10., "high": 9., "low": 9.5,
                "close": 10., "volume": 1., "amount": 1.}
        with self.assertRaisesRegex(ValueError, "OHLCVA invalid"):
            E._normalize_quote("510050.SH", FakeFrame([data]),
                               until=date(2026, 11, 15))

    def test_readonly_preview_makes_no_file_and_no_network_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            xt = FakeXt()
            extra = root / "AllCycleAStockData" / "qmt_extra"
            private = Path(tmp) / "private"
            result = E.run(root, xt=xt, apply=False,
                           today=date(2026, 11, 15),
                           workspace=private, progress=lambda _: None)
            self.assertEqual(result["status"], "READONLY_PREVIEW")
            self.assertEqual(result["counts"]["index"], 1)
            self.assertFalse(extra.exists())
            self.assertFalse(private.exists())
            self.assertEqual(xt.download_calls, [])
            self.assertFalse(result["data_files_modified"])

    def test_real_batch_creates_isolated_parquet_and_repeats_idempotently(self):
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            xt = FakeXt()
            private = Path(tmp) / "private"
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                first = E.run(root, xt=xt, apply=True,
                              today=date(2026, 11, 15),
                              since=date(2026, 1, 1),
                              stock_limit=1, asset_limit=1,
                              workspace=private, progress=lambda _: None)
                second = E.run(root, xt=xt, apply=True,
                               today=date(2026, 11, 15),
                               since=date(2026, 1, 1),
                               stock_limit=1, asset_limit=1,
                               workspace=private, progress=lambda _: None)
            base = root / "AllCycleAStockData"
            extra = base / "qmt_extra"
            self.assertEqual(first["status"], "BATCH_COMMITTED_MORE_BATCHES_MAY_REMAIN")
            self.assertEqual(second["status"], "BATCH_COMMITTED_MORE_BATCHES_MAY_REMAIN")
            self.assertTrue((private / "progress.json").is_file())
            self.assertTrue(list((extra / "financial" / "Balance").rglob("*.parquet")))
            self.assertTrue(list((extra / "adjustments").rglob("*.parquet")))
            self.assertTrue(list((extra / "sectors").rglob("*.parquet")))
            self.assertTrue(list((extra / "index" / "instruments").rglob("*.parquet")))
            self.assertTrue(list((extra / "index" / "weights").rglob("*.parquet")))
            self.assertTrue(list((extra / "etf" / "info").rglob("*.parquet")))
            self.assertFalse(any((base / period).rglob("*.parquet")
                                 for period in L.PERIODS))
            for kind, ticker in (("index", "000001.SH"), ("etf", "510050.SH")):
                for period in L.PERIODS:
                    with self.subTest(kind=kind, period=period):
                        files = list((extra / kind / period / ticker).glob("*.parquet"))
                        self.assertEqual(len(files), 1)
                        table = pq.read_table(files[0])
                        self.assertEqual(table.schema, E.OHLC_SCHEMA)
                        self.assertEqual(table.num_rows, 1)
            # All purchased 8 period directories stay completely empty.
            self.assertEqual(xt.download_calls.count(("sectors",)), 2)

    def test_windows_atomic_replace_closes_all_parquet_readers(self):
        """Both scratch readback and existing snapshot close before rename."""
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "financial.parquet"
            workspace = Path(tmp) / "private"
            first = E.snapshot_table(
                "2026-11-15", "600000.SH", "Balance", [{"value": 1}])
            second = E.snapshot_table(
                "2026-11-15", "600000.SH", "Balance", [{"value": 2}])
            native_reader = pq.ParquetFile
            native_replace = os.replace
            readers = []
            renames = []

            class TrackedReader:
                def __init__(self, filename):
                    self.native = native_reader(filename)
                    self.closed = False
                    readers.append(self)
                def read(self):
                    return self.native.read()
                def close(self):
                    self.native.close()
                    self.closed = True

            def checked_replace(src, dst):
                self.assertTrue(readers)
                self.assertTrue(all(reader.closed for reader in readers),
                                "Windows file replace attempted with open Parquet reader")
                renames.append((str(src), str(dst)))
                return native_replace(src, dst)

            with patch.object(E.pq, "ParquetFile", side_effect=TrackedReader), \
                 patch.object(E.os, "replace", side_effect=checked_replace):
                created = E._atomic_parquet(path, first, workspace=workspace)
                updated = E._atomic_parquet(
                    path, second, workspace=workspace, allow_changed=True)
                unchanged = E._atomic_parquet(
                    path, second, workspace=workspace, allow_changed=True)
            self.assertEqual(created["status"], "CREATED")
            self.assertEqual(updated["status"], "UPDATED")
            self.assertEqual(unchanged["status"], "UNCHANGED")
            self.assertEqual(len(renames), 2)
            self.assertGreaterEqual(len(readers), 4)
            self.assertTrue(all(reader.closed for reader in readers))
            self.assertTrue(list((workspace / "backups").rglob("*.bak")))

    def test_parquet_reader_close_even_if_read_raises(self):
        class BadReader:
            def __init__(self):
                self.closed = False
            def read(self):
                raise ValueError("Synthetic corrupt Parquet")
            def close(self):
                self.closed = True
        bad = BadReader()
        with patch.object(E.pq, "ParquetFile", return_value=bad):
            with self.assertRaisesRegex(ValueError, "Synthetic corrupt"):
                E._read_closed_parquet("not-opened.parquet")
        self.assertTrue(bad.closed)

    def test_prelisting_quote_windows_may_be_missing_but_later_data_valid(self):
        class NewEtfXt(FakeXt):
            def get_market_data_ex(self, *, stock_list, period, **kwargs):
                if kwargs["end_time"][:4] < "2026":
                    return {}
                return super().get_market_data_ex(
                    stock_list=stock_list, period=period, **kwargs)
        with tempfile.TemporaryDirectory() as tmp:
            xt = NewEtfXt()
            extra = Path(tmp) / "market"
            changes = E._fetch_quotes(
                xt, extra, "etf", "510050.SH",
                date(2026, 11, 15), date(2025, 1, 1),
                workspace=Path(tmp) / "private")
            self.assertEqual(set(changes), set(E.API_PERIODS))
            self.assertGreater(changes["day"]["observed"], 0)

    def test_no_price_periods_means_not_a_successful_asset_download(self):
        class EmptyXt(FakeXt):
            def get_market_data_ex(self, *, stock_list, period, **kwargs):
                return {}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "zero index/ETF OHLCVA"):
                E._fetch_quotes(
                    EmptyXt(), Path(tmp) / "market", "etf", "510050.SH",
                    date(2026, 11, 15), date(2026, 1, 1),
                    workspace=Path(tmp) / "private")

    def test_quote_historical_overlap_must_be_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            extra = Path(tmp) / "qmt_extra"
            private = Path(tmp) / "private"
            day = date(2026, 11, 15)
            stamp = int(datetime(2026, 11, 13, 15, tzinfo=L.UTC8).timestamp()*1000)
            row = {"ts": stamp, "symbol": "SH000001", "open": 10.,
                   "high": 10.1, "low": 9.9, "close": 10.,
                   "volume": 100., "amount": 1000.}
            self.assertEqual(E._upsert_quote(
                extra, "index", "1min", "000001.SH", [row],
                today=day, workspace=private), 1)
            self.assertEqual(E._upsert_quote(
                extra, "index", "1min", "000001.SH", [row],
                today=day, workspace=private), 0)
            changed = {**row, "close": 10.05}
            with self.assertRaisesRegex(ValueError, "historical overlap changed"):
                E._upsert_quote(extra, "index", "1min", "000001.SH",
                                [changed], today=day, workspace=private)

    def test_weekend_closed_week_bar_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            extra = Path(tmp) / "extra"
            private = Path(tmp) / "private"
            friday = date(2026, 11, 13)
            ts = int(datetime(2026, 11, 13, 15, tzinfo=L.UTC8).timestamp()*1000)
            bar = {"ts": ts, "symbol": "SH000001", "open": 10.,
                   "high": 10.1, "low": 9.9, "close": 10.,
                   "volume": 100., "amount": 1000.}
            self.assertEqual(E._upsert_quote(
                extra, "index", "week", "000001.SH", [bar],
                today=date(2026,11,15), workspace=private), 1)

    def test_fail_closed_missing_qmt_etf_universe(self):
        xt = FakeXt()
        xt.sectors["ETF"] = []
        xt.sectors["沪深基金"] = []
        with self.assertRaisesRegex(ValueError, "ETF universe"):
            E.discover(xt)

    def test_cursor_batches_deterministic_and_restart_after_complete(self):
        names = ["600003.SH", "600001.SH", "600002.SH"]
        self.assertEqual(E._batch(names, "", 2),
                         ["600001.SH", "600002.SH"])
        self.assertEqual(E._batch(names, "600002.SH", 2),
                         ["600003.SH"])
        self.assertEqual(E._batch(names, "600003.SH", 2),
                         ["600001.SH", "600002.SH"])


if __name__ == "__main__":
    unittest.main()
