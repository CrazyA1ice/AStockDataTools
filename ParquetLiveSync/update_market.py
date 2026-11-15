#!/usr/bin/env python3
"""One-command QMT → canonical 1min Parquet daily updater.

First run: attach verified legacy Oct 1..13 + existing calibrated
Oct 14..Nov 12 private increments to real AllCycleAStockData/1min.
Subsequent runs: fetch only not-yet-committed trading days using official
TDX DAY + QMT 1m, sampled pytdx/eltdx/AKShare checks, and append atomically.
No full history replay and no independent monthly preflight handoffs.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date, datetime, timedelta
import itertools
import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

import live_sync as LIVE
import local_layout as L
import qmt_1m_pipeline as P
import qmt_1m_private_month_bridge as B
import market_month_storage as S
import market_source_adapters as X
from qmt_1m_probe import FIELDS, normalize_code

FORMAT = "one_command_qmt_market_update_v1"
BOOTSTRAP_START = date(2026, 10, 14)
BOOTSTRAP_END = date(2026, 11, 12)
BASELINE_OCT_DAYS = ["2026-10-08", "2026-10-09",
                     "2026-10-12", "2026-10-13"]
CONFIG_PATH = Path(__file__).resolve().parent / "market_sources.json"


def config_file(path=CONFIG_PATH):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if (raw.get("format") != FORMAT or raw.get("primary") != "qmt"
            or not isinstance(raw.get("minute_cross_checks"), dict)
            or not isinstance(raw.get("max_failure_fraction"), (int, float))
            or not 0 <= raw["max_failure_fraction"] <= .10):
        raise ValueError("Unknown market source config or unsafe primary policy")
    return raw


def bootstrap(root, *, apply=True, progress=print, stage=B.P.BASE / "20261014_20261112"):
    """Initialize canonical 2026-10/11 once; no rewriting existing asof baseline."""
    state = S.recover_intent(root)
    completed = all(
        any(str(src).startswith("BOOTSTRAP:") for src in
            state["periods"]["1min"].get(month, {}).get("sources", []))
        for month in B.MONTHS
    )
    if (completed and state.get("qmt_calibration_sha256")
            and state.get("original_day_bootstrap_attempted")):
        # The current November file can evolve daily. Ledger + transaction
        # checks protect each append; NEVER rescan 5403 historical receipts
        # when bootstrap is already committed.
        progress("MARKET_BOOTSTRAP_ALREADY_INSTALLED_SKIP_HISTORY")
        return [{"status": "ALREADY_BOOTSTRAPPED", "months": list(B.MONTHS)}]
    plan = B.resolve(root, stage, progress=progress)
    if (sum(len(codes) for codes in plan["expected"].values()) != 114749
            or plan["original"] + plan["recovered"] + plan["opening"] != 114739
            or len(plan["gaps"]) != 10):
        raise ValueError("Legacy October/November bootstrapping source count changed")
    expected_sha = {"2026-10": "ec6c8bb53f15ab885b122e0a15b43d39c41169ddfbf4cc4066561202c43753e0",
                    "2026-11": "d942d8036841fe6053ec49fbdf66d2229bcd07303b5a2de7f08aa5a0c509abc0"}
    for month, sha in expected_sha.items():
        f = Path(stage) / B.TARGET / (month + ".parquet")
        if f.is_symlink() or not f.is_file() or L.hash_file(f) != sha:
            raise ValueError("Real Windows SHA-verified private monthly source changed " + month)
        receipt = B._json(f.with_suffix(".receipt.json"))
        if (receipt.get("format") != B.FORMAT
                or receipt.get("status") != "PRIVATE_MONTH_ONLY"
                or receipt.get("identity_sha256") != plan["identity_sha256"]
                or receipt.get("month_coverage") != plan["months"][month]
                or receipt.get("rows") != plan["months"][month]["minute_rows_expected_from_accepted"]
                or receipt.get("market_modified") is not False
                or receipt.get("production_merge_authorized") is not False):
            raise ValueError("QMT private month source identity or row-count receipt changed")
        physical = pq.ParquetFile(f)
        try:
            if (physical.schema_arrow != P.PRIVATE_SCHEMA
                    or physical.metadata.num_rows != receipt["rows"]
                    or physical.num_row_groups != len(receipt["groups"])):
                raise ValueError("QMT private monthly footer does not match accepted receipt")
        finally:
            physical.close()
        # A single streamed read in S.private_oct_nov_batches independently
        # checks every row group's logical SHA. Avoid reading 27m rows twice.
    if apply and state.get("qmt_calibration_sha256") not in (
            None, plan["plan"]["calibration_sha256"]):
        raise ValueError("Existing updater calibration SHA differs from sealed bootstrap")
    results = []
    for month in B.MONTHS:
        dates = sorted(d.isoformat() for d in plan["expected"] if str(d).startswith(month))
        if month == "2026-10":
            dates = sorted(set(dates) | set(BASELINE_OCT_DAYS))
        source_id = "BOOTSTRAP:" + plan["identity_sha256"] + ":" + month
        old = state["periods"]["1min"].get(month)
        if old is not None and source_id in old["sources"]:
            results.append({"month": month, "status": "ALREADY_INSTALLED",
                            "rows": old["rows"], "sha256": old["sha256"]})
            continue
        progress("MARKET_BOOTSTRAP_READY=" + json.dumps(
            {"month": month, "trading_dates": dates,
             "qmt_source_stockdays": plan["months"][month]["stock_days_accepted"],
             "historical_original_included": month == "2026-10",
             "write": apply}, sort_keys=True))
        if not apply:
            results.append({"month": month, "status": "DRY_RUN", "trading_dates": dates})
            continue
        if month == "2026-10":
            streams = itertools.chain(
                S.legacy_october_batches(root),
                S.private_oct_nov_batches(month, stage=stage, plan=plan))
        else:
            streams = S.private_oct_nov_batches(month, stage=stage, plan=plan)
        result = S.install_month(root, month, streams, source_id=source_id,
                                 days=dates, state=state, progress=progress)
        results.append(result)
        state = S.state_for(root)
    if apply and state.get("qmt_calibration_sha256") is None:
        state["qmt_calibration_sha256"] = plan["plan"]["calibration_sha256"]
        S._save(S.STATE_FILE, state)
    if apply and not state.get("original_day_bootstrap_attempted"):
        # TDX DAY overlays already accepted during the old QMT discovery
        # phase are appended to the physical day months ONLY ONCE.
        # Legacy October DAY purchased-first prefix is handled by the
        # existing LIVE.materialize_day_in_original_layout() implementation.
        day_state = LIVE.read_state()
        payload = LIVE.baseline()
        completed_days = []
        unavailable = []
        for day in sorted(plan["expected"]):
            label = day.isoformat()
            if label in day_state.get("days", {}):
                LIVE.materialize_day_in_original_layout(
                    root, day, day_state, payload, progress)
                completed_days.append(label)
            else:
                unavailable.append(label)
        if unavailable:
            progress("MARKET_BOOTSTRAP_OFFICIAL_DAY_NOT_IN_ACCEPTED_OVERLAYS=" +
                     json.dumps(unavailable, ensure_ascii=False))
        state["original_day_bootstrap_attempted"] = True
        state["original_day_bootstrap_complete"] = not unavailable
        state["pending_original_day_dates"] = unavailable
        S._save(S.STATE_FILE, state)
        progress("MARKET_BOOTSTRAP_DAY_MATERIALIZED=" +
                 json.dumps({"accepted_overlay_days": len(completed_days),
                             "unavailable_overlay_dates": unavailable}, sort_keys=True))
    return results


def _reference_for_day(root, day):
    state = LIVE.read_state()
    entry = state.get("days", {}).get(day.isoformat())
    if not entry:
        return {}
    path = LIVE.checked_path(LIVE.WORK, entry["file"])
    if L.hash_file(path) != entry["sha256"]:
        raise ValueError("Official DAY accepted daily source SHA changed")
    t = pq.read_table(path, columns=list(L.COLS))
    L.validate_schema(t.schema)
    out = {}
    for bar in t.to_pylist():
        code = L.normal_symbol(bar["symbol"])
        if (code[:2] not in ("SH", "SZ") or len(code) != 8
                or code[2:].isdigit() is False):
            continue
        if code in out:
            raise ValueError("Official DAY duplicates same security")
        if float(bar["volume"]) <= 0 or float(bar["amount"]) <= 0:
            continue
        out[code] = bar
    return out


def normal_qmt_day(raw, code, day, expected, calibration):
    """Normalize one QMT stock/day while conserving genuine 09:30 auction.

    Keep the original native 241 labels in the QMT API; convert to the paid
    provider's 240 intervals using the SAME conservation logic as the
    historical bootstrap. Independently compare the final 240 traded OHLCVA
    against the official accepted DAY reference before admission.
    """
    if len(raw) not in (240, 241):
        raise ValueError("QMT day must contain 240/241 native 1minute bars")
    native = sorted(P.GRID)
    clocks = [datetime.fromisoformat(r["datetime_cn"]).astimezone(L.UTC8)
              for r in raw]
    observed = [(d.hour, d.minute) for d in clocks]
    if any(d.date() != day for d in clocks):
        raise ValueError("QMT source minute outside official requested date")
    if observed != (native if len(raw) == 241 else native[1:]):
        raise ValueError("QMT native minute grid differs from accepted 241/240 labels")
    gate = B._calibration(calibration, code)
    records = pa.Table.from_pylist([
        {"ts": P.stamp_ms(r["datetime_cn"]),
         "symbol": L.normal_symbol(code),
         **{k: float(r[k]) for k in FIELDS}}
        for r in raw
    ], schema=P.PRIVATE_SCHEMA)
    calibrated = B.calibrate_table(records, gate, day.strftime("%Y-%m"))
    if len(raw) == 241:
        approved, _ = S.adapt_241_private(
            calibrated, gate["offset_ms"], day.strftime("%Y-%m"))
    else:
        approved = S._canonical(calibrated)
    if approved.num_rows != 240:
        raise ValueError("QMT calibrated day is not 240 compatible intervals")
    L.checked_records(approved, target_year=day.year, target_month=day.month)
    target_grid = sorted(P.GRID - {(9, 30)})
    clocks = [datetime.fromtimestamp((int(ts)-gate["offset_ms"])/1000, L.UTC8)
              for ts in approved["ts"].to_pylist()]
    if [(d.hour, d.minute) for d in clocks] != target_grid:
        raise ValueError("QMT converted 240-grid differs from purchased minute convention")
    rows = approved.to_pylist()
    for bar in rows:
        v, a = float(bar["volume"]), float(bar["amount"])
        if not (math.isfinite(v) and math.isfinite(a)
                and v >= 0 and a >= 0 and (v > 0) == (a > 0)):
            raise ValueError("QMT traded minute invalid volume/amount pair")
    traded = [r for r in rows if r["volume"] > 0]
    if not traded:
        raise ValueError("QMT day contains no genuine trading minutes")
    ohlc = {"open": traded[0]["open"],
            "high": max(r["high"] for r in traded),
            "low": min(r["low"] for r in traded),
            "close": traded[-1]["close"]}
    for name, value in ohlc.items():
        if not math.isclose(float(value), float(expected[name]),
                            rel_tol=.006, abs_tol=.04):
            raise ValueError("Independent official DAY OHLC discrepancy: " + name)
    for name in ("volume", "amount"):
        total = sum(float(r[name]) for r in rows)
        reference = float(expected[name])
        if not math.isclose(total, reference, rel_tol=.03,
                            abs_tol=200 if name == "volume" else 1000):
            raise ValueError("Independent official DAY " + name + " discrepancy")
    return approved


def fetch_one(xtdata, code, day):
    """Only one missing day per code, not a repeated 90-day/history scan."""
    return P.fetch_qmt(xtdata, code, day, day)


def stage_day(root, day, reference, calib, sources_config, *,
              reader=None, progress=print,
              workspace=S.STATE_DIR):
    """QMT acquisition with per-stock quarantine; one daily private file."""
    if reader is None:
        from xtquant import xtdata as real_xtdata
        xtdata = real_xtdata
    else:
        xtdata = reader
    folder = Path(workspace) / "daily"
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / (day.isoformat() + ".parquet")
    receipt = folder / (day.isoformat() + ".json")
    if output.is_symlink() or receipt.is_symlink():
        raise ValueError("Linked private daily candidate")
    if output.exists() or receipt.exists():
        if not output.is_file() or not receipt.is_file():
            raise ValueError("Incomplete daily candidate pair")
        meta = S._json(receipt)
        if (meta.get("format") != FORMAT or meta.get("date") != day.isoformat()
                or meta.get("sha256") != L.hash_file(output)):
            raise ValueError("Saved daily candidate SHA changed")
        return output, meta
    scratch = folder / (day.isoformat() + ".parquet.part")
    if scratch.exists() or scratch.is_symlink():
        raise ValueError("Interrupted daily stage; inspect temporary source first")
    codes = sorted(reference)
    bad = {}
    valid = 0
    selected_samples = {}
    import random
    target_count = int(sources_config.get("sample_stocks", 8))
    sample = set(random.Random(day.isoformat()).sample(
        codes, min(target_count, len(codes)))) if codes else set()
    try:
        with pq.ParquetWriter(scratch, P.PRIVATE_SCHEMA, compression="zstd") as writer:
            for i, symbol in enumerate(codes, 1):
                code = normalize_code(symbol)
                try:
                    raw = fetch_one(xtdata, code, day)
                    ready = normal_qmt_day(raw, code, day, reference[symbol], calib)
                    writer.write_table(ready, row_group_size=240)
                    valid += 1
                    if symbol in sample:
                        selected_samples[symbol] = ready.to_pylist()
                except (ValueError, RuntimeError, TypeError, KeyError, OSError) as exc:
                    bad[symbol] = type(exc).__name__ + ": " + str(exc)[:160]
                if i % 250 == 0:
                    progress("MARKET_DAILY_QMT_PROGRESS=" + str(day) + " " +
                             str(i) + "/" + str(len(codes)) +
                             " valid=" + str(valid))
        if (valid == 0 or valid / len(codes) <
                (1. - sources_config.get("max_failure_fraction", .02))):
            raise ValueError("Too many missing/incompatible QMT stocks: " +
                             str(len(bad)) + "/" + str(len(codes)))
        check = X.sample_check(day, selected_samples,
                               sources_config["minute_cross_checks"], progress=progress)
        # Mismatched independent 1m samples block blind daily publication.
        disagreement = [(name, item) for name, entry in check["results"].items()
                        for item in entry["disagreements"]
                        if item.get("status") == "PRICE_DISAGREES"]
        if disagreement:
            raise ValueError("Cross-source sampled minute OHLC mismatch: " +
                             json.dumps(disagreement[:4], ensure_ascii=False))
        tmp = pq.ParquetFile(scratch)
        try:
            if (tmp.schema_arrow != P.PRIVATE_SCHEMA
                    or tmp.metadata.num_rows != valid * 240):
                raise ValueError("Daily QMT staged 240-grid row count invalid")
        finally:
            tmp.close()
        import os
        os.replace(scratch, output)
        doc = {"format": FORMAT, "date": day.isoformat(),
               "sha256": L.hash_file(output), "rows": valid * 240,
               "stock_days_accepted": valid, "expected_stock_days": len(codes),
               "quarantined": bad, "source_family": "QMT_AND_TDX_OFFICIAL_DAY",
               "sampled_minute_sources": check, "production_merge_authorized": False}
        S._save(receipt, doc)
        progress("MARKET_DAILY_STAGED=" + json.dumps(
            {"date": doc["date"], "accepted": valid, "quarantine": len(bad),
             "rows": doc["rows"], "sha256": doc["sha256"]}, sort_keys=True))
        return output, doc
    finally:
        if scratch.exists() and not scratch.is_symlink():
            scratch.unlink()


def last_eligible_day():
    """At/after 20:00 Shanghai time; otherwise previous calendar day."""
    now = datetime.now(L.UTC8)
    cutoff = now.date() if now.hour >= 20 else now.date() - timedelta(days=1)
    while cutoff.weekday() >= 5:
        cutoff -= timedelta(days=1)
    return cutoff


def update(root, *, mode="auto", apply=True, requested_date=None,
           config=CONFIG_PATH, max_days=30, progress=print):
    cfg = config_file(config)
    if mode not in ("auto", "bootstrap", "daily"):
        raise ValueError("Invalid updater mode")
    if not 1 <= max_days <= 30:
        raise ValueError("Daily catch-up must be <=30 calendar days")
    with LIVE.exclusive_writer():
        state = S.recover_intent(root)
        logs = []
        if mode in ("auto", "bootstrap"):
            logs.extend(bootstrap(root, apply=apply, progress=progress))
            state = S.state_for(root)
        if mode == "bootstrap":
            return logs
        if not state["periods"]["1min"]:
            if not apply and mode == "auto":
                progress("MARKET_AUTO_DRY_RUN=BOOTSTRAP_PENDING_DAILY_NOT_STARTED")
                return logs
            raise ValueError("First run needs the verified private Oct/Nov bootstrap")
        existing_days = sorted({d for entry in state["periods"]["1min"].values()
                                for d in entry["days"]})
        if not existing_days:
            raise ValueError("No physical market minute-day ledger")
        latest = date.fromisoformat(existing_days[-1])
        end = requested_date or last_eligible_day()
        if end > last_eligible_day():
            raise ValueError("Do not automatically ingest unconfirmed intraday trading bars")
        begin = latest + timedelta(days=1)
        if end < begin:
            progress("MARKET_DAILY_ALREADY_CURRENT=" + latest.isoformat())
            return logs
        if (end - begin).days + 1 > max_days:
            raise ValueError("More than max_days of missed market history; increase --max-days")
        calibration = S._json(P.BASE / "calibration" / "latest.json")
        if (calibration.get("calibration_passed") is not True
                or len(calibration.get("providers", {})) != 3):
            raise ValueError("Missing previously verified QMT purchased calibration")
        pinned = state.get("qmt_calibration_sha256")
        if pinned is None or P.sha_bytes(P.canonical(calibration)) != pinned:
            raise ValueError("QMT calibration SHA differs from initial accepted physical update")
        for provider in calibration["providers"].values():
            paid = Path(provider["paid_source_path"])
            if paid.is_symlink() or not paid.is_file() or L.hash_file(paid) != provider.get("paid_source_sha256"):
                raise ValueError("Purchased calibration source changed; refusing daily QMT write")
        for n in range((end - begin).days + 1):
            day = begin + timedelta(days=n)
            if day.weekday() >= 5:
                continue
            # Existing TDX DAY download, accepted Parquet source and local
            # monthly day materialization are reused, never reimplemented.
            if apply:
                LIVE._sync_unlocked(root, day, day, max_days=1,
                                    materialize_local=True, logger=progress)
                reference = _reference_for_day(root, day)
            else:
                reference = _reference_for_day(root, day)
            if not reference:
                progress("MARKET_DAILY_NO_OFFICIAL_DAY=" + day.isoformat())
                continue
            if not apply:
                logs.append({"date": str(day), "status": "DRY_RUN",
                             "official_sh_sz_stocks": len(reference)})
                continue
            src, doc = stage_day(root, day, reference, calibration, cfg,
                                 progress=progress)
            month = day.strftime("%Y-%m")
            result = S.install_month(
                root, month,
                (pa.Table.from_batches([b]) for b in
                 pq.ParquetFile(src).iter_batches(batch_size=32768, use_threads=False)),
                source_id="DAILY:" + str(day) + ":" + doc["sha256"],
                days=[str(day)], state=state, progress=progress)
            logs.append({**result, "date": str(day),
                         "quarantined_stocks": len(doc["quarantined"])})
            state = S.state_for(root)
        progress("MARKET_UPDATE_SUMMARY=" + json.dumps(
            {"jobs": logs, "market_root": str(L.storage_root(root)),
             "original_history_reprocessed": False,
             "qmt_0930_zero_trade_discarded": True,
             "current_month_only": True}, ensure_ascii=False, sort_keys=True))
        return logs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--mode", choices=("auto", "bootstrap", "daily"), default="auto")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--day", type=date.fromisoformat)
    parser.add_argument("--max-days", type=int, default=30)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args(argv)
    results = update(args.root, mode=args.mode, apply=not args.dry_run,
                     requested_date=args.day, config=args.config,
                     max_days=args.max_days)
    print("MARKET_UPDATE_COMPLETE=" + json.dumps(
        {"mode": args.mode, "dry_run": args.dry_run,
         "steps": len(results)}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
