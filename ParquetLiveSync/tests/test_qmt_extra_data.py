"""Offline QMT extra-data tests; never contact live QMT or Windows scheduler."""
from __future__ import annotations

from datetime import date, datetime
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
