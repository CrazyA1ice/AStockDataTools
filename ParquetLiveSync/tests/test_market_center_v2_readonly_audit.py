"""V2-B synthetic, private-directory-only, read-only Parquet audit tests."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import inspect
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

import market_center_v2_readonly_audit as A
import market_center_v2_audit_cli as CLI

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    pa = pq = None

CN = timezone(timedelta(hours=8))


def stamp(day, hour=9, minute=31):
    return int(datetime(*day, hour, minute, tzinfo=CN).timestamp() * 1000)


def source(root, *, period="day", year=2026, month=11,
           symbols=("SZ000001", "SH600519"), times=None, values=None,
           yearly=False, write_stats=True, row_group_size=1):
    folder = root / "AllCycleAStockData"
    for p in A.PERIODS:
        (folder / p).mkdir(parents=True, exist_ok=True)
    times = times or (stamp((year, month, 17)),) * len(symbols)
    fields = {"ts": pa.array(times, type=pa.int64()),
              "symbol": pa.array(symbols, type=pa.string())}
    for name in A.REQUIRED[2:]:
        entries = (values or {}).get(name, [10.0] * len(symbols))
        fields[name] = pa.array(entries, type=pa.float64())
    file = folder / period / (
        f"{year}.parquet" if yearly else f"{year}-{month:02d}.parquet")
    pq.write_table(pa.table(fields), file, write_statistics=write_stats,
                   row_group_size=row_group_size)
    return folder, file


@unittest.skipIf(pa is None, "PyArrow needed for synthetic Parquet audit")
class SyntheticReadOnlySurvey(unittest.TestCase):
    def query(self, root, *, period="day", start="2026-11-17",
              end="2026-11-17", symbols=("000001.SZ",)):
        return A.survey(root=root, start=start, end=end, symbols=list(symbols),
                        periods=[period], explicit_readonly=True)

    def test_real_rows_observed_without_claiming_a_certified_missing_day(self):
        with TemporaryDirectory() as temp:
            market, path = source(Path(temp))
            before = path.read_bytes()
            result = self.query(market)
            self.assertEqual(result["status"],
                "V2B_BOUNDED_READONLY_OBSERVATION_NOT_CERTIFIED")
            self.assertEqual(result["observations"][0]["rows"], 1)
            self.assertEqual(result["observations"][0]["status"],
                             "ROWS_OBSERVED_UNCERTIFIED")
            self.assertFalse(result["allowed_market_write"])
            self.assertFalse(result["exchange_trading_calendar_verified"])
            self.assertFalse(result["physical_snapshot_immutability_certified"])
            self.assertEqual(result["qmt_calls"], 0)
            self.assertEqual(path.read_bytes(), before)

    def test_no_rows_not_proof_missing_or_expected_trade(self):
        with TemporaryDirectory() as temp:
            market, _ = source(Path(temp))
            result = self.query(market, symbols=("300750.SZ",))
            self.assertEqual(result["observations"][0]["rows"], 0)
            self.assertEqual(result["observations"][0]["status"], "NO_ROWS_OBSERVED")
            self.assertTrue(result["no_rows_does_not_certify_missing_trading_day"])

    def test_missing_month_shard_is_reported_not_created(self):
        with TemporaryDirectory() as temp:
            market = Path(temp) / "AllCycleAStockData"
            for p in A.PERIODS:
                (market / p).mkdir(parents=True)
            result = self.query(market)
            self.assertEqual(len(result["missing_partitions"]), 1)
            self.assertEqual(result["observations"][0]["status"], "NO_ROWS_OBSERVED")
            self.assertFalse((market / "day" / "2026-11.parquet").exists())

    def test_duplicates_are_explicit_anomalies(self):
        with TemporaryDirectory() as temp:
            market, _ = source(Path(temp), symbols=("SZ000001", "000001.SZ"))
            result = self.query(market)
            self.assertEqual(result["observations"][0]["rows"], 2)
            self.assertEqual(result["observations"][0]["status"], "ANOMALY_OBSERVED")
            self.assertEqual(result["observations"][0]["anomalies"]
                             ["DUPLICATE_SYMBOL_TIMESTAMP"], 1)

    def test_ohlc_invalid_is_reported_not_repaired(self):
        with TemporaryDirectory() as temp:
            market, _ = source(Path(temp), symbols=("SZ000001",),
                               values={"open": [20.0], "high": [10.0]})
            result = self.query(market)
            self.assertEqual(result["observations"][0]["anomalies"]["OHLC_INVALID"], 1)

    def test_one_minute_count_is_candidate_not_full_grid_certification(self):
        with TemporaryDirectory() as temp:
            market, _ = source(Path(temp), period="1min", symbols=("SZ000001",))
            result = self.query(market, period="1min")
            self.assertEqual(result["observations"][0]["status"],
                             "ROWS_OBSERVED_UNCERTIFIED")
            self.assertEqual(
                result["observations"][0]["standard_bar_count_difference_candidate"], 239)
            self.assertNotIn("MINUTE_BAR_COUNT_DIFFERS_FROM_STANDARD_GRID",
                             result["observations"][0]["anomalies"])
            self.assertFalse(result["source_crosscheck_completed"])
            self.assertFalse(result["minute_grid_observations"][0]
                             ["minute_label_complete_certified"])

    def test_annual_file_read_once_for_multiple_requested_months(self):
        with TemporaryDirectory() as temp:
            market, _ = source(Path(temp), period="day", yearly=True,
                               symbols=("SZ000001",))
            result = self.query(market, start="2026-10-28", end="2026-11-19")
            self.assertEqual(result["row_group_budget"]["groups_preflight"], 1)
            self.assertEqual(len(result["source_partitions"]), 1)
            day = next(x for x in result["observations"]
                       if x["timestamp_label_day"] == "2026-11-17")
            self.assertEqual(day["rows"], 1)

    def test_colliding_annual_and_monthly_files_blocked(self):
        with TemporaryDirectory() as temp:
            market, _ = source(Path(temp))
            source(Path(temp), yearly=True)
            with self.assertRaisesRegex(A.AuditBlocked, "partition_collision"):
                self.query(market)

    def test_cannot_decompress_huge_group(self):
        with TemporaryDirectory() as temp:
            market, _ = source(Path(temp), row_group_size=2)
            with patch.object(A, "MAX_GROUP_ROWS", 1):
                with self.assertRaisesRegex(A.AuditBlocked, "single_row_group_budget"):
                    self.query(market)

    def test_missing_statistics_still_scans_bounded_subset(self):
        with TemporaryDirectory() as temp:
            market, _ = source(Path(temp), write_stats=False)
            result = self.query(market)
            self.assertEqual(result["observations"][0]["rows"], 1)

    def test_future_or_unbounded_dates_blocked(self):
        with TemporaryDirectory() as temp:
            market, _ = source(Path(temp))
            for start, end in (
                ("2026-11-19", "2026-11-20"),
                ("2026-10-01", "2026-11-19"),
                ("2026-11-18", "2026-11-17"),
                ("2026-11-31", "2026-11-31"),
            ):
                with self.subTest(start=start, end=end):
                    with self.assertRaises(A.AuditBlocked):
                        self.query(market, start=start, end=end)

    def test_november_twentieth_explicit_committed_asof_is_physical_read_only(self):
        with TemporaryDirectory() as temp:
            market, path = source(
                Path(temp), symbols=("SZ000001",),
                times=(stamp((2026, 11, 20)),))
            original = path.read_bytes()
            with self.assertRaises(A.AuditBlocked):
                self.query(market, start="2026-11-20", end="2026-11-20")
            result = A.survey(
                root=market, start="2026-11-20", end="2026-11-20",
                symbols=["000001.SZ"], periods=["day"],
                explicit_readonly=True, accepted_asof="2026-11-20")
            self.assertEqual(result["observations"][0]["rows"], 1)
            self.assertFalse(result["allowed_market_write"])
            self.assertFalse(result["exchange_trading_calendar_verified"])
            self.assertTrue(result["no_rows_does_not_certify_missing_trading_day"])
            self.assertEqual(result["qmt_calls"], 0)
            self.assertEqual(path.read_bytes(), original)

    def test_stock_scope_and_permission_fail_closed(self):
        with TemporaryDirectory() as temp:
            market, _ = source(Path(temp))
            with self.assertRaisesRegex(A.AuditBlocked, "optin"):
                A.survey(root=market, start="2026-11-17",
                         end="2026-11-17", symbols=["000001.SZ"], periods=["day"])
            with self.assertRaisesRegex(A.AuditBlocked, "symbol"):
                self.query(market, symbols=("000001",))
            with self.assertRaisesRegex(A.AuditBlocked, "20_stocks"):
                self.query(market, symbols=tuple(
                    f"{i:06d}.SZ" for i in range(21)))

    def test_automatic_2005_reserved_window_has_priority(self):
        for h, m, busy in ((19, 54, False), (19, 55, True),
                           (20, 4, True), (20, 19, True), (20, 20, False)):
            with self.subTest(hour=h, minute=m):
                now = datetime(2026, 11, 20, h, m, tzinfo=CN)
                self.assertEqual(CLI._scheduled_window_reserved(now), busy)

    def test_cli_optin_denied_before_mutex_or_market(self):
        with patch.object(CLI, "shared_market_read_guard") as guard:
            with self.assertRaisesRegex(A.AuditBlocked, "optin"):
                CLI.audited_query(root="fake", start="2026-11-17",
                                  end="2026-11-17", symbols=["000001.SZ"],
                                  periods=["day"])
            guard.assert_not_called()

    def test_mutex_conflict_blocks_physical_audit(self):
        @contextmanager
        def collision():
            raise A.AuditBlocked("market_2005_task_or_manual_writer_is_running")
            yield
        with patch.object(CLI, "shared_market_read_guard", collision):
            with self.assertRaisesRegex(A.AuditBlocked, "running"):
                CLI.audited_query(
                    root="fake", start="2026-11-17", end="2026-11-17",
                    symbols=["000001.SZ"], periods=["day"], explicit_readonly=True)

    def test_cli_prints_noncertifying_report_only(self):
        with TemporaryDirectory() as temp:
            market, _ = source(Path(temp))
            buf = io.StringIO()
            @contextmanager
            def mock_guard():
                # Offline suite must never inspect or hold the *real*
                # production named mutex on user's Windows machine.
                yield
            # Synthetic tests never acquire the real production mutex and
            # never inherit local 19:55–20:20 scheduler restrictions.
            with patch.object(CLI, "shared_market_read_guard", mock_guard):
                with patch.object(CLI, "_read_budget_seconds", return_value=45.0):
                    with redirect_stdout(buf):
                        status = CLI.main(["--market-root", str(market),
                            "--start", "2026-11-17", "--end", "2026-11-17",
                            "--symbols", "000001.SZ", "--period", "day",
                            "--explicit-readonly"])
            self.assertEqual(status, 0)
            result = json.loads(buf.getvalue())
            self.assertFalse(result["allowed_market_write"])

    def test_auditor_does_not_look_up_qmt(self):
        text = inspect.getsource(A)
        for forbidden in ("xtquant", "subprocess.Popen", "write_table", "download_history"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
