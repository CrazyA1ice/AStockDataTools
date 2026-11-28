"""Synthetic regression for one-command daily updater; temporary files only."""
from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import market_month_storage as S
import market_source_adapters as X
import update_market as U
import local_layout as L


def stock_day(day="2026-11-13", code="600000.SH"):
    minute_grid = sorted(U.P.GRID)
    rows = []
    for i, (hour, minute) in enumerate(minute_grid):
        rows.append({
            "datetime_cn": datetime.fromisoformat(
                day + "T" + f"{hour:02}:{minute:02}:00").replace(
                    tzinfo=L.UTC8).isoformat(),
            "symbol": code,
            "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0,
            "volume": 0.0 if i == 0 else 2.0,
            "amount": 0.0 if i == 0 else 200.0})
    return rows


def canonical(rows, style="SH600000"):
    return pa.Table.from_pylist([{"symbol": style, **x}
                                 for x in rows], schema=S.SCHEMA)


def fixture(root):
    base = Path(root) / "AllCycleAStockData"
    for period in L.PERIODS:
        (base / period).mkdir(parents=True, exist_ok=True)
    return base


class MarketUpdaterTests(unittest.TestCase):
    def test_provider_cross_fit_one_minute_clock_shift(self):
        q = [{"ts": 1000000 + 60000 * i, "open": 10., "high": 10.2,
              "low": 9.8, "close": 10., "volume": 2., "amount": 200.}
             for i in range(240)]
        external = [{**x, "ts": x["ts"] - 60000, "volume": 200.}
                    for x in q]
        result = X.compare_minutes(q, external)
        self.assertEqual(result["status"], "AGREE")
        self.assertEqual(result["offset_ms"], 60000)
        self.assertEqual(result["volume_ratio"]["status"], "STABLE")
        wrong = [{**x, "open": 15., "high": 15.2, "low": 14.8, "close": 15.}
                 for x in external]
        self.assertEqual(X.compare_minutes(q, wrong)["status"], "PRICE_DISAGREES")

    def test_qmt_241_to_240_and_independent_daily_reference(self):
        raw = stock_day()
        gate = {"providers": {"SH_OTHER": {
            "category": "SH_OTHER", "offset_ms": 0,
            "volume": {"factor": 100.}, "amount": {"factor": 1.}}}}
        day = date(2026, 11, 13)
        official = {"open": 10., "high": 10.2, "low": 9.8,
                    "close": 10., "volume": 48000., "amount": 48000.}
        candidate = U.normal_qmt_day(raw, "600000.SH", day, official, gate)
        self.assertEqual(candidate.num_rows, 241)
        self.assertEqual(S._daily_group_rows(candidate), ["2026-11-13"])
        self.assertEqual(candidate["volume"][0].as_py(), 0.0)
        self.assertEqual(candidate["volume"][1].as_py(), 200.0)
        self.assertEqual(L.market_ts_day(candidate["ts"][0].as_py()), day)

    def test_purchased_vendor_minute_clock_offset_is_respected(self):
        from datetime import date as D
        day = D(2026, 11, 13)
        native = stock_day()
        offset = 60000
        cfg = {"providers": {"SH_OTHER": {
            "category": "SH_OTHER", "offset_ms": offset,
            "volume": {"factor": 100.}, "amount": {"factor": 1.}}}}
        official = {"open": 10., "high": 10.2, "low": 9.8,
                    "close": 10., "volume": 48000., "amount": 48000.}
        with self.assertRaisesRegex(ValueError, "PAID_241_NATIVE_TIMESTAMP_OFFSET_NOT_PROVEN"):
            U.normal_qmt_day(native, "600000.SH", day, official, cfg)
        # The old 240 conversion is still available for explicit TDX
        # comparisons, but it must not enter the purchased 241 writer.
        native_first = U.P.stamp_ms(native[1]["datetime_cn"])
        original = canonical([{
            "ts": U.P.stamp_ms(r["datetime_cn"]) + offset,
            **{k: r[k] for k in U.FIELDS}} for r in native])
        converted, removed = S.adapt_241_private(original, offset, "2026-11")
        self.assertEqual(converted.num_rows, 240)
        self.assertEqual(removed, 1)

    def test_unpaired_0930_and_official_price_mismatch_fail(self):
        raw = stock_day()
        gate = {"providers": {"SH_OTHER": {
            "category": "SH_OTHER", "offset_ms": 0,
            "volume": {"factor": 100.}, "amount": {"factor": 1.}}}}
        ref = {"open": 10., "high": 10.2, "low": 9.8,
               "close": 10., "volume": 48000., "amount": 48000.}
        # Traded 09:30 is valid in paid 241. The deliberately corrupt
        # positive-volume/zero-amount pair must still be rejected.
        raw[0]["volume"] = 5.
        with self.assertRaisesRegex(ValueError, "PAID_241_NATIVE_UNPAIRED_VOLUME_AMOUNT"):
            U.normal_qmt_day(raw, "600000.SH", date(2026, 11, 13), ref, gate)
        raw[0]["volume"] = 0.
        ref["open"] = 12.
        with self.assertRaisesRegex(ValueError, "OHLC"):
            U.normal_qmt_day(raw, "600000.SH", date(2026, 11, 13), ref, gate)

    def test_qmt_private_241_zero_placeholder_filter(self):
        raw = stock_day("2026-10-14")
        rows = [{"ts": U.P.stamp_ms(r["datetime_cn"]), "symbol": "SH600000",
                 **{k: r[k] for k in U.FIELDS}} for r in raw]
        t = canonical(rows)
        output, removed = S.adapt_241_private(t, 0, "2026-10")
        self.assertEqual(removed, 1)
        self.assertEqual(output.num_rows, 240)
        self.assertEqual(output["ts"][0].as_py(), rows[1]["ts"])
        rows[0]["amount"] = 1.
        with self.assertRaisesRegex(ValueError, "unpaired"):
            S.adapt_241_private(canonical(rows), 0, "2026-10")

    def test_real_0930_auction_is_folded_without_losing_any_ohlcva(self):
        source = stock_day("2026-10-14")
        source[0].update({"open": 9.95, "high": 10.25, "low": 9.7,
                          "close": 10.05, "volume": 4., "amount": 400.})
        converted = canonical([{
            "ts": U.P.stamp_ms(bar["datetime_cn"]),
            **{key: bar[key] for key in U.FIELDS}
        } for bar in source])
        counters = {}
        folded, removed = S.adapt_241_private(
            converted, 0, "2026-10", stats=counters)
        self.assertEqual(folded.num_rows, 240)
        self.assertEqual(removed, 1)
        self.assertEqual(counters["REAL_AUCTION_FOLDED_TO_0931"], 1)
        first = folded.slice(0, 1).to_pylist()[0]
        self.assertEqual(first["open"], 9.95)
        self.assertEqual(first["high"], 10.25)
        self.assertEqual(first["low"], 9.7)
        self.assertEqual(first["close"], 10.)
        self.assertEqual(first["volume"], 6.)
        self.assertEqual(first["amount"], 600.)
        self.assertAlmostEqual(sum(row["volume"] for row in folded.to_pylist()),
                               sum(row["volume"] for row in converted.to_pylist()))
        self.assertAlmostEqual(sum(row["amount"] for row in folded.to_pylist()),
                               sum(row["amount"] for row in converted.to_pylist()))
        rawohlc = (source[0]["open"], max(x["high"] for x in source),
                   min(x["low"] for x in source), source[-1]["close"])
        values = folded.to_pylist()
        newohlc = (values[0]["open"], max(x["high"] for x in values),
                   min(x["low"] for x in values), values[-1]["close"])
        self.assertEqual(rawohlc, newohlc)

    def test_real_0930_auction_daily_official_verification_and_clock(self):
        source = stock_day("2026-11-13")
        source[0].update({"open": 9.95, "high": 10.25, "low": 9.7,
                          "close": 10.05, "volume": 4., "amount": 400.})
        reference = {"open": 9.95, "high": 10.25, "low": 9.7,
                     "close": 10., "volume": 48400., "amount": 48400.}
        factor = {"providers": {"SH_OTHER": {
            "category": "SH_OTHER", "offset_ms": 0,
            "volume": {"factor": 100.}, "amount": {"factor": 1.}}}}
        accepted = U.normal_qmt_day(source, "600000.SH",
                                    date(2026, 11, 13), reference, factor)
        self.assertEqual(accepted.num_rows, 241)
        self.assertEqual(accepted["volume"][0].as_py(), 400.)
        self.assertEqual(accepted["amount"][0].as_py(), 400.)
        self.assertEqual(accepted["volume"][1].as_py(), 200.)
        self.assertEqual(accepted["amount"][1].as_py(), 200.)
        self.assertEqual(accepted["ts"][0].as_py(),
                         U.P.stamp_ms(source[0]["datetime_cn"]))
        reference["volume"] = 40000.
        with self.assertRaisesRegex(ValueError, "official DAY volume"):
            U.normal_qmt_day(source, "600000.SH",
                             date(2026, 11, 13), reference, factor)

    def test_zero_0930_remains_placeholder_and_two_days_stay_distinct(self):
        first = stock_day("2026-10-14")
        second = stock_day("2026-10-15")
        second[0].update({"open": 9.95, "high": 10.25, "low": 9.7,
                          "close": 10.05, "volume": 4., "amount": 400.})
        combined = canonical([{
            "ts": U.P.stamp_ms(bar["datetime_cn"]),
            **{key: bar[key] for key in U.FIELDS}
        } for bar in first+second])
        counters = {}
        output, removed = S.adapt_241_private(combined, 0, "2026-10",
                                              stats=counters)
        self.assertEqual(removed, 2)
        self.assertEqual(output.num_rows, 480)
        self.assertEqual(S._daily_group_rows(output),
                         ["2026-10-14", "2026-10-15"])
        self.assertEqual(counters, {"ZERO_PLACEHOLDER": 1,
                                    "REAL_AUCTION_FOLDED_TO_0931": 1})

    def test_auction_fold_does_not_hide_unpaired_regular_minute(self):
        raw = stock_day("2026-10-14")
        raw[0].update({"volume": 4., "amount": 400.})
        raw[1]["amount"] = 0.
        batch = canonical([{
            "ts": U.P.stamp_ms(bar["datetime_cn"]),
            **{key: bar[key] for key in U.FIELDS}
        } for bar in raw])
        with self.assertRaisesRegex(ValueError, "native_label=09:31"):
            S.adapt_241_private(batch, 0, "2026-10")

    def test_canonical_month_append_idempotence_and_old_vendor_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = fixture(tmp)
            work = Path(tmp) / "work"
            september = base / "1min" / "2026-09.parquet"
            prior = canonical([{"ts": U.P.stamp_ms(
                datetime(2026, 9, 30, 9, 31, tzinfo=L.UTC8).isoformat()),
                **{k: 10.0 for k in U.FIELDS}}],
                style="600000.SH")
            pq.write_table(prior, september)
            before = L.hash_file(september)
            day = "2026-11-13"
            one = canonical([{"ts": U.P.stamp_ms(
                datetime(2026, 11, 13, 9, 31, tzinfo=L.UTC8).isoformat()),
                **{k: 10.0 for k in U.FIELDS}}])
            a = S.install_month(tmp, "2026-11", iter([one]),
                                source_id="TEST:one", days=[day],
                                workspace=work, progress=lambda _: None)
            self.assertEqual(a["status"], "COMMITTED")
            target = base / "1min" / "2026-11.parquet"
            saved = pq.read_table(target)
            self.assertEqual(saved["symbol"][0].as_py(), "600000.SH")
            b = S.install_month(tmp, "2026-11", iter([one]),
                                source_id="TEST:one", days=[day],
                                workspace=work, progress=lambda _: None)
            self.assertEqual(b["status"], "ALREADY_INSTALLED")
            self.assertEqual(L.hash_file(september), before)
            later = canonical([{"ts": U.P.stamp_ms(
                datetime(2026, 11, 16, 9, 31, tzinfo=L.UTC8).isoformat()),
                **{k: 10.0 for k in U.FIELDS}}])
            c = S.install_month(tmp, "2026-11", iter([later]),
                                source_id="TEST:two", days=["2026-11-16"],
                                workspace=work, progress=lambda _: None)
            self.assertEqual(c["rows"], 2)
            self.assertEqual(len(pq.read_table(target)["symbol"]), 2)
            with self.assertRaisesRegex(ValueError, "Overlapping trading date"):
                S.install_month(tmp, "2026-11", iter([one]),
                                source_id="TEST:three", days=[day],
                                workspace=work, progress=lambda _: None)
            self.assertTrue((work / "backups").is_dir())

    def test_month_external_edit_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = fixture(tmp)
            work = Path(tmp) / "work"
            target = base / "1min" / "2026-11.parquet"
            one = canonical([{"ts": U.P.stamp_ms(
                datetime(2026, 11, 13, 9, 31, tzinfo=L.UTC8).isoformat()),
                **{k: 10.0 for k in U.FIELDS}}])
            S.install_month(tmp, "2026-11", iter([one]), source_id="T1",
                            days=["2026-11-13"], workspace=work, progress=lambda _: None)
            with target.open("ab") as f:
                f.write(b"external-write")
            with self.assertRaisesRegex(ValueError, "changed since"):
                S.install_month(tmp, "2026-11", iter([one]), source_id="T2",
                                days=["2026-11-16"], workspace=work,
                                progress=lambda _: None)

    def test_sources_config_declares_independent_and_correlated_providers(self):
        config = U.config_file()
        self.assertEqual(config["primary"], "qmt")
        checks = config["minute_cross_checks"]
        self.assertNotIn("pytdx", checks)
        self.assertNotIn("pytdx", X.ADAPTERS)
        self.assertTrue(checks["tencent"]["enabled"])
        self.assertTrue(checks["eltdx"]["enabled"])
        self.assertFalse(checks["akshare"]["enabled"])
        self.assertNotIn("tencent", X.TDX_FAMILY)
        self.assertIn("eltdx", X.TDX_FAMILY)

    def test_legacy_local_pytdx_config_migrates_without_file_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = U.config_file()
            cfg["minute_cross_checks"].pop("tencent")
            cfg["minute_cross_checks"]["pytdx"] = {"enabled": True}
            path = Path(tmp) / "sources.local.json"
            content = json.dumps(cfg, ensure_ascii=False)
            path.write_text(content, encoding="utf-8")
            loaded = U.config_file(path)
            self.assertNotIn("pytdx", loaded["minute_cross_checks"])
            self.assertTrue(loaded["minute_cross_checks"]["tencent"]["enabled"])
            self.assertTrue(loaded["minute_cross_checks"]["eltdx"]["enabled"])
            self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_bootstrap_short_circuits_historical_5403_receipts_daily(self):
        fake = {"periods": {"1min": {
            m: {"sources": ["BOOTSTRAP:approved:" + m],
                "minute_grid_contract": S.PAID_241_CONTRACT}
            for m in U.B.MONTHS}},
            "qmt_calibration_sha256": "a" * 64,
            "original_day_bootstrap_attempted": True}
        with (patch.object(U.S, "recover_intent", return_value=fake),
              patch.object(U.B, "resolve",
                           side_effect=AssertionError("never reread old receipts"))):
            result = U.bootstrap("D:/stock", apply=True, progress=lambda _: None)
            self.assertEqual(result[0]["status"], "ALREADY_BOOTSTRAPPED")

    def test_new_target_rejects_untracked_existing_original(self):
        with tempfile.TemporaryDirectory() as temp:
            base = fixture(temp)
            target = base / "1min" / "2026-11.parquet"
            target.write_bytes(b"unknown-market-data")
            table = canonical([{"ts": U.P.stamp_ms(
                datetime(2026, 11, 13, 9, 31, tzinfo=L.UTC8).isoformat()),
                **{k: 10.0 for k in U.FIELDS}}])
            with self.assertRaisesRegex(ValueError, "no updater ledger"):
                S.install_month(temp, "2026-11", iter([table]),
                                source_id="T1", days=["2026-11-13"],
                                workspace=Path(temp) / "work", progress=lambda _: None)
            self.assertEqual(target.read_bytes(), b"unknown-market-data")

    def test_tencent_m1_http_fallback_and_no_fabricated_amount(self):
        from unittest.mock import MagicMock
        from urllib.parse import parse_qs, urlparse
        day = date(2026, 11, 13)
        calls = []
        candle = ["202611130931", "10.0", "10.1", "10.2", "9.9", "300"]
        body = json.dumps({"code": 0,
            "data": {"sz000001": {"m1": [candle,
                ["202611120931", "9", "9", "9", "9", "100"]]}}}).encode("utf-8")
        def mock_urlopen(request, timeout=None):
            calls.append(request.full_url)
            url = urlparse(request.full_url)
            self.assertEqual(url.path.endswith("/appstock/app/kline/mkline"), True)
            self.assertEqual(parse_qs(url.query),
                             {"param": ["sz000001,m1,,320"]})
            self.assertEqual(request.get_header("Referer"),
                             "https://gu.qq.com/")
            self.assertEqual(timeout, 8)
            if len(calls) == 1:
                raise TimeoutError("temporary endpoint outage")
            response = MagicMock()
            response.__enter__.return_value.read.return_value = body
            return response
        with (patch.object(X, "urlopen", side_effect=mock_urlopen),
              patch.dict(X._TENCENT_HOST_DOWN_UNTIL, {}, clear=True),
              patch.object(X, "_TENCENT_LAST_GOOD", None)):
            got = X.tencent_1m("000001.SZ", day)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["open"], 10.)
        self.assertEqual(got[0]["close"], 10.1)
        self.assertEqual(got[0]["high"], 10.2)
        self.assertEqual(got[0]["low"], 9.9)
        self.assertEqual(got[0]["volume"], 300.)
        self.assertNotIn("amount", got[0])

    def test_tencent_stdlib_http_rejects_oversize_or_invalid_json(self):
        from unittest.mock import MagicMock
        def make_response(body):
            response = MagicMock()
            response.__enter__.return_value.read.return_value = body
            return response
        with patch.object(X, "urlopen",
                          return_value=make_response(b"x" * 2_000_001)):
            with self.assertRaisesRegex(ValueError, "RESPONSE_TOO_LARGE"):
                X._tencent_http_json(X.TENCENT_KLINE_HOSTS[0],
                                     {"param": "sh600000,m1,,320"}, 8)
        with patch.object(X, "urlopen",
                          return_value=make_response(b"not-a-json-document")):
            with self.assertRaises(ValueError):
                X._tencent_http_json(X.TENCENT_KLINE_HOSTS[0],
                                     {"param": "sh600000,m1,,320"}, 8)

    def test_tencent_m1_rejects_duplicate_bad_or_nonfinite_rows(self):
        day = date(2026, 11, 13)
        valid = ["202611130931", "10", "10.1", "10.2", "9.9", "100"]
        def payload(rows):
            return {"data": {"sh600000": {"m1": rows}}}
        self.assertEqual(len(X._tencent_parse_minute_payload(
            payload([valid]), "sh600000", day)), 1)
        for rows in ([valid, valid],
                     [["202611130931", "10", "10.1", "10.2", "nan", "100"]],
                     [["202611130931", "10", "10.1", "10.2", "9.9", True]],
                     [["202611130931", "12", "10.1", "10.2", "9.9", "100"]],
                     [["bad_date", "10", "10.1", "10.2", "9.9", "100"]]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                X._tencent_parse_minute_payload(
                    payload(rows), "sh600000", day)

    def test_tencent_outage_fast_skip_eltdx_untouched(self):
        stocks = ["SH600%03d" % i for i in range(8)]
        primary = {symbol: [{"ts": 1000 + i * 60000,
                             "open": 10., "high": 10., "low": 10.,
                             "close": 10., "volume": 1., "amount": 10.}
                            for i in range(100)] for symbol in stocks}
        counts = {"down": 0, "ok": 0}
        def down(symbol, day, options):
            counts["down"] += 1
            raise X.MinuteSourceUnavailable("TENCENT_M1_ALL_HTTP_GATEWAYS_UNAVAILABLE")
        def up(symbol, day, options):
            counts["ok"] += 1
            return list(primary[symbol])
        cfg = {"sample_stocks": 8,
               "tencent": {"enabled": True}, "eltdx": {"enabled": True}}
        with patch.dict(X.ADAPTERS, {"tencent": down, "eltdx": up}):
            result = X.sample_check(date(2026, 11, 13), primary, cfg,
                                    progress=lambda _: None)
        self.assertEqual(counts, {"down": 1, "ok": 8})
        self.assertEqual(result["results"]["tencent"]["status"], "UNAVAILABLE")
        self.assertEqual(result["results"]["tencent"]["attempted"], 1)
        self.assertEqual(result["results"]["tencent"]["skipped_after_outage"], 7)
        self.assertEqual(result["results"]["eltdx"]["status"], "AGREE")
        self.assertEqual(result["results"]["eltdx"]["agreed_stocks"], 8)
        self.assertEqual(result["results"]["tencent"]["evidence_family"],
                         "TENCENT_FINANCE")

    def test_readonly_recheck_sources_from_previously_staged_daily_file(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "market_update"
            day = date(2026, 11, 13)
            staged = workspace / "daily"
            staged.mkdir(parents=True)
            rows = []
            symbols = ["SH600000", "SZ000001", "SZ000002"]
            for symbol in symbols:
                for hour, minute in sorted(U.P.GRID):
                    ts = U.P.stamp_ms(
                        datetime(2026, 11, 13, hour, minute,
                                 tzinfo=L.UTC8).isoformat())
                    rows.append({"ts": ts, "symbol": symbol,
                                 "open": 10., "high": 10.,
                                 "low": 10., "close": 10.,
                                 "volume": 100., "amount": 1000.})
            f = staged / (day.isoformat() + ".parquet")
            pq.write_table(pa.Table.from_pylist(rows,
                                                 schema=U.P.PRIVATE_SCHEMA),
                           f, row_group_size=241)
            digest = L.hash_file(f)
            (staged / (day.isoformat() + ".json")).write_bytes(
                U.P.canonical({"format": U.FORMAT,
                               "date": day.isoformat(), "sha256": digest,
                               "rows": len(rows),
                               "minute_grid_contract": S.PAID_241_CONTRACT,
                               "stock_days_accepted": len(symbols)}))
            def faux_sample(d, stock_data, settings, progress=print):
                self.assertEqual(d, day)
                self.assertEqual(set(stock_data), set(symbols))
                self.assertTrue(all(len(v) == 241 for v in stock_data.values()))
                return {"sampled": len(stock_data), "results": {}}
            before = sorted(str(p) for p in Path(temp).rglob("*"))
            with patch.object(U.X, "sample_check", side_effect=faux_sample):
                report = U.recheck_sources(day, workspace=workspace,
                                           progress=lambda _: None)
            self.assertTrue(report["qmt_refetched"] is False)
            self.assertTrue(report["production_market_modified"] is False)
            self.assertEqual(report["qmt_sha256"], digest)
            self.assertEqual(before, sorted(str(p) for p in
                                           Path(temp).rglob("*")))
            self.assertEqual(L.hash_file(f), digest)

    def test_readonly_recheck_rejects_tampered_daily_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp) / "market_update"
            folder = work / "daily"
            folder.mkdir(parents=True)
            day = date(2026, 11, 13)
            (folder / "2026-11-13.parquet").write_bytes(b"changed")
            (folder / "2026-11-13.json").write_bytes(
                U.P.canonical({"format": U.FORMAT,
                               "date": "2026-11-13",
                               "sha256": "0"*64, "rows": 240,
                               "stock_days_accepted": 1}))
            with self.assertRaisesRegex(ValueError, "source SHA changed"):
                U.recheck_sources(day, workspace=work,
                                  progress=lambda _: None)

    def test_dry_run_requires_no_qmt_or_market_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(tmp)
            with (patch.object(U.B, "resolve", return_value={
                    "expected": {date(2026, 10, 14): {"600000.SH": {}}},
                    "original": 1, "recovered": 0, "opening": 0,
                    "gaps": [], "months": {}, "identity_sha256": "a" * 64}),
                  patch.object(U.S, "recover_intent",
                               return_value={"periods": {"1min": {}}})):
                with self.assertRaisesRegex(ValueError, "source count changed"):
                    U.bootstrap(tmp, apply=False, progress=lambda _: None)


if __name__ == "__main__":
    unittest.main()
