"""Offline QMT extra-data tests; never contact live QMT or Windows scheduler."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import json
import subprocess
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
        available = {
            "Balance": FakeFrame([{"m_timetag": 20260930, "assets": 12.5}]),
            "Income": FakeFrame([{"m_timetag": 20260930, "income": 5.}]),
        }
        return {codes[0]: {table: available[table] for table in names
                           if table in available}}

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

    def test_real_etf_15min_binary64_roundoff_preserves_source_ohlcva(self):
        # Real Windows QMT 158000.SZ 2026-09-30, row 399: high one ULP
        # lower than close due solely to source float serialization.
        source = {"time": 1790751600000, "open": 1.031,
                  "high": 1.0319999999999998, "low": 1.031,
                  "close": 1.032, "volume": 10667., "amount": 1100778.}
        result = E._normalize_quote(
            "158000.SZ", FakeFrame([source]), period="15min",
            since=date(2026, 9, 30), until=date(2026, 9, 30))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["high"], source["high"])
        self.assertEqual(result[0]["close"], source["close"])
        self.assertEqual(result[0]["volume"], source["volume"])
        self.assertEqual(result[0]["amount"], source["amount"])
        self.assertLess(result[0]["high"], result[0]["close"])

    def test_ohlc_low_boundary_single_ulp_roundoff_is_accepted(self):
        import math
        stamp = int(datetime(2026, 9, 30, 15,
                             tzinfo=L.UTC8).timestamp() * 1000)
        open_price = 1.031
        source = {"time": stamp, "open": open_price, "high": 1.032,
                  "low": math.nextafter(open_price, math.inf),
                  "close": 1.032, "volume": 1., "amount": 1.}
        normalized = E._normalize_quote(
            "158000.SZ", FakeFrame([source]), period="15min",
            since=date(2026, 9, 30), until=date(2026, 9, 30))
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["low"], source["low"])

    def test_ohlc_boundary_five_or_more_ulps_is_still_rejected(self):
        import math
        stamp = int(datetime(2026, 9, 30, 15,
                             tzinfo=L.UTC8).timestamp() * 1000)
        close_price = 1.032
        too_low_high = close_price
        for _ in range(6):
            too_low_high = math.nextafter(too_low_high, -math.inf)
        source = {"time": stamp, "open": 1.031,
                  "high": too_low_high, "low": 1.031,
                  "close": close_price, "volume": 10667.,
                  "amount": 1100778.}
        with self.assertRaisesRegex(ValueError, "OHLCVA invalid") as ctx:
            E._normalize_quote(
                "158000.SZ", FakeFrame([source]), period="15min",
                since=date(2026, 9, 30), until=date(2026, 9, 30))
        self.assertIn('"high_below_open_or_close"', str(ctx.exception))

    def test_etf_invalid_15min_ohlcva_exposes_exact_source_row(self):
        stamp = int(datetime(2026, 11, 16, 10, 15, tzinfo=L.UTC8).timestamp()*1000)
        good = {"time": stamp, "open": 1.1, "high": 1.2, "low": 1.0,
                "close": 1.15, "volume": 12., "amount": 1200.}
        invalid = dict(good, time=stamp+900000, high=1.05)
        with self.assertRaisesRegex(ValueError, "OHLCVA invalid") as ctx:
            E._normalize_quote("158000.SZ", FakeFrame([good, invalid]),
                               until=date(2026, 11, 16), period="15min")
        msg = str(ctx.exception)
        self.assertIn('"period":"15min"', msg)
        self.assertIn('"row_index":1', msg)
        self.assertIn('"timestamp_ms":' + str(stamp+900000), msg)
        self.assertIn('"high_below_open_or_close"', msg)
        self.assertIn('"high":1.05', msg)
        self.assertIn('"local_day":"2026-11-16"', msg)

    def test_nonpositive_or_nonfinite_qmt_bar_diagnostic_is_not_suppressed(self):
        stamp = int(datetime(2026, 11, 16, 10, tzinfo=L.UTC8).timestamp()*1000)
        raw = {"time": stamp, "open": 1.1, "high": 1.2,
               "low": 0., "close": 1.15, "volume": float("nan"), "amount": 1200.}
        with self.assertRaisesRegex(ValueError, "OHLCVA invalid") as ctx:
            E._normalize_quote("158000.SZ", FakeFrame([raw]),
                               until=date(2026, 11, 16), period="15min")
        msg = str(ctx.exception)
        self.assertIn('"nonpositive_low"', msg)
        self.assertIn('"non_finite"', msg)
        self.assertIn('"volume":null', msg)

    def test_non_numeric_qmt_quote_bar_identifies_missing_field(self):
        stamp = int(datetime(2026, 11, 16, 10, tzinfo=L.UTC8).timestamp()*1000)
        row = {"time": stamp, "open": 1.1, "high": 1.2,
               "low": 1., "close": 1.15, "volume": 1.}
        with self.assertRaisesRegex(ValueError, "OHLCVA invalid") as ctx:
            E._normalize_quote("158000.SZ", FakeFrame([row]),
                               until=date(2026, 11, 16), period="15min")
        self.assertIn('"reason":"missing_or_nonnumeric_ohlcva"',
                      str(ctx.exception))
        self.assertIn('"amount":null', str(ctx.exception))

    def test_qmt_300000_etf_redemption_unsupported_does_not_block_core(self):
        """Observed QMT broker error is capability limitation, not corruption."""
        import contextlib
        message = ('当前客户端未支持此功能，请更新客户端或升级投研版 '
                   'func:commonControl, error:{ "error" : { '
                   '"ErrorID" : 300000, "ErrorMsg" : "function not realize" } }')

        class BrokerXt(FakeXt):
            def download_etf_info(self):
                raise RuntimeError(message)
            def download_index_weight(self):
                raise RuntimeError(message)
            def get_index_weight(self, code):
                raise RuntimeError(message)

        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = root / "AllCycleAStockData" / "qmt_extra"
            private = Path(tmp) / "private"
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                result = E.run(
                    root, xt=BrokerXt(), apply=True,
                    today=date(2026,11,15), since=date(2026,1,1),
                    stock_limit=1, asset_limit=1,
                    workspace=private, progress=lambda _: None)
            self.assertEqual(result["sections"]["etf_catalog"]["status"],
                             "UNSUPPORTED_CLIENT_FUNCTION")
            self.assertEqual(result["sections"]["index_weight_cache"]["status"],
                             "UNSUPPORTED_CLIENT_FUNCTION")
            self.assertEqual(result["sections"]["index"]["symbols_processed"], 1)
            self.assertEqual(result["sections"]["etf"]["symbols_processed"], 1)
            self.assertTrue(list((extra / "financial").rglob("*.parquet")))
            self.assertTrue(list((extra / "adjustments").rglob("*.parquet")))
            self.assertTrue(list((extra / "index" / "day").rglob("*.parquet")))
            self.assertTrue(list((extra / "etf" / "day").rglob("*.parquet")))
            self.assertFalse((extra / "etf" / "info").exists())
            self.assertFalse((extra / "index" / "weights").exists())
            self.assertFalse(any(list((root / "AllCycleAStockData" / p).rglob("*.parquet"))
                                 for p in L.PERIODS))

    def test_unknown_qmt_runtime_errors_still_fail_closed(self):
        class BrokenXt(FakeXt):
            def download_etf_info(self):
                raise RuntimeError("QMT network broke unexpectedly")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "network broke"):
                E._fetch_etf_catalog(
                    BrokenXt(), Path(tmp) / "extras",
                    date(2026,11,15), Path(tmp) / "private")
        self.assertFalse(E._qmt_client_unsupported(
            RuntimeError("ErrorID 300000, authentication timed out")))
        self.assertFalse(E._qmt_client_unsupported(
            RuntimeError("function not realize, ErrorID 200000")))

    def test_if_etf_catalog_api_absent_financial_still_processes(self):
        class MissingEtfAPI:
            pass
        with tempfile.TemporaryDirectory() as tmp:
            reply = E._fetch_etf_catalog(MissingEtfAPI(), Path(tmp) / "extras",
                                         date(2026,11,15), Path(tmp) / "private")
            self.assertEqual(reply["status"], "API_NOT_EXPOSED")

    def test_single_financial_table_calls_have_progress_and_nine_reports(self):
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            xt = FakeXt()
            progress = []
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                result = E.run(root, xt=xt, apply=True, section="financial",
                               today=date(2026, 11, 15), since=date(2026,1,1),
                               stock_limit=1, asset_limit=1,
                               workspace=Path(tmp) / "private",
                               progress=progress.append)
            self.assertEqual(result["sections"]["financial"]["symbols_processed"], 1)
            self.assertNotIn("index", result["sections"])
            self.assertNotIn("etf_catalog", result["sections"])
            self.assertNotIn(("sectors",), xt.download_calls)
            requested = [call[2] for call in xt.download_calls
                         if call[0] == "financial"]
            self.assertEqual(requested, [(name,) for name in E.FIN_TABLES])
            self.assertTrue(all(len(names) == 1 for names in requested))
            self.assertEqual(len([line for line in progress
                if line.startswith("MARKET_QMT_EXTRA_FINANCIAL_TABLE_START=")]),
                len(E.FIN_TABLES))
            self.assertEqual(len([line for line in progress
                if line.startswith("MARKET_QMT_EXTRA_FINANCIAL_TABLE_FETCHED=")]),
                len(E.FIN_TABLES))
            self.assertEqual(len([line for line in progress
                if line.startswith("MARKET_QMT_EXTRA_FINANCIAL_TABLE_COMPLETE=")]),
                len(E.FIN_TABLES))
            self.assertEqual(len([line for line in progress
                if line.startswith("MARKET_QMT_EXTRA_FINANCIAL_TABLE_READ_START=")]),
                len(E.FIN_TABLES))
            self.assertEqual(len([line for line in progress
                if line.startswith("MARKET_QMT_EXTRA_FINANCIAL_TABLE_READ_DONE=")]),
                len(E.FIN_TABLES))
            self.assertEqual(len([line for line in progress
                if line.startswith("MARKET_QMT_EXTRA_FINANCIAL_TABLE_DECODE_DONE=")]),
                len(E.FIN_TABLES))
            decoded = [json.loads(line.split("=", 1)[1])
                       for line in progress if line.startswith(
                           "MARKET_QMT_EXTRA_FINANCIAL_TABLE_DECODE_DONE=")]
            expected_saved = {row["table"] for row in decoded
                              if row["rows"] > 0}
            # FakeXt only provides Balance and Income; absent tables should
            # be read and completed, but must not create empty Parquet files.
            self.assertEqual(expected_saved, {"Balance", "Income"})
            for phase in ("SAVE_START", "SAVE_DONE"):
                emitted = [json.loads(line.split("=", 1)[1])["table"]
                           for line in progress if line.startswith(
                               "MARKET_QMT_EXTRA_FINANCIAL_TABLE_" + phase + "=")]
                self.assertEqual(set(emitted), expected_saved)
                self.assertEqual(len(emitted), len(expected_saved))


    def test_failing_second_financial_table_does_not_advance_cursor(self):
        import contextlib
        class HangTableXt(FakeXt):
            def download_financial_data(self, codes, names):
                if names == ["Income"]:
                    raise RuntimeError("simulated QMT financial table timeout")
                return super().download_financial_data(codes, names)
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            progress = []
            private = Path(tmp) / "private"
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                with self.assertRaisesRegex(RuntimeError, "table timeout"):
                    E.run(root, xt=HangTableXt(), apply=True,
                          section="financial", today=date(2026,11,15),
                          since=date(2026,1,1), stock_limit=1,
                          asset_limit=1, workspace=private,
                          progress=progress.append)
            self.assertTrue(list((root / "AllCycleAStockData" /
                                  "qmt_extra" / "financial" /
                                  "Balance").rglob("*.parquet")))
            self.assertFalse((private / "progress.json").exists())
            self.assertTrue(any("Income" in line for line in progress
                                if "FINANCIAL_TABLE_START" in line))

    def test_financial_recovery_reuses_verified_tables_without_recontacting_qmt(self):
        import contextlib
        class FullFinancialXt(FakeXt):
            def get_financial_data(self, codes, names, **kwargs):
                return {codes[0]: {names[0]: FakeFrame(
                    [{"m_timetag": 20260930, "source": names[0]}])}}
        class InterruptedXt(FullFinancialXt):
            def download_financial_data(self, codes, names):
                if names == ["CashFlow"]:
                    raise RuntimeError("synthetic API blocks at CashFlow")
                return super().download_financial_data(codes, names)
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            work = Path(tmp) / "private"
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                with self.assertRaisesRegex(RuntimeError, "CashFlow"):
                    E.run(root, xt=InterruptedXt(), apply=True,
                          section="financial", today=date(2026, 11, 15),
                          stock_limit=1, workspace=work,
                          progress=lambda _: None)
            self.assertFalse((work / "progress.json").exists())
            extra = root / "AllCycleAStockData" / "qmt_extra"
            for name in ("Balance", "Income"):
                self.assertEqual(E._verified_financial_snapshot(
                    extra, "600000.SH", name, "2026-11-15"), 1)
            class RecoveryXt(FullFinancialXt):
                def download_financial_data(self, codes, names):
                    if names in (["Balance"], ["Income"]):
                        raise AssertionError("Already saved table re-downloaded")
                    return super().download_financial_data(codes, names)
            xt = RecoveryXt()
            events = []
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                result = E.run(root, xt=xt, apply=True,
                               section="financial", today=date(2026, 11, 15),
                               stock_limit=1, workspace=work,
                               progress=events.append)
            self.assertEqual(result["sections"]["financial"]["cursor"],
                             "600000.SH")
            self.assertEqual([call[2] for call in xt.download_calls
                              if call[0] == "financial"],
                             [(name,) for name in E.FIN_TABLES[2:]])
            reused = [json.loads(line.split("=", 1)[1])
                      for line in events if line.startswith(
                          "MARKET_QMT_EXTRA_FINANCIAL_TABLE_REUSED=")]
            self.assertEqual({row["table"] for row in reused},
                             {"Balance", "Income"})
            self.assertTrue(all(row["status"] == "REUSED_VERIFIED"
                                for row in reused))
            self.assertIsNone(E._verified_financial_snapshot(
                extra, "600000.SH", "Balance", "2026-11-16"),
                "A prior-day snapshot must never suppress a new day's refresh")

    def test_financial_recovery_rejects_corrupted_or_mismatched_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            extra = Path(tmp) / "qmt_extra"
            for name in ("Balance", "Income"):
                tab = E.snapshot_table("2026-11-15", "600000.SH", name,
                                       [{"m_timetag": 20260930, "v": 2.0}])
                E._snapshot_write(extra,
                    "financial/" + name + "/600000.SH",
                    "2026-11-15", tab, Path(tmp) / "private")
            self.assertEqual(E._verified_financial_snapshot(
                extra, "600000.SH", "Balance", "2026-11-15"), 1)
            folder = extra / "financial" / "Balance" / "600000.SH" / "snapshots"
            original = next(folder.glob("*.parquet"))
            altered = original.with_name("2026-11-15-0000000000000000.parquet")
            original.rename(altered)
            with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
                E._verified_financial_snapshot(
                    extra, "600000.SH", "Balance", "2026-11-15")
            self.assertEqual(E._verified_financial_snapshot(
                extra, "600000.SH", "Income", "2026-11-15"), 1)

    def test_isolated_financial_worker_exports_original_fake_xt_records(self):
        import qmt_extra_financial_worker as W
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "records.json"
            trace = []
            W.collect(FakeXt(), "600000.SH", "Balance", output,
                      progress=trace.append)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["format"], "qmt_financial_worker_v1")
            self.assertEqual(payload["symbol"], "600000.SH")
            self.assertEqual(payload["table"], "Balance")
            self.assertEqual(payload["records"][0]["assets"], 12.5)
            self.assertTrue(any("WORKER_EXPORT_DONE" in t for t in trace))
            self.assertFalse(output.with_suffix(".part").exists())

    def test_isolated_financial_parent_validates_worker_payload(self):
        def fake_run(command, *, timeout, check):
            self.assertEqual(timeout, 35)
            self.assertFalse(check)
            self.assertEqual(command[0], E.sys.executable)
            out = Path(command[command.index("--output") + 1])
            result = {"format": "qmt_financial_worker_v1",
                      "symbol": "600000.SH", "table": "Balance",
                      "records": [{"_index": "20260930", "m_timetag": 20260930,
                                   "assets": 12.5}]}
            out.write_text(E.canonical_json(result), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "private"
            with patch.object(E.subprocess, "run", side_effect=fake_run):
                rows = E._read_financial_isolated(
                    "600000.SH", "Balance", workspace, timeout_seconds=35,
                    asof="2026-11-16", progress=lambda _: None)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["_index"], "20260930")
            self.assertFalse((workspace / "financial-failures.jsonl").exists())
            self.assertFalse(list(workspace.glob("financial-worker-*")))

    def test_isolated_financial_timeout_records_pending_without_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "private"
            with patch.object(E.subprocess, "run", side_effect=
                              subprocess.TimeoutExpired(cmd="worker", timeout=30)):
                with self.assertRaisesRegex(TimeoutError, "timeout"):
                    E._read_financial_isolated(
                        "600000.SH", "CashFlow", workspace,
                        timeout_seconds=30, asof="2026-11-16",
                        progress=lambda _: None)
            queue = [json.loads(line) for line in (
                workspace / "financial-failures.jsonl").read_text(
                    encoding="utf-8").splitlines()]
            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0]["symbol"], "600000.SH")
            self.assertEqual(queue[0]["table"], "CashFlow")
            self.assertEqual(queue[0]["reason"], "TIMEOUT")
            self.assertEqual(queue[0]["status"], "PENDING_RETRY")
            self.assertFalse((workspace / "progress.json").exists())
            self.assertFalse(list(workspace.glob("financial-worker-*")))

    def test_isolated_financial_recovery_only_invokes_remaining_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = root / "AllCycleAStockData" / "qmt_extra"
            private = Path(tmp) / "private"
            for name in E.FIN_TABLES[:7]:
                tab = E.snapshot_table("2026-11-16", "600000.SH", name,
                                       [{"m_timetag": 20260930, "value": 2.}])
                E._snapshot_write(extra, "financial/" + name + "/600000.SH",
                                  "2026-11-16", tab, private)
            calls = []
            def fake_run(command, *, timeout, check):
                table = command[command.index("--table") + 1]
                calls.append(table)
                self.assertIn(table, E.FIN_TABLES[7:])
                out = Path(command[command.index("--output") + 1])
                records = ([{"_index": "20260930", "m_timetag": 20260930,
                             "value": 3.}] if table == "PershareIndex" else [])
                payload = {"format": "qmt_financial_worker_v1",
                           "symbol": "600000.SH", "table": table,
                           "records": records}
                out.write_text(E.canonical_json(payload), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)
            logs = []
            with patch.object(E.subprocess, "run", side_effect=fake_run):
                result = E._fetch_financial(
                    FakeXt(), extra, "600000.SH", date(2026, 11, 16),
                    private, progress=logs.append,
                    financial_timeout_seconds=30)
            self.assertEqual(calls, ["PershareIndex", "PerShare"])
            self.assertEqual(result["Balance"]["status"], "REUSED_VERIFIED")
            self.assertEqual(result["CashFlow"]["status"], "REUSED_VERIFIED")
            self.assertEqual(result["PershareIndex"]["status"], "CREATED")
            self.assertEqual(result["PerShare"]["status"], "NO_SOURCE_RECORDS")
            self.assertEqual(sum("FINANCIAL_TABLE_REUSED=" in x for x in logs), 7)
            self.assertEqual(E._verified_financial_snapshot(
                extra, "600000.SH", "PershareIndex", "2026-11-16"), 1)

    def test_tolerant_financial_queue_highwater_and_explicit_retries(self):
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            private = Path(tmp) / "private"
            xt = FakeXt()
            xt.sectors["沪深A股"] = ["600000.SH", "600001.SH"]
            calls = []
            fail_once = {"pending": True}
            def simulate_worker(code, name, workspace, **kwargs):
                calls.append((code, name))
                if code == "600000.SH" and name == "CashFlow" and fail_once["pending"]:
                    raise TimeoutError("synthetic QMT timeout")
                return [{"_index": "20260930", "m_timetag": 20260930, "v": 1.}]
            log = []
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()), \
                 patch.object(E, "_read_financial_isolated",
                              side_effect=simulate_worker):
                first = E.run(
                    root, xt=xt, apply=True, section="financial",
                    today=date(2026, 11, 16), stock_limit=2,
                    workspace=private, financial_timeout_seconds=30,
                    financial_continue_on_error=True, progress=log.append)
                state = E._state(E._storage(root), private)
                self.assertEqual(state["cursor"]["financial"], "600001.SH")
                self.assertEqual(sorted(state["financial_pending"]),
                                 ["600000.SH"])
                self.assertEqual(state["financial_pending"]["600000.SH"]["table"],
                                 "CashFlow")
                self.assertEqual(state["financial_pending"]["600000.SH"]["attempts"], 1)
                self.assertEqual(first["status"],
                                 "BATCH_HAS_PENDING_FINANCIAL_RETRIES")
                self.assertEqual(first["sections"]["financial"]["symbols_processed"], 1)
                self.assertEqual(first["sections"]["financial"]["symbols_deferred"], 1)
                self.assertTrue(first["sections"]["financial"]["scan_exhausted"])
                self.assertTrue(any("FINANCIAL_DEFERRED=" in text for text in log))
                preview = E.run(
                    root, xt=xt, apply=False, section="financial",
                    today=date(2026, 11, 16), stock_limit=2,
                    workspace=private, financial_continue_on_error=True,
                    progress=lambda _: None)
                self.assertEqual(preview["next"]["financial"], [],
                                 "Tolerant high-water scan cannot silently wrap")
                self.assertEqual(preview["financial_pending_count"], 1)
                self.assertEqual(E.run(
                    root, xt=xt, apply=False, section="financial",
                    today=date(2026, 11, 16), stock_limit=2,
                    workspace=private, financial_continue_on_error=True,
                    financial_retry_pending=True, progress=lambda _: None
                    )["next"]["financial"], ["600000.SH"])
                fail_once["pending"] = False
                calls.clear()
                second = E.run(
                    root, xt=xt, apply=True, section="financial",
                    today=date(2026, 11, 16), stock_limit=2,
                    workspace=private, financial_timeout_seconds=30,
                    financial_continue_on_error=True,
                    financial_retry_pending=True, progress=lambda _: None)
                self.assertEqual(sorted(calls),
                                 sorted(("600000.SH", name)
                                        for name in E.FIN_TABLES[2:]))
                self.assertEqual(second["sections"]["financial"]["cursor"],
                                 "600001.SH",
                                 "Retry completion must not rewind scan cursor")
                self.assertEqual(second["sections"]["financial"]["pending_retry_count"],
                                 0)
                self.assertEqual(second["sections"]["financial"]["symbols_processed"],
                                 1)
                self.assertEqual(E._state(E._storage(root), private)
                                 ["financial_pending"], {})
            receipts = [json.loads(row) for row in
                        (private / "financial-coverage.jsonl").read_text(
                            encoding="utf-8").splitlines()]
            self.assertEqual([item["symbol"] for item in receipts],
                             ["600001.SH", "600000.SH"])
            self.assertTrue(all(item["coverage_status"] ==
                                "UNVERIFIED_HISTORICAL_COMPLETENESS"
                                for item in receipts))

    def test_tolerant_queue_is_not_implicit_and_does_not_hide_corruption(self):
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            private = Path(tmp) / "private"
            xt = FakeXt()
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()), \
                 patch.object(E, "_read_financial_isolated",
                              side_effect=TimeoutError("source stalled")):
                with self.assertRaises(E.FinancialDeferredError):
                    E.run(root, xt=xt, apply=True, section="financial",
                          today=date(2026, 11, 16), stock_limit=1,
                          workspace=private, financial_timeout_seconds=30)
            self.assertFalse((private / "progress.json").exists(),
                             "Default failure must never advance the cursor")
            with self.assertRaisesRegex(ValueError, "require --section financial"):
                E.run(root, xt=xt, apply=False, section="all",
                      financial_continue_on_error=True)
            with self.assertRaisesRegex(ValueError, "requires explicit"):
                E.run(root, xt=xt, apply=False, section="financial",
                      financial_retry_pending=True)
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()), \
                 patch.object(E, "_verified_financial_snapshot",
                              side_effect=ValueError("corrupted parquet")):
                with self.assertRaisesRegex(ValueError, "corrupted parquet"):
                    E.run(root, xt=xt, apply=True, section="financial",
                          today=date(2026, 11, 16), stock_limit=1,
                          workspace=private, financial_timeout_seconds=30,
                          financial_continue_on_error=True)
            self.assertFalse((private / "progress.json").exists(),
                             "Local corrupt data may not be queued as a broker failure")

    def test_financial_coverage_receipt_flags_sparse_and_empty_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "private"
            summary = {name: {"rows": 50, "status": "CREATED"}
                       for name in E.FIN_TABLES}
            summary["Income"] = {"rows": 12, "status": "CREATED"}
            summary["Top10FlowHolder"] = {
                "rows": 0, "status": "NO_SOURCE_RECORDS"}
            E._financial_coverage_receipt(
                work, "000008.SZ", "2026-11-16", summary)
            receipt = json.loads((work / "financial-coverage.jsonl")
                                 .read_text(encoding="utf-8").strip())
            self.assertEqual(receipt["low_record_tables"], ["Income"])
            self.assertEqual(receipt["empty_source_tables"], ["Top10FlowHolder"])
            self.assertEqual(receipt["coverage_status"],
                             "UNVERIFIED_HISTORICAL_COMPLETENESS")
            self.assertEqual(receipt["tables"]["Income"]["rows"], 12)

    def test_offline_financial_snapshot_audit_inspects_raw_markers_readonly(self):
        import qmt_extra_financial_audit as AUDIT
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            tab = E.snapshot_table(
                "2026-11-16", "000008.SZ", "Income", [
                    {"m_timetag": 20231231, "v": 1.},
                    {"m_timetag": 20240930, "v": 2.}])
            E._snapshot_write(
                extra, "financial/Income/000008.SZ",
                "2026-11-16", tab, private)
            file = next((extra / "financial" / "Income" / "000008.SZ" /
                         "snapshots").glob("*.parquet"))
            fingerprint = L.hash_file(file)
            result = AUDIT.audit(
                root, "000008.SZ", "2026-11-16", workspace=private)
            self.assertEqual(result["status"],
                             "READONLY_FINANCIAL_COVERAGE_UNVERIFIED")
            self.assertEqual(result["snapshot_tables"], 1)
            self.assertEqual(result["tables"]["Income"]["rows"], 2)
            self.assertEqual(result["tables"]["Income"]["status"],
                             "SPARSE_RECORDS_NEED_REVIEW")
            self.assertEqual(result["tables"]["Income"]["raw_m_timetag_min"],
                             "20231231")
            self.assertEqual(result["tables"]["Income"]["raw_m_timetag_max"],
                             "20240930")
            self.assertEqual(result["tables"]["Top10FlowHolder"]["status"],
                             "NO_SNAPSHOT")
            self.assertFalse(result["source_report_dates_validated"])
            self.assertFalse(result["progress_modified"])
            self.assertEqual(fingerprint, L.hash_file(file))
            self.assertFalse((private / "progress.json").exists())
            self.assertEqual(AUDIT.audit(
                root, "000008.SZ", "2026-11-17", workspace=private)
                ["snapshot_tables"], 0)

    def test_financial_cached_repair_preview_and_version_commit_keep_old(self):
        import contextlib
        import qmt_extra_financial_reconcile as R
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            asof = datetime.now(L.UTC8).date().isoformat()
            state = E._state(extra, private)
            state["cursor"]["financial"] = "000009.SZ"
            E._save_state(state, private)
            progress_before = L.hash_file(private / "progress.json")
            old = [
                {"_index": "0", "m_timetag": 19921231, "v": 1.},
                {"_index": "1", "m_timetag": 19931231, "v": 2.}]
            first = E.snapshot_table(asof, "000008.SZ", "Income", old)
            E._snapshot_write(extra, "financial/Income/000008.SZ", asof,
                              first, private)
            prior = E._financial_snapshot_file(extra, "000008.SZ",
                                               "Income", asof)
            prior_hash = L.hash_file(prior)
            fresh = {
                "Income": [*old, {"_index": "2", "m_timetag": 19941231,
                                  "v": 3.}],
                "Top10FlowHolder": [
                    {"_index": "0", "holder": "A"},
                    {"_index": "1", "holder": "B"}]}
            calls = []
            def fake_cached(code, name, workspace, **kwargs):
                self.assertEqual(code, "000008.SZ")
                self.assertTrue(kwargs["cached_only"])
                self.assertFalse(kwargs["record_failure"])
                calls.append(name)
                return fresh[name]
            def run_once(apply):
                return R.reconcile(
                    root, asof=asof, baseline_asof=asof,
                    apply=apply, timeout_seconds=30, workspace=private,
                    progress=lambda _: None,
                    expected_minimums={"Income": 3, "Top10FlowHolder": 2})
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()), \
                 patch.object(E, "_read_financial_isolated",
                              side_effect=fake_cached):
                preview = run_once(False)
                self.assertEqual(preview["tables"]["Income"]
                                 ["extra_exact_records"], 1)
                self.assertEqual(preview["tables"]["Top10FlowHolder"]
                                 ["extra_exact_records"], 2)
                self.assertEqual(E._verified_financial_snapshot(
                    extra, "000008.SZ", "Income", asof), 2)
                self.assertFalse(E._financial_active_path(
                    extra, "000008.SZ", "Income", asof).exists())
                result = run_once(True)
                self.assertEqual(result["status"],
                                 "QMT_FINANCIAL_REPAIR_VERSIONED_COMMITTED")
                self.assertEqual(E._verified_financial_snapshot(
                    extra, "000008.SZ", "Income", asof), 3)
                self.assertEqual(E._verified_financial_snapshot(
                    extra, "000008.SZ", "Top10FlowHolder", asof), 2)
                self.assertEqual(L.hash_file(prior), prior_hash)
                self.assertEqual(len(list(prior.parent.glob(
                    asof + "-*.parquet"))), 2)
                self.assertTrue(E._financial_active_path(
                    extra, "000008.SZ", "Income", asof).exists())
                run_once(True)
                self.assertEqual(len(list(prior.parent.glob(
                    asof + "-*.parquet"))), 2)
            self.assertEqual(calls, ["Income", "Top10FlowHolder"] * 3)
            self.assertEqual(progress_before, L.hash_file(
                private / "progress.json"))
            self.assertTrue((private / "financial-repair.jsonl").exists())

    def test_financial_repair_rejects_changed_old_rows_before_any_write(self):
        import contextlib
        import qmt_extra_financial_reconcile as R
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            asof = datetime.now(L.UTC8).date().isoformat()
            state = E._state(extra, private)
            state["cursor"]["financial"] = "000009.SZ"
            E._save_state(state, private)
            tab = E.snapshot_table(asof, "000008.SZ", "Income",
                                   [{"_index": "0", "m_timetag": 19921231,
                                     "v": 1.}])
            E._snapshot_write(extra, "financial/Income/000008.SZ", asof,
                              tab, private)
            def changed(code, name, workspace, **kwargs):
                if name == "Income":
                    return [{"_index": "0", "m_timetag": 19921231,
                             "v": 99.},
                            {"_index": "1", "m_timetag": 19931231,
                             "v": 2.}]
                return [{"_index": "0", "holder": "X"}]
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()), \
                 patch.object(E, "_read_financial_isolated",
                              side_effect=changed):
                with self.assertRaisesRegex(ValueError, "removed or revised"):
                    R.reconcile(
                        root, asof=asof, baseline_asof=asof, apply=True,
                        workspace=private,
                        expected_minimums={"Income": 2,
                                           "Top10FlowHolder": 1},
                        progress=lambda _: None)
            self.assertEqual(E._verified_financial_snapshot(
                extra, "000008.SZ", "Income", asof), 1)
            self.assertFalse(E._financial_active_path(
                extra, "000008.SZ", "Income", asof).exists())
            self.assertFalse((private / "financial-repair.jsonl").exists())

    def test_financial_active_manifest_rejects_bogus_and_keeps_strict_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            extra = Path(tmp) / "qmt_extra"
            private = Path(tmp) / "private"
            asof = "2026-11-16"
            a = E.snapshot_table(
                asof, "000008.SZ", "Income", [{"v": 1}])
            b = E.snapshot_table(
                asof, "000008.SZ", "Income", [{"v": 2}])
            p = E._snapshot_path(
                extra, "financial/Income/000008.SZ", asof, a)
            E._snapshot_write(extra, "financial/Income/000008.SZ", asof,
                              a, private)
            E._snapshot_write(extra, "financial/Income/000008.SZ", asof,
                              b, private)
            with self.assertRaisesRegex(ValueError, "Ambiguous"):
                E._verified_financial_snapshot(
                    extra, "000008.SZ", "Income", asof)
            E._pin_financial_snapshot(extra, "000008.SZ", "Income", asof, p)
            self.assertEqual(E._verified_financial_snapshot(
                extra, "000008.SZ", "Income", asof), 1)
            pin = E._financial_active_path(extra, "000008.SZ", "Income", asof)
            doc = json.loads(pin.read_text(encoding="utf-8"))
            doc["filename"] = asof + "-0000000000000000.parquet"
            pin.write_text(E.canonical_json(doc), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Missing QMT financial active"):
                E._verified_financial_snapshot(
                    extra, "000008.SZ", "Income", asof)

    def test_financial_cached_only_worker_never_triggers_qmt_download(self):
        import qmt_extra_financial_worker as W
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeXt()
            output = Path(tmp) / "cache.json"
            W.collect(fake, "600000.SH", "Balance", output,
                      cached_only=True, progress=lambda _: None)
            doc = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(doc["table"], "Balance")
            self.assertEqual(len(doc["records"]), 1)
            self.assertFalse(fake.download_calls)

    def test_repair_crash_before_switch_still_selects_original_version(self):
        import contextlib
        import qmt_extra_financial_reconcile as R
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            asof = datetime.now(L.UTC8).date().isoformat()
            state = E._state(extra, private)
            state["cursor"]["financial"] = "000009.SZ"
            E._save_state(state, private)
            old = [{"_index": "0", "v": 1}]
            E._snapshot_write(extra, "financial/Income/000008.SZ", asof,
                              E.snapshot_table(
                                  asof, "000008.SZ", "Income", old), private)
            original_pin = E._pin_financial_snapshot
            pins = []
            def fail_on_new_pin(*args, **kwargs):
                pins.append(args[-1].name)
                if len(pins) == 2:
                    raise OSError("Simulated interrupted active pin switch")
                return original_pin(*args, **kwargs)
            def cached(code, name, workspace, **kwargs):
                return ([*old, {"_index": "1", "v": 2}]
                        if name == "Income" else [{"_index": "0", "holder": 1}])
            params = {"asof": asof, "baseline_asof": asof,
                      "apply": True, "workspace": private,
                      "expected_minimums": {"Income": 2,
                                             "Top10FlowHolder": 1},
                      "progress": lambda _: None}
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()), \
                 patch.object(E, "_read_financial_isolated",
                              side_effect=cached), \
                 patch.object(E, "_pin_financial_snapshot",
                              side_effect=fail_on_new_pin):
                with self.assertRaisesRegex(OSError, "interrupted"):
                    R.reconcile(root, **params)
            self.assertEqual(E._verified_financial_snapshot(
                extra, "000008.SZ", "Income", asof), 1)
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()), \
                 patch.object(E, "_read_financial_isolated",
                              side_effect=cached):
                R.reconcile(root, **params)
            self.assertEqual(E._verified_financial_snapshot(
                extra, "000008.SZ", "Income", asof), 2)
            self.assertEqual(E._verified_financial_snapshot(
                extra, "000008.SZ", "Top10FlowHolder", asof), 1)

    def test_offline_audit_follows_active_financial_snapshot_pointer(self):
        import qmt_extra_financial_audit as AUDIT
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            asof = "2026-11-16"
            old = E.snapshot_table(
                asof, "000008.SZ", "Income", [{"m_timetag": 19921231}])
            new = E.snapshot_table(
                asof, "000008.SZ", "Income", [
                    {"m_timetag": 19921231}, {"m_timetag": 20260930}])
            for tab in (old, new):
                E._snapshot_write(extra, "financial/Income/000008.SZ",
                                  asof, tab, private)
            selected = E._snapshot_path(
                extra, "financial/Income/000008.SZ", asof, new)
            E._pin_financial_snapshot(extra, "000008.SZ", "Income",
                                      asof, selected)
            audit = AUDIT.audit(root, "000008.SZ", asof, workspace=private)
            self.assertEqual(audit["tables"]["Income"]["rows"], 2)
            self.assertEqual(audit["tables"]["Income"]["raw_m_timetag_max"],
                             "20260930")

    def test_bulk_scan_preview_has_no_qmt_writes(self):
        import qmt_extra_financial_bulk as BULK
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            workspace = Path(tmp) / "private"
            logs = []
            result = BULK.scan(
                root, xt=FakeXt(), apply=False, max_symbols=2,
                workspace=workspace, progress=logs.append)
            self.assertEqual(result["status"],
                             "BOUNDED_FINANCIAL_READONLY_PREVIEW")
            self.assertEqual(result["next"], ["600000.SH"])
            self.assertEqual(result["symbols_processed"], 0)
            self.assertFalse(workspace.exists())
            self.assertFalse(E._storage(root).exists())
            self.assertIn("QMT_FINANCIAL_BULK_SUMMARY=", logs[0])

    def test_bulk_scan_two_then_one_then_no_wrap(self):
        import contextlib
        import qmt_extra_financial_bulk as BULK
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            workspace = Path(tmp) / "private"
            xt = FakeXt()
            xt.sectors["沪深A股"] = [
                "600000.SH", "600001.SH", "600002.SH"]
            now = datetime(2026, 11, 16, 23, 30, tzinfo=L.UTC8)
            worker_calls = []
            def fake_worker(code, table, workspace, **kwargs):
                worker_calls.append((code, table))
                return [{"_index": "20260930", "m_timetag": 20260930}]
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()), \
                 patch.object(E, "_read_financial_isolated",
                              side_effect=fake_worker):
                first = BULK.scan(
                    root, xt=xt, apply=True, max_symbols=2,
                    workspace=workspace, clock=lambda: now,
                    timeout_seconds=30, progress=lambda _: None)
                second = BULK.scan(
                    root, xt=xt, apply=True, max_symbols=2,
                    workspace=workspace, clock=lambda: now,
                    timeout_seconds=30, progress=lambda _: None)
                third = BULK.scan(
                    root, xt=xt, apply=True, max_symbols=2,
                    workspace=workspace, clock=lambda: now,
                    timeout_seconds=30, progress=lambda _: None)
            self.assertEqual(first["status"], "PAUSED_SYMBOL_LIMIT")
            self.assertEqual(first["symbols_processed"], 2)
            self.assertEqual(first["last_cursor"], "600001.SH")
            self.assertEqual(second["status"],
                             "SCAN_EXHAUSTED_COVERAGE_UNVERIFIED")
            self.assertEqual(second["symbols_processed"], 1)
            self.assertEqual(second["last_cursor"], "600002.SH")
            self.assertEqual(third["symbols_processed"], 0)
            self.assertEqual(third["last_cursor"], "600002.SH")
            self.assertEqual(len(worker_calls), 3 * len(E.FIN_TABLES))
            self.assertEqual(E._state(E._storage(root), workspace)
                             ["cursor"]["financial"], "600002.SH")

    def test_bulk_scan_defers_failed_stock_but_keeps_progress(self):
        import contextlib
        import qmt_extra_financial_bulk as BULK
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            workspace = Path(tmp) / "private"
            xt = FakeXt()
            xt.sectors["沪深A股"] = ["600000.SH", "600001.SH"]
            now = datetime(2026, 11, 16, 23, 30, tzinfo=L.UTC8)
            def fake_worker(code, table, workspace, **kwargs):
                if code == "600000.SH" and table == "Balance":
                    raise TimeoutError("Synthetic upstream timeout")
                return [{"_index": "20260930", "m_timetag": 20260930}]
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()), \
                 patch.object(E, "_read_financial_isolated",
                              side_effect=fake_worker):
                result = BULK.scan(
                    root, xt=xt, apply=True, max_symbols=3,
                    timeout_seconds=30, workspace=workspace,
                    clock=lambda: now, progress=lambda _: None)
            self.assertEqual(result["status"],
                             "SCAN_EXHAUSTED_PENDING_RETRIES")
            self.assertEqual(result["symbols_processed"], 1)
            self.assertEqual(result["symbols_deferred"], 1)
            self.assertEqual(result["pending_retry_count"], 1)
            saved = E._state(E._storage(root), workspace)
            self.assertEqual(saved["cursor"]["financial"], "600001.SH")
            self.assertEqual(sorted(saved["financial_pending"]),
                             ["600000.SH"])

    def test_bulk_scan_protects_scheduled_market_window(self):
        import qmt_extra_financial_bulk as BULK
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            workspace = Path(tmp) / "private"
            xt = FakeXt()
            with patch.object(E, "run",
                              side_effect=AssertionError("QMT must not run")):
                blocked = BULK.scan(
                    root, xt=xt, apply=True, timeout_seconds=180,
                    workspace=workspace, max_symbols=3,
                    clock=lambda: datetime(2026, 11, 16, 21, 45,
                                           tzinfo=L.UTC8),
                    progress=lambda _: None)
                near = BULK.scan(
                    root, xt=xt, apply=True, timeout_seconds=180,
                    workspace=workspace, max_symbols=3,
                    clock=lambda: datetime(2026, 11, 16, 20, 50,
                                           tzinfo=L.UTC8),
                    progress=lambda _: None)
            self.assertEqual(blocked["status"],
                             "PAUSED_PROTECTED_2130_WINDOW")
            self.assertEqual(near["status"],
                             "PAUSED_INSUFFICIENT_PRE_2130_WORST_CASE_WINDOW")
            self.assertFalse(workspace.exists())

    def test_bulk_scan_stops_on_time_budget_before_batch(self):
        import qmt_extra_financial_bulk as BULK
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            start = datetime(2026, 11, 16, 23, 30, tzinfo=L.UTC8)
            ticks = iter([start, start + timedelta(minutes=2)])
            with patch.object(E, "run",
                              side_effect=AssertionError("QMT must not run")):
                result = BULK.scan(
                    root, xt=FakeXt(), apply=True, max_symbols=3,
                    max_minutes=1, workspace=Path(tmp) / "private",
                    clock=lambda: next(ticks), progress=lambda _: None)
            self.assertEqual(result["status"], "PAUSED_TIME_BUDGET")
            self.assertEqual(result["symbols_processed"], 0)

    def test_prepared_financial_universe_does_not_need_etf_discovery(self):
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            private = Path(tmp) / "private"
            xt = FakeXt()
            xt.sectors["ETF"] = []
            xt.sectors["沪深基金"] = []
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()), \
                 patch.object(E, "_read_financial_isolated",
                              return_value=[{"_index": "0", "value": 1.}]):
                result = E.run(
                    root, xt=xt, apply=True, section="financial",
                    financial_universe=["600000.SH"],
                    financial_continue_on_error=True,
                    financial_timeout_seconds=30,
                    stock_limit=1, workspace=private,
                    today=date(2026, 11, 16), progress=lambda _: None)
            self.assertEqual(result["sections"]["financial"]["symbols_processed"], 1)
            self.assertEqual(result["sections"]["financial"]["universe_symbols"], 1)
            self.assertEqual(E._state(E._storage(root), private)
                             ["cursor"]["financial"], "600000.SH")

    def test_prepared_financial_universe_rejects_duplicates_and_other_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            xt = FakeXt()
            base = {"xt": xt, "apply": False,
                    "financial_continue_on_error": True,
                    "section": "financial", "progress": lambda _: None}
            with self.assertRaisesRegex(ValueError, "Invalid prepared"):
                E.run(root, financial_universe=[
                    "600000.SH", "600000.SH"], **base)
            with self.assertRaisesRegex(ValueError, "Unsupported QMT security code"):
                E.run(root, financial_universe=["NOT_A_STOCK"], **base)
            with self.assertRaisesRegex(ValueError, "opt-in financial-only"):
                E.run(root, financial_universe=["600000.SH"],
                      xt=xt, section="all", apply=False)

    def test_bulk_scan_rechecks_blackout_after_stock_catalog_discovery(self):
        import qmt_extra_financial_bulk as BULK
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            starts = iter([
                datetime(2026, 11, 16, 20, 0, tzinfo=L.UTC8),
                datetime(2026, 11, 16, 20, 0, tzinfo=L.UTC8),
                datetime(2026, 11, 16, 20, 55, tzinfo=L.UTC8)])
            with patch.object(E, "run",
                              side_effect=AssertionError("Too near blackout")):
                result = BULK.scan(
                    root, xt=FakeXt(), apply=True, max_symbols=2,
                    timeout_seconds=180, workspace=Path(tmp) / "private",
                    clock=lambda: next(starts), progress=lambda _: None)
            self.assertEqual(result["status"],
                             "PAUSED_INSUFFICIENT_PRE_2130_WORST_CASE_WINDOW")
            self.assertEqual(result["symbols_processed"], 0)

    def test_unattended_financial_finishes_once_without_wrapping(self):
        import qmt_extra_financial_unattended as U
        now = datetime(2026, 11, 17, 0, 30, tzinfo=L.UTC8)
        calls = []
        def fake_scan(*args, **kwargs):
            calls.append(kwargs["apply"])
            return {"status": "SCAN_EXHAUSTED_PENDING_RETRIES",
                    "symbols_processed": 4, "symbols_deferred": 1,
                    "last_cursor": "920000.BJ", "pending_retry_count": 1}
        result = U.run_foreground(
            Path("D:/stock"), xt=FakeXt(), scan_fn=fake_scan,
            clock=lambda: now, sleep=lambda _: self.fail("Unexpected sleep"),
            progress=lambda _: None)
        self.assertEqual(calls, [True])
        self.assertTrue(result["scan_exhausted"])
        self.assertEqual(result["status"], "SCAN_EXHAUSTED_PENDING_RETRIES")
        self.assertEqual(result["processed_total"], 4)
        self.assertEqual(result["pending_retry_count"], 1)

    def test_unattended_financial_resumes_only_after_protected_window(self):
        import qmt_extra_financial_unattended as U
        instant = [datetime(2026, 11, 16, 21, 10, tzinfo=L.UTC8)]
        calls = []
        waits = []
        def fake_scan(*args, **kwargs):
            calls.append(instant[0])
            return {"status": ("PAUSED_PROTECTED_2130_WINDOW"
                               if len(calls) == 1 else
                               "SCAN_EXHAUSTED_COVERAGE_UNVERIFIED"),
                    "symbols_processed": 0 if len(calls) == 1 else 5,
                    "symbols_deferred": 0,
                    "last_cursor": "000026.SZ", "pending_retry_count": 0}
        def fake_sleep(seconds):
            waits.append(seconds)
            instant[0] += timedelta(seconds=seconds)
        result = U.run_foreground(
            Path("D:/stock"), xt=FakeXt(), scan_fn=fake_scan,
            clock=lambda: instant[0], sleep=fake_sleep,
            progress=lambda _: None)
        self.assertEqual(result["sessions"], 2)
        self.assertEqual(result["processed_total"], 5)
        self.assertEqual(len(waits), 1)
        self.assertEqual(instant[0],
                         datetime(2026, 11, 16, 23, 5, tzinfo=L.UTC8))
        self.assertEqual(calls[-1], instant[0])

    def test_unattended_financial_time_budget_with_progress_resumes(self):
        import qmt_extra_financial_unattended as U
        now = datetime(2026, 11, 17, 1, 0, tzinfo=L.UTC8)
        calls = []
        def fake_scan(*args, **kwargs):
            calls.append(1)
            return {"status": ("PAUSED_TIME_BUDGET" if len(calls) == 1
                               else "SCAN_EXHAUSTED_COVERAGE_UNVERIFIED"),
                    "symbols_processed": 3 if len(calls) == 1 else 2,
                    "symbols_deferred": 0, "last_cursor": "000030.SZ",
                    "pending_retry_count": 0}
        result = U.run_foreground(
            Path("D:/stock"), xt=FakeXt(), scan_fn=fake_scan,
            clock=lambda: now, sleep=lambda _: self.fail("Should not sleep"),
            progress=lambda _: None)
        self.assertEqual(result["sessions"], 2)
        self.assertEqual(result["processed_total"], 5)

    def test_unattended_financial_zero_progress_budget_fails_closed(self):
        import qmt_extra_financial_unattended as U
        now = datetime(2026, 11, 17, 1, 0, tzinfo=L.UTC8)
        with self.assertRaisesRegex(RuntimeError, "made no progress"):
            U.run_foreground(
                Path("D:/stock"), xt=FakeXt(),
                scan_fn=lambda *a, **kw: {
                    "status": "PAUSED_TIME_BUDGET",
                    "symbols_processed": 0,
                    "symbols_deferred": 0, "last_cursor": "000026.SZ",
                    "pending_retry_count": 0},
                clock=lambda: now, sleep=lambda _: None,
                progress=lambda _: None)

    def test_unattended_financial_unexpected_error_is_not_retried(self):
        import qmt_extra_financial_unattended as U
        now = datetime(2026, 11, 17, 1, 0, tzinfo=L.UTC8)
        calls = []
        def fail(*args, **kwargs):
            calls.append(1)
            raise OSError("Corrupt Parquet (simulated)")
        with self.assertRaisesRegex(OSError, "Corrupt Parquet"):
            U.run_foreground(
                Path("D:/stock"), xt=FakeXt(), scan_fn=fail,
                clock=lambda: now, sleep=lambda _: None,
                progress=lambda _: None)
        self.assertEqual(len(calls), 1)

    def test_unattended_financial_days_horizon_fails_safe(self):
        import qmt_extra_financial_unattended as U
        start = datetime(2026, 11, 17, 1, 0, tzinfo=L.UTC8)
        ticks = iter([start, start + timedelta(days=2)])
        result = U.run_foreground(
            Path("D:/stock"), xt=FakeXt(), max_days=1,
            scan_fn=lambda *args, **kwargs: self.fail("Must not scan"),
            clock=lambda: next(ticks), sleep=lambda _: None,
            progress=lambda _: None)
        self.assertEqual(result["status"], "STOPPED_MAX_DAYS")
        self.assertEqual(result["sessions"], 0)

    def test_unattended_financial_keep_awake_opt_in_guard(self):
        import qmt_extra_financial_unattended as U
        with U.keep_awake(False):
            pass
        with patch.object(U.sys, "platform", "linux"):
            with self.assertRaisesRegex(RuntimeError, "requires Windows"):
                with U.keep_awake(True):
                    pass

    def test_cache_worker_reads_two_stocks_nine_tables_without_download(self):
        import qmt_extra_financial_cache_worker as W
        class XT:
            def __init__(self):
                self.calls = []
            def get_financial_data(self, codes, tables, **kwargs):
                self.calls.append(("read", tuple(codes), tuple(tables)))
                return {code: {"Income": FakeFrame([
                    {"m_timetag": 20260930, "income": 1}])} for code in codes}
            def download_financial_data2(self, *args, **kwargs):
                self.calls.append(("download",))
        with tempfile.TemporaryDirectory() as tmp:
            xt = XT()
            path = Path(tmp) / "private.json"
            W.collect(xt, ["600000.SH", "600001.SH"], path,
                      progress=lambda _: None)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(payload["records"]),
                             {"600000.SH", "600001.SH"})
            self.assertEqual(payload["records"]["600000.SH"]["Income"][0]
                             ["m_timetag"], 20260930)
            self.assertEqual(len(payload["records"]["600000.SH"]), 9)
            self.assertEqual(payload["records"]["600000.SH"]["PerShare"], [])
            self.assertEqual(len(xt.calls), 1)
            self.assertEqual(xt.calls[0][0], "read")

    def test_cache_worker_daily_only_downloads_announce_window(self):
        import qmt_extra_financial_cache_worker as W
        class XT:
            def __init__(self):
                self.calls = []
            def download_financial_data2(self, codes, tables,
                                         start_time, end_time):
                self.calls.append(("daily", codes, tables,
                                   start_time, end_time))
            def get_financial_data(self, codes, tables, **kwargs):
                self.calls.append(("read", codes, tables))
                return {codes[0]: {"Balance": FakeFrame(
                    [{"m_timetag": 20260930}])}}
        with tempfile.TemporaryDirectory() as tmp:
            xt = XT()
            W.collect(xt, ["600000.SH"], Path(tmp) / "out.json",
                      mode="daily", start="20260717", end="20261117",
                      progress=lambda _: None)
            self.assertEqual(len(xt.calls), 2)
            self.assertEqual(xt.calls[0][0], "daily")
            self.assertEqual(xt.calls[0][3:], ("20260717", "20261117"))
            self.assertNotIn("PerShare", xt.calls[0][2])
            self.assertEqual(len(xt.calls[1][2]), 9)

    def test_cache_import_explicit_finance_dat_universe_adds_historical_bj(self):
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            finance = Path(tmp) / "Finance"
            for market, code in (("SZ", "000001"),
                                 ("SH", "600000"), ("BJ", "920001")):
                folder = finance / market / "86400"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / (code + "_7001.DAT")).write_bytes(b"opaque")
                (folder / "ignore.txt").write_bytes(b"not-finance")
            codes, meta = I._stock_universe(FakeXt(), finance)
            self.assertEqual(codes, [
                "000001.SZ", "600000.SH", "920001.BJ"])
            self.assertEqual(meta["finance_file_symbols"], 3)
            self.assertEqual(meta["finance_only_symbols"], 2)
            self.assertEqual(meta["source_scope"],
                             "QMT_SECTOR_PLUS_EXPLICIT_FINANCE_DAT_NAMES")

    def test_cache_import_missing_explicit_finance_dir_fails(self):
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "Missing or redirected"):
                I._stock_universe(FakeXt(), Path(tmp) / "no-finance")
            empty = Path(tmp) / "Finance"
            empty.mkdir()
            with self.assertRaisesRegex(ValueError, "No stock-level"):
                I._stock_universe(FakeXt(), empty)

    def test_cache_import_preview_never_creates_progress_or_parquet(self):
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            private = Path(tmp) / "private"
            result = I.run(root, xt=FakeXt(), mode="cache",
                           apply=False, workspace=private,
                           max_symbols=2, progress=lambda _: None)
            self.assertEqual(result["status"], "PREVIEW")
            self.assertEqual(result["selected"], 1)
            self.assertFalse(private.exists())
            self.assertFalse(E._storage(root).exists())

    def test_cache_import_commit_skips_identical_and_keeps_original(self):
        import contextlib
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            asof = "2026-11-17"
            old = [{"_index": "0", "m_timetag": 19921231, "v": 1}]
            old_tab = E.snapshot_table(asof, "600000.SH", "Income", old)
            E._snapshot_write(extra, "financial/Income/600000.SH",
                              asof, old_tab, private)
            original = E._financial_snapshot_file(
                extra, "600000.SH", "Income", asof)
            old_sha = E.L.hash_file(original)
            calls = []
            def worker(group, mode, day, lookback, workspace, timeout,
                       **kwargs):
                calls.append((group, mode))
                values = {table: [] for table in E.FIN_TABLES}
                values["Income"] = [
                    *old, {"_index": "1", "m_timetag": 20260930, "v": 2}]
                values["Balance"] = [{"_index": "0", "asset": 99}]
                return {code: values for code in group}, []
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                result = I.run(
                    root, xt=FakeXt(), mode="cache", apply=True,
                    batch_size=1, workspace=private, worker=worker,
                    clock=lambda: datetime(2026, 11, 17, 1, 30,
                                           tzinfo=L.UTC8),
                    progress=lambda _: None)
                again = I.run(
                    root, xt=FakeXt(), mode="cache", apply=True,
                    batch_size=1, workspace=private, worker=worker,
                    clock=lambda: datetime(2026, 11, 17, 1, 30,
                                           tzinfo=L.UTC8),
                    progress=lambda _: None)
            self.assertEqual(result["status"], "SOURCE_UNIVERSE_EXHAUSTED")
            self.assertEqual(result["processed"], 1)
            self.assertEqual(result["new_snapshots"], 2)
            self.assertEqual(result["empty_tables"], 7)
            self.assertEqual(again["processed"], 0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(E._verified_financial_snapshot(
                extra, "600000.SH", "Income", asof), 2)
            self.assertEqual(E.L.hash_file(original), old_sha)
            self.assertEqual(len(list(original.parent.glob(
                asof + "-*.parquet"))), 2)
            self.assertEqual(I._state(extra, private)["import_cursor"],
                             "600000.SH")

    def test_cache_import_conflict_queues_stock_and_continues(self):
        import contextlib
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            xt = FakeXt()
            xt.sectors["沪深A股"] = ["600000.SH", "600001.SH"]
            E._snapshot_write(
                extra, "financial/Income/600000.SH", "2026-11-16",
                E.snapshot_table("2026-11-16", "600000.SH", "Income",
                                 [{"_index": "0", "v": 1}]), private)
            def worker(group, mode, day, lookback, workspace, timeout,
                       **kwargs):
                values = {table: [] for table in E.FIN_TABLES}
                values["Income"] = [{"_index": "0", "v": 99}]
                return {code: values for code in group}, []
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                result = I.run(root, xt=xt, mode="cache", apply=True,
                               batch_size=2, workspace=private, worker=worker,
                               clock=lambda: datetime(2026, 11, 17, 1, 0,
                                                      tzinfo=L.UTC8),
                               progress=lambda _: None)
            self.assertEqual(result["pending_added"], 1)
            self.assertEqual(result["processed"], 1)
            self.assertEqual(result["end_cursor"], "600001.SH")
            self.assertEqual(I._state(extra, private)["pending"]
                             ["600000.SH"]["reason"],
                             "SOURCE_HISTORY_CONFLICT")
            self.assertEqual(E._verified_financial_snapshot(
                extra, "600000.SH", "Income", "2026-11-16"), 1)
            self.assertIsNone(E._verified_financial_snapshot(
                extra, "600000.SH", "Income", "2026-11-17"))
            self.assertEqual(E._verified_financial_snapshot(
                extra, "600001.SH", "Income", "2026-11-17"), 1)

    def test_cache_import_union_of_all_old_effective_days(self):
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            for day, value in (("2026-11-15", 101),
                               ("2026-11-16", 202)):
                E._snapshot_write(
                    extra, "financial/Income/600000.SH", day,
                    E.snapshot_table(
                        day, "600000.SH", "Income",
                        [{"_index": "0", "v": value}]), private)
            data = {table: [] for table in E.FIN_TABLES}
            data["Income"] = [{"_index": "0", "v": 202}]
            with self.assertRaisesRegex(ValueError,
                                        "SOURCE_HISTORY_CONFLICT"):
                I._plan_symbol(extra, "600000.SH", "2026-11-17", data)

    def test_cache_import_missing_cache_pending_and_retry(self):
        import contextlib
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            found = [False]
            def worker(group, mode, day, lookback, workspace, timeout,
                       **kwargs):
                if not found[0]:
                    return {}, group
                data = {table: [] for table in E.FIN_TABLES}
                data["Balance"] = [{"_index": "0", "asset": 12}]
                return {code: data for code in group}, []
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                first = I.run(
                    root, xt=FakeXt(), mode="cache", apply=True,
                    batch_size=1, workspace=private, worker=worker,
                    clock=lambda: datetime(2026, 11, 17, 1, 0,
                                           tzinfo=L.UTC8),
                    progress=lambda _: None)
                found[0] = True
                second = I.run(
                    root, xt=FakeXt(), mode="cache", apply=True,
                    batch_size=1, retry_pending=True,
                    workspace=private, worker=worker,
                    clock=lambda: datetime(2026, 11, 17, 1, 0,
                                           tzinfo=L.UTC8),
                    progress=lambda _: None)
            self.assertEqual(first["pending_added"], 1)
            self.assertEqual(first["processed"], 0)
            self.assertEqual(second["processed"], 1)
            self.assertEqual(I._state(extra, private)["pending"], {})
            self.assertEqual(I._state(extra, private)["import_cursor"],
                             "600000.SH")

    def test_cache_import_daily_new_day_incremental_window(self):
        import contextlib
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            seeded = I._state(extra, private)
            seeded["import_cursor"] = "600000.SH"
            I._save_state(private, seeded)
            calls = []
            def worker(group, mode, day, lookback, workspace, timeout,
                       **kwargs):
                calls.append((mode, day, lookback))
                rows = {table: [] for table in E.FIN_TABLES}
                rows["Balance"] = [{"_index": "0", "v": 1}]
                return {code: rows for code in group}, []
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                first = I.run(
                    root, xt=FakeXt(), mode="daily", apply=True,
                    workspace=private, worker=worker,
                    clock=lambda: datetime(2026, 11, 17, 23, 30,
                                           tzinfo=L.UTC8),
                    progress=lambda _: None)
                second = I.run(
                    root, xt=FakeXt(), mode="daily", apply=True,
                    workspace=private, worker=worker,
                    clock=lambda: datetime(2026, 11, 18, 23, 30,
                                           tzinfo=L.UTC8),
                    progress=lambda _: None)
            self.assertEqual(first["new_snapshots"], 1)
            self.assertEqual(second["new_snapshots"], 0)
            self.assertEqual(calls, [("daily", "2026-11-17", 120),
                                     ("daily", "2026-11-18", 120)])
            self.assertEqual(I._state(extra, private)["daily_date"],
                             "2026-11-18")
            self.assertEqual(I._state(extra, private)["daily_cursor"],
                             "600000.SH")

    def test_cache_daily_partial_sweep_resumes_across_days_and_rotates_on_end(self):
        import contextlib
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            xt = FakeXt()
            xt.sectors["沪深A股"] = [
                "600000.SH", "600001.SH", "600002.SH"]
            state = I._state(extra, private)
            state["import_cursor"] = "600002.SH"
            state["pending"] = {"000001.SZ": {
                "reason": "SOURCE_HISTORY_CONFLICT", "asof": "2026-11-16",
                "attempts": 1, "detail": "previous Capital history mismatch"}}
            I._save_state(private, state)
            calls = []

            def worker(group, mode, day, lookback, workspace, timeout,
                       **kwargs):
                calls.append((day, tuple(group)))
                rows = {table: [] for table in E.FIN_TABLES}
                rows["Balance"] = [{"_index": "0", "v": 1}]
                return {code: rows for code in group}, []

            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                results = []
                for day in (17, 18, 19, 20):
                    results.append(I.run(
                        root, xt=xt, mode="daily", apply=True,
                        max_symbols=1, batch_size=1,
                        workspace=private, worker=worker,
                        clock=lambda day=day: datetime(
                            2026, 11, day, 16, 35, tzinfo=L.UTC8),
                        progress=lambda _: None))
            self.assertEqual(calls, [
                ("2026-11-17", ("600000.SH",)),
                ("2026-11-18", ("600001.SH",)),
                ("2026-11-19", ("600002.SH",)),
                ("2026-11-20", ("600000.SH",))])
            self.assertEqual(
                [r["daily_sweep_start"] for r in results],
                ["2026-11-17", "2026-11-17",
                 "2026-11-17", "2026-11-20"])
            self.assertEqual(
                [r["daily_remaining_unvisited"] for r in results],
                [2, 1, 0, 2])
            self.assertFalse(results[0]["daily_sweep_reached_end"])
            self.assertTrue(results[2]["daily_sweep_reached_end"])
            self.assertEqual(results[2]["status"],
                             "SOURCE_UNIVERSE_EXHAUSTED")
            self.assertFalse(results[3]["daily_sweep_reached_end"])
            self.assertEqual(I._state(extra, private)["daily_cursor"],
                             "600000.SH")
            self.assertEqual(set(I._state(extra, private)["pending"]),
                             {"000001.SZ"})

    def test_cache_daily_legacy_partial_resume_preview_no_write(self):
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            xt = FakeXt()
            xt.sectors["沪深A股"] = [
                "600000.SH", "600001.SH", "600002.SH"]
            state = I._state(extra, private)
            state["import_cursor"] = "600002.SH"
            state["daily_date"] = "2026-11-16"
            state["daily_cursor"] = "600000.SH"
            for name in ("daily_sweep_start", "daily_sweep_reached_end",
                         "daily_sweep_finished"):
                state.pop(name)
            I._save_state(private, state)
            saved = I._state_file(private).read_bytes()
            result = I.run(
                root, xt=xt, mode="daily", apply=False,
                workspace=private, max_symbols=1,
                clock=lambda: datetime(2026, 11, 17, 16, 35,
                                       tzinfo=L.UTC8),
                progress=lambda _: None)
            self.assertEqual(result["selected_first"], "600001.SH")
            self.assertEqual(result["daily_sweep_start"], "2026-11-16")
            self.assertEqual(result["daily_remaining_unvisited"], 2)
            self.assertFalse(result["daily_sweep_reached_end"])
            self.assertEqual(I._state_file(private).read_bytes(), saved)

    def test_cache_daily_cross_date_failure_never_advances_checkpoint(self):
        import contextlib
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            xt = FakeXt()
            xt.sectors["沪深A股"] = ["600000.SH", "600001.SH"]
            state = I._state(extra, private)
            state["import_cursor"] = "600001.SH"
            I._save_state(private, state)
            data = {table: [] for table in E.FIN_TABLES}
            data["Balance"] = [{"_index": "0", "v": 3}]
            def success(group, *args, **kwargs):
                return {code: data for code in group}, []
            def fail(*args, **kwargs):
                raise TimeoutError("Simulated next-day QMT timeout")
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                first = I.run(
                    root, xt=xt, mode="daily", apply=True,
                    max_symbols=1, batch_size=1, workspace=private,
                    worker=success,
                    clock=lambda: datetime(2026, 11, 17, 16, 35,
                                           tzinfo=L.UTC8),
                    progress=lambda _: None)
                before = I._state_file(private).read_bytes()
                with self.assertRaisesRegex(TimeoutError, "Simulated"):
                    I.run(
                        root, xt=xt, mode="daily", apply=True,
                        max_symbols=1, batch_size=1, workspace=private,
                        worker=fail,
                        clock=lambda: datetime(2026, 11, 18, 16, 35,
                                               tzinfo=L.UTC8),
                        progress=lambda _: None)
                self.assertEqual(I._state_file(private).read_bytes(), before)
                second = I.run(
                    root, xt=xt, mode="daily", apply=True,
                    max_symbols=1, batch_size=1, workspace=private,
                    worker=success,
                    clock=lambda: datetime(2026, 11, 19, 16, 35,
                                           tzinfo=L.UTC8),
                    progress=lambda _: None)
            self.assertEqual(first["end_cursor"], "600000.SH")
            self.assertEqual(second["end_cursor"], "600001.SH")
            self.assertEqual(second["daily_sweep_start"], "2026-11-17")
            self.assertEqual(second["daily_remaining_unvisited"], 0)
            self.assertTrue(second["daily_sweep_reached_end"])

    def test_cache_import_daily_requires_initial_scan_completion(self):
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            private = Path(tmp) / "private"
            with self.assertRaisesRegex(ValueError,
                                        "Initial QMT financial cache import"):
                I.run(root, xt=FakeXt(), mode="daily", apply=True,
                      workspace=private, progress=lambda _: None)
            self.assertFalse(I._state_file(private).exists())

    def test_cache_import_worker_failure_preserves_state(self):
        import contextlib
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            def fail(*args, **kwargs):
                raise TimeoutError("Simulated QMT timeout")
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                with self.assertRaisesRegex(TimeoutError, "Simulated"):
                    I.run(
                        root, xt=FakeXt(), apply=True, mode="cache",
                        workspace=private, worker=fail,
                        clock=lambda: datetime(2026, 11, 17, 1, 0,
                                               tzinfo=L.UTC8),
                        progress=lambda _: None)
            self.assertFalse(I._state_file(private).exists())
            self.assertIsNone(E._verified_financial_snapshot(
                extra, "600000.SH", "Balance", "2026-11-17"))

    def test_cache_import_no_2130_blackout_and_no_time_budget(self):
        import contextlib
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            private = Path(tmp) / "private"
            rows = {table: [] for table in E.FIN_TABLES}
            rows["Balance"] = [{"_index": "0", "v": 4}]
            calls = []
            def worker(group, mode, day, lookback, workspace, timeout,
                       **kwargs):
                calls.append((group, mode, day))
                return {code: rows for code in group}, []
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                result = I.run(
                    root, xt=FakeXt(), mode="cache", apply=True,
                    max_minutes=0, workspace=private, worker=worker,
                    clock=lambda: datetime(2026, 11, 17, 21, 30,
                                           tzinfo=L.UTC8),
                    progress=lambda _: None)
            self.assertEqual(result["processed"], 1)
            self.assertEqual(result["time_budget_minutes"], 0)
            self.assertEqual(result["status"], "SOURCE_UNIVERSE_EXHAUSTED")
            self.assertEqual(len(calls), 1)

    def test_financial_daily_2130_is_not_a_scheduled_blackout(self):
        import contextlib
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            state = I._state(extra, private)
            state["import_cursor"] = "600000.SH"
            I._save_state(private, state)
            rows = {table: [] for table in E.FIN_TABLES}
            rows["Balance"] = [{"_index": "0", "v": 4}]
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                result = I.run(
                    root, xt=FakeXt(), mode="daily", apply=True,
                    max_minutes=0, workspace=private,
                    worker=lambda group, *args, **kwargs:
                        ({code: rows for code in group}, []),
                    clock=lambda: datetime(2026, 11, 17, 21, 30,
                                           tzinfo=L.UTC8),
                    progress=lambda _: None)
            self.assertEqual(result["processed"], 1)
            self.assertEqual(result["daily_remaining_unvisited"], 0)
            self.assertTrue(result["daily_sweep_reached_end"])
            self.assertEqual(result["time_budget_minutes"], 0)

    def test_cache_utf8_group_split_defers_only_bad_stock(self):
        import contextlib
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            workspace = Path(tmp) / "private"
            xt = FakeXt()
            symbols = ["600000.SH", "600001.SH", "600002.SH",
                       "600003.SH", "600004.SH"]
            xt.sectors["沪深A股"] = symbols
            calls = []
            bad = "600002.SH"
            repaired = [False]
            def fake_worker(group, mode, day, lookback, work, timeout, **kw):
                calls.append(tuple(group))
                if bad in group and not repaired[0]:
                    raise I.QMTCacheDecodeError("Simulated provider UTF-8 error")
                def recs(code):
                    out = {name: [] for name in E.FIN_TABLES}
                    out["Income"] = [{"_index": "0", "m_timetag": 20260930,
                                      "net": 1}]
                    return out
                return {code: recs(code) for code in group}, []
            fixed_now = datetime(2026, 11, 17, 1, 0, tzinfo=L.UTC8)
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                result = I.run(
                    root, xt=xt, mode="cache", apply=True,
                    batch_size=5, workspace=workspace,
                    worker=fake_worker, clock=lambda: fixed_now,
                    progress=lambda _: None)
                repaired[0] = True
                retry = I.run(
                    root, xt=xt, mode="cache", apply=True,
                    batch_size=5, retry_pending=True, workspace=workspace,
                    worker=fake_worker, clock=lambda: fixed_now,
                    progress=lambda _: None)
            self.assertEqual(result["processed"], 4)
            self.assertEqual(result["pending_added"], 1)
            self.assertEqual(result["end_cursor"], symbols[-1])
            self.assertEqual(result["pending_total"], 1)
            self.assertEqual(I._state(extra, workspace)["pending"], {})
            self.assertEqual(retry["processed"], 1)
            self.assertEqual(retry["pending_total"], 0)
            self.assertEqual(len([x for x in calls if bad in x]), 4)
            for code in symbols:
                self.assertEqual(E._verified_financial_snapshot(
                    extra, code, "Income", "2026-11-17"), 1)

    def test_cache_utf8_three_consecutive_source_failures_halt(self):
        import contextlib
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            extra = E._storage(root)
            private = Path(tmp) / "private"
            xt = FakeXt()
            symbols = ["600000.SH", "600001.SH", "600002.SH",
                       "600003.SH", "600004.SH"]
            xt.sectors["沪深A股"] = symbols
            def fail(*args, **kwargs):
                raise I.QMTCacheDecodeError("Provider UTF8 failed")
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                with self.assertRaisesRegex(
                        RuntimeError, "Three consecutive"):
                    I.run(root, xt=xt, mode="cache", apply=True,
                          batch_size=5, workspace=private, worker=fail,
                          clock=lambda: datetime(2026, 11, 17, 1, 0,
                                                 tzinfo=L.UTC8),
                          progress=lambda _: None)
            saved = I._state(extra, private)
            self.assertEqual(saved["import_cursor"], "600002.SH")
            self.assertEqual(len(saved["pending"]), 3)
            self.assertEqual(set(entry["reason"] for entry
                                 in saved["pending"].values()),
                             {"CACHE_DECODE_ERROR"})

    def test_cache_utf8_worker_exit_retries_once_then_classifies(self):
        import qmt_extra_financial_cache_import as I
        with tempfile.TemporaryDirectory() as tmp:
            from subprocess import CompletedProcess
            with patch.object(I.subprocess, "run",
                              return_value=CompletedProcess([], 85)) as run:
                with self.assertRaises(I.QMTCacheDecodeError):
                    I._worker_batch(
                        ["600000.SH"], "cache", "2026-11-17", 120,
                        Path(tmp), 30, progress=lambda _: None)
            self.assertEqual(run.call_count, 2)

    def test_cache_utf8_does_not_hide_unrelated_worker_error(self):
        import qmt_extra_financial_cache_import as I
        with self.assertRaisesRegex(RuntimeError, "Unrelated QMT error"):
            I._recover_utf8_group(
                lambda *a, **k: (_ for _ in ()).throw(
                    RuntimeError("Unrelated QMT error")),
                ["600000.SH", "600001.SH"], "cache",
                "2026-11-17", 120, Path("D:/not-used"), 30,
                progress=lambda _: None)

    def test_capital_readonly_diagnosis_identifies_field_value_drift(self):
        import qmt_extra_financial_conflict_diagnose as D
        old = [{"_index": "0", "m_timetag": 20240930,
                "capital": 100.0, "source": "old"}]
        fresh = [{"_index": "1", "m_timetag": 20240930,
                  "capital": 110.0, "source": "old"}]
        result = D.compare(old, fresh)
        self.assertEqual(result["old_missing_from_new"], 1)
        self.assertEqual(result["new_not_in_old"], 1)
        fields = result["report_key_differences"]["changed_field_frequency_top"]
        self.assertIn(["capital", 1], [list(x) for x in fields])
        self.assertEqual(result["report_key_differences"]["matched_changed"], 1)

    def test_capital_readonly_diagnosis_ignores_pandas_row_index(self):
        import qmt_extra_financial_conflict_diagnose as D
        old = [{"_index": "old", "m_timetag": 20240930,
                "capital": 100.0}]
        fresh = [{"_index": "different", "m_timetag": 20240930,
                  "capital": 100.0}]
        result = D.compare(old, fresh)
        self.assertEqual(result["old_missing_from_new"], 0)
        self.assertEqual(result["new_not_in_old"], 0)
        self.assertEqual(result["report_key_differences"]["matched_identical"], 1)

    def test_malformed_financial_pending_queue_fails_closed(self):
        good = {"cursor": {"financial": "600001.SH"},
                "financial_pending": {"600000.SH": {
                    "table": "CashFlow", "attempts": 1}}}
        self.assertEqual(E._financial_selection(
            ["600001.SH", "600000.SH"], good, 1,
            tolerate=True, retry_pending=True), ["600000.SH"])
        bad = {"cursor": {"financial": "600001.SH"},
               "financial_pending": {"600000.SH": {
                   "table": "BadTable", "attempts": 1}}}
        with self.assertRaisesRegex(ValueError, "Invalid pending"):
            E._financial_selection(
                ["600001.SH", "600000.SH"], bad, 1,
                tolerate=True, retry_pending=True)
        with self.assertRaisesRegex(ValueError, "missing from universe"):
            E._financial_selection(
                ["600001.SH"], good, 1, tolerate=True,
                retry_pending=True)

    def test_sectors_section_runs_without_financial_and_etf_download(self):
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            xt = FakeXt()
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                result = E.run(root, xt=xt, apply=True,
                               section="sectors", today=date(2026,11,15),
                               workspace=Path(tmp) / "private",
                               progress=lambda _: None)
            self.assertTrue(result["sections"]["sectors"]["memberships"] > 0)
            self.assertNotIn("financial", result["sections"])
            self.assertNotIn("etf_catalog", result["sections"])
            self.assertEqual(xt.download_calls, [("sectors",)])

    def test_only_index_section_does_not_download_financial_or_etf_info(self):
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            xt = FakeXt()
            with patch.object(E.LIVE, "exclusive_writer",
                              return_value=contextlib.nullcontext()):
                result = E.run(root, xt=xt, apply=True, section="index",
                               today=date(2026,11,15),
                               since=date(2026,1,1),
                               stock_limit=1, asset_limit=1,
                               workspace=Path(tmp) / "private",
                               progress=lambda _: None)
            self.assertEqual(result["sections"]["index"]["symbols_processed"], 1)
            self.assertNotIn("financial", result["sections"])
            self.assertNotIn("etf_catalog", result["sections"])
            self.assertFalse(any(call[0] == "financial" for call in xt.download_calls))
            self.assertTrue(list((root / "AllCycleAStockData" / "qmt_extra" /
                                  "index" / "day").rglob("*.parquet")))

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
            # Inspect files INSIDE each generator, not its truthy iterator.
            # A generator exists even when the purchased period is empty.
            unexpected = {
                period: [str(path.relative_to(base))
                         for path in (base / period).rglob("*.parquet")]
                for period in L.PERIODS
            }
            self.assertEqual(
                {period: paths for period, paths in unexpected.items() if paths},
                {}, "QMT extras leaked into purchased 8-cycle directories")
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
