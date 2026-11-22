"""P5: explicit, bounded QMT Capital LOCAL-cache vs verified history comparison.

Parent invokes an isolated QMT cache-only child after opt-in. The child emits
field hashes to a captured pipe, never raw financial values to the terminal.
No download APIs, persistent file creation, schedule edits or finance writes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import subprocess
import sys

import market_center_finance_pending_triage as P2
import market_center_finance_pending_snapshot_review as P3
import market_center_finance_pending_snapshot_integrity as P4
import qmt_extra_data as E

CN = timezone(timedelta(hours=8))
PROOF_TYPES = ("REPORT_KEYS_ADDED_OR_REMOVED",
               "BUSINESS_OR_DATE_FIELD_CHANGED")
MAX_STOCKS = 2
MAX_SNAPSHOT_FILES = 8
MAX_TOTAL_SNAPSHOT_BYTES = 8 * 1024 * 1024
MAX_CACHE_ROWS = 2000
MAX_FIELDS = 128
MAX_DATE_DETAILS = 32
MAX_CHILD_STDOUT_BYTES = 3 * 1024 * 1024
FIELD = re.compile(r"[A-Za-z0-9_]{1,96}")
SENTINEL = "FINANCE_P5_CACHED_FINGERPRINTS="


class CacheCompareBlocked(ValueError):
    """An input, cache, or local history is incomplete or changed."""


def _digest(value) -> str:
    return sha256(E.canonical_json(value).encode("utf-8")).hexdigest()


def _report_key_date(value) -> str:
    """Strict QMT m_timetag date label; not a certified financial filing date."""
    try:
        value = json.loads(E.canonical_json(value))
        if type(value) is bool or type(value) not in (str, int, float):
            raise ValueError("unsupported QMT key date type")
        if type(value) is float:
            if not math.isfinite(value) or not value.is_integer():
                raise ValueError("fractional QMT key date")
            value = int(value)
        token = str(value).strip()
        if re.fullmatch(r"\d{8}", token):
            day = datetime.strptime(token, "%Y%m%d").date()
        elif re.fullmatch(r"\d{14}", token):
            day = datetime.strptime(token, "%Y%m%d%H%M%S").date()
        elif re.fullmatch(r"\d{13}", token):
            # Reject decimal date-like encodings such as YYYYMMDDHHmmm;
            # treating one as Unix milliseconds would invent the wrong date.
            if re.fullmatch(r"(19|20)\d{6}", token[:8]):
                try:
                    date.fromisoformat(token[:8])
                except ValueError:
                    pass
                else:
                    raise ValueError("ambiguous numeric QMT date encoding")
            day = datetime.fromtimestamp(int(token) / 1000, CN).date()
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", token):
            day = date.fromisoformat(token)
        elif re.fullmatch(
                r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
                r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?", token):
            stamp = datetime.fromisoformat(token.replace("Z", "+00:00"))
            day = (stamp.astimezone(CN).date()
                   if stamp.tzinfo is not None else stamp.date())
        else:
            raise ValueError("unknown QMT report-key encoding")
        if not 1980 <= day.year <= 2100:
            raise ValueError("QMT report-key date outside bounded range")
        return day.isoformat()
    except (ValueError, OverflowError, OSError) as exc:
        raise CacheCompareBlocked("qmt_report_key_date_unverifiable") from exc


def _fingerprint(row: dict, *, date_details=False) -> dict:
    if type(row) is not dict or len(row) > MAX_FIELDS + 1:
        raise CacheCompareBlocked("cache_record_field_budget")
    if ("m_timetag" not in row or row["m_timetag"] is None
            or type(row["m_timetag"]) in (dict, list, bool)
            or str(row["m_timetag"]).strip() in ("", "0")):
        raise CacheCompareBlocked("unkeyed_capital_report")
    fields = {}
    for key, value in row.items():
        if key == "_index":
            continue
        if type(key) is not str or FIELD.fullmatch(key) is None:
            raise CacheCompareBlocked("unexpected_capital_field_name")
        fields[key] = _digest(value)
    result = {"key_sha256": _digest(row["m_timetag"]),
              "field_sha256": fields}
    if date_details:
        result["report_key_date"] = _report_key_date(row["m_timetag"])
    return result


def _child_cache_fingerprints(code: str, *, date_details=False) -> dict:
    if type(code) is not str or P2.STOCK.fullmatch(code) is None:
        raise CacheCompareBlocked("invalid_child_symbol")
    from xtquant import xtdata
    # Exactly one read of the EXISTING local financial cache. No download,
    # no local market writes and no QMT history refresh methods.
    data = xtdata.get_financial_data(
        [code], ["Capital"], start_time="", end_time="",
        report_type="report_time")
    if (type(data) is not dict or set(data) != {code}
            or type(data[code]) is not dict
            or set(data[code]) != {"Capital"}):
        raise CacheCompareBlocked("incomplete_qmt_capital_cache_reply")
    records = E.dataframe_records(data[code]["Capital"])
    if not 0 < len(records) <= MAX_CACHE_ROWS:
        raise CacheCompareBlocked("empty_or_oversized_cached_capital")
    return {
        "format": "qmt_capital_cache_fingerprints_v1",
        "stock": code,
        "table": "Capital",
        "row_count": len(records),
        "records": [_fingerprint(row, date_details=date_details) for row in records],
    }


def _run_child(code: str, timeout_seconds: int = 25,
               runner=subprocess.run, *, date_details=False) -> dict:
    if type(timeout_seconds) is not int or not 5 <= timeout_seconds <= 30:
        raise CacheCompareBlocked("invalid_cache_child_timeout")
    cmd = [sys.executable, "-u", "-B", str(Path(__file__).resolve()),
           "--internal-cache-fingerprints", "--stock", code]
    if date_details:
        cmd.extend(["--report-key-date-details", "--explicit-readonly",
                    "--explicit-qmt-cache-read"])
    try:
        completed = runner(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=False, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise CacheCompareBlocked("qmt_cache_read_timed_out") from exc
    except OSError as exc:
        raise CacheCompareBlocked("qmt_cache_child_spawn_failed") from exc
    stdout = completed.stdout
    if (completed.returncode != 0 or type(stdout) is not bytes
            or len(stdout) > MAX_CHILD_STDOUT_BYTES):
        raise CacheCompareBlocked("qmt_cache_read_failed_or_exceeded_budget")
    lines = stdout.decode("utf-8", errors="replace").splitlines()
    matching = [line[len(SENTINEL):] for line in lines
                if line.startswith(SENTINEL)]
    if len(matching) != 1:
        raise CacheCompareBlocked("qmt_cache_fingerprint_receipt_missing")
    try:
        payload = json.loads(matching[0])
    except (TypeError, ValueError) as exc:
        raise CacheCompareBlocked("qmt_cache_fingerprint_receipt_invalid") from exc
    if (type(payload) is not dict
            or payload.get("format") != "qmt_capital_cache_fingerprints_v1"
            or payload.get("stock") != code
            or payload.get("table") != "Capital"
            or type(payload.get("row_count")) is not int
            or not 0 < payload["row_count"] <= MAX_CACHE_ROWS
            or type(payload.get("records")) is not list
            or len(payload["records"]) != payload["row_count"]):
        raise CacheCompareBlocked("qmt_cache_fingerprint_envelope_invalid")
    for record in payload["records"]:
        if (type(record) is not dict
                or set(record) != ({"key_sha256", "field_sha256",
                                   "report_key_date"} if date_details else
                                   {"key_sha256", "field_sha256"})
                or type(record["key_sha256"]) is not str
                or len(record["key_sha256"]) != 64
                or type(record["field_sha256"]) is not dict
                or not 1 <= len(record["field_sha256"]) <= MAX_FIELDS
                or "m_timetag" not in record["field_sha256"]
                or (date_details and
                    (type(record["report_key_date"]) is not str or
                     re.fullmatch(r"\d{4}-\d{2}-\d{2}",
                                  record["report_key_date"]) is None))):
            raise CacheCompareBlocked("qmt_cache_fingerprint_record_invalid")
        if (any(type(k) is not str or FIELD.fullmatch(k) is None
                or type(v) is not str or len(v) != 64
                or re.fullmatch(r"[0-9a-f]{64}", v) is None
                for k, v in record["field_sha256"].items())
                or re.fullmatch(r"[0-9a-f]{64}",
                                record["key_sha256"]) is None):
            raise CacheCompareBlocked("qmt_cache_fingerprint_digest_invalid")
    if date_details:
        for record in payload["records"]:
            try:
                if (date.fromisoformat(record["report_key_date"]).isoformat()
                        != record["report_key_date"]):
                    raise ValueError("noncanonical date")
            except ValueError as exc:
                raise CacheCompareBlocked(
                    "qmt_cache_report_key_date_invalid") from exc
    return payload


def _pick_two(ledger: dict, p3_sample_codes: set[str]) -> list[dict]:
    selected = []
    for proof in PROOF_TYPES:
        group = []
        for code, item in ledger["pending"].items():
            if item["reason"] != "SOURCE_HISTORY_CONFLICT":
                continue
            match = P2.CONFLICT.fullmatch(item["detail"])
            if (match is None or match.group(1) != code
                    or match.group(2) != "Capital"
                    or match.group(4) != proof):
                continue
            group.append({
                "stock": code, "proof_class": proof,
                "pending_asof": item["asof"], "attempts": item["attempts"],
            })
        if not group:
            raise CacheCompareBlocked("missing_required_capital_proof_class_" + proof)
        # Reuse a P3/P4-listed sample when possible; otherwise choose the
        # lexicographically first pending stock with the other proof class.
        group.sort(key=lambda x: (
            x["stock"] not in p3_sample_codes, x["stock"]))
        selected.append(group[0])
    return selected


def _old_verified_fingerprints(finance: Path, extra: Path,
                               item: dict, *, date_details=False) -> tuple[list[dict], dict]:
    code = item["stock"]
    if type(code) is not str or P2.STOCK.fullmatch(code) is None:
        raise CacheCompareBlocked("invalid_history_stock")
    meta = P3._inventory(finance, code, "Capital")
    files = P3._files(finance / "Capital" / code / "snapshots", P3.SNAP)
    if not files or len(files) > MAX_SNAPSHOT_FILES:
        raise CacheCompareBlocked("missing_or_unbounded_old_capital_versions")
    total_bytes = sum(path.stat().st_size for path in files)
    if total_bytes > MAX_TOTAL_SNAPSHOT_BYTES:
        raise CacheCompareBlocked("old_capital_snapshot_budget")
    fake_scope = {"stock": code, "first_blocking_table": "Capital"}
    by_day = {}
    for path in sorted(files):
        P4._snapshot(fake_scope, path, extra)
        day = path.name[:10]
        by_day.setdefault(day, []).append(path)
    merged = Counter()
    for day in sorted(by_day):
        chosen = E._financial_snapshot_file(extra, code, "Capital", day)
        if chosen is None or chosen not in by_day[day]:
            raise CacheCompareBlocked("historical_active_selection_failed")
        old_rows = E._financial_snapshot_rows(extra, code, "Capital", day)
        if old_rows is None:
            raise CacheCompareBlocked("historical_selected_version_missing")
        raw = Counter(E.canonical_json({
            k: v for k, v in row.items() if k != "_index"})
            for row in old_rows)
        merged |= raw  # Same union semantics as importer._prior_rows.
    if not merged or sum(merged.values()) > MAX_CACHE_ROWS:
        raise CacheCompareBlocked("unbounded_historical_capital_union")
    if any(multiplicity != 1 for multiplicity in merged.values()):
        raise CacheCompareBlocked("duplicate_historical_raw_records")
    return ([_fingerprint(json.loads(record), date_details=date_details)
             for record in merged],
            {"snapshot_candidates_verified": len(files),
             "historical_selected_dates": len(by_day),
             "selected_history_variants": len(merged),
             "active_pins_structurally_present": meta["active_pin_metadata"],
             "history_fingerprint_locally_verified": True})


def _locate_report_key_dates(old: list[dict], fresh: list[dict],
                             outcome: dict) -> dict:
    """Expose bounded QMT m_timetag date labels and changed field NAMES only."""
    def dates(rows):
        by_key, by_day = {}, {}
        for row in rows:
            key = row["key_sha256"]
            label = row.get("report_key_date")
            if (type(label) is not str or
                    not re.fullmatch(r"\d{4}-\d{2}-\d{2}", label)):
                raise CacheCompareBlocked("missing_verified_qmt_key_date")
            try:
                if date.fromisoformat(label).isoformat() != label:
                    raise ValueError("noncanonical")
            except ValueError as exc:
                raise CacheCompareBlocked("invalid_qmt_key_date") from exc
            if ((key in by_key and by_key[key] != label) or
                    (label in by_day and by_day[label] != key)):
                raise CacheCompareBlocked("ambiguous_qmt_key_date_mapping")
            by_key[key], by_day[label] = label, key
        return by_key

    old_dates, fresh_dates = dates(old), dates(fresh)
    previous, current = {}, {}
    for row in old:
        previous.setdefault(row["key_sha256"], []).append(row["field_sha256"])
    for row in fresh:
        key = row["key_sha256"]
        if key in current:
            raise CacheCompareBlocked("duplicate_cached_report_key")
        current[key] = row["field_sha256"]
    old_keys, fresh_keys = set(previous), set(current)
    removed = sorted(old_dates[k] for k in old_keys - fresh_keys)
    added = sorted(fresh_dates[k] for k in fresh_keys - old_keys)
    changed, field_totals = [], Counter()
    for key in old_keys & fresh_keys:
        variants = previous[key]
        def business(fields):
            return {name: value for name, value in fields.items()
                    if name != "m_quarter"}
        stable = {json.dumps(business(fields), sort_keys=True)
                  for fields in variants}
        if len(stable) != 1:
            raise CacheCompareBlocked("ambiguous_historical_business_key_dates")
        before, after = business(variants[0]), business(current[key])
        names = sorted(name for name in before.keys() | after.keys()
                       if before.get(name) != after.get(name))
        if names:
            if old_dates[key] != fresh_dates[key]:
                raise CacheCompareBlocked("mismatched_common_key_date")
            for name in names:
                if FIELD.fullmatch(name) is None or name == "m_timetag":
                    raise CacheCompareBlocked("unsafe_date_detail_field")
                field_totals[name] += 1
            changed.append({"report_key_date": old_dates[key], "fields": names})
    changed.sort(key=lambda x: x["report_key_date"])
    expected = {entry["field"]: entry["report_keys"]
                for entry in outcome["changed_non_quarter_field_counts"]}
    if (len(removed) != outcome["previous_keys_missing_from_cache"]
            or len(added) != outcome["cached_keys_absent_from_previous"]
            or field_totals != Counter(expected)):
        raise CacheCompareBlocked("qmt_key_dates_not_aligned_with_p5_counts")
    if len(removed) + len(added) + len(changed) > MAX_DATE_DETAILS:
        raise CacheCompareBlocked("report_key_date_detail_budget_exceeded")
    return {
        "source_key": "QMT_CAPITAL_M_TIMETAG",
        "date_labels_from_existing_local_cache": True,
        "official_report_periods_or_filing_dates_certified": False,
        "previous_only_key_dates": removed,
        "current_only_key_dates": added,
        "changed_business_field_key_dates": changed,
        "m_quarter_date_labels_omitted": True,
        "historical_pending_remains_blocked": True,
        "financial_original_values_emitted": False,
    }


def _compare(old: list[dict], fresh: list[dict], *, date_details=False) -> dict:
    previous = {}
    current = {}
    for row in old:
        previous.setdefault(row["key_sha256"], []).append(row["field_sha256"])
    for row in fresh:
        key = row["key_sha256"]
        if key in current:
            raise CacheCompareBlocked("duplicate_cached_report_key")
        current[key] = row["field_sha256"]
    old_keys, fresh_keys = set(previous), set(current)
    historical_disagreement = 0
    changed = Counter()
    quarters_changed = 0
    for key in sorted(old_keys & fresh_keys):
        previous_variants = previous[key]
        def business(fields):
            return {f: v for f, v in fields.items() if f != "m_quarter"}
        stable = {json.dumps(business(f), sort_keys=True)
                  for f in previous_variants}
        if len(stable) != 1:
            historical_disagreement += 1
            continue
        before = business(previous_variants[0])
        after = business(current[key])
        for field in before.keys() | after.keys():
            if before.get(field) != after.get(field):
                changed[field] += 1
        if ({"m_quarter"} <= set(previous_variants[0]) & set(current[key])
                and any(p["m_quarter"] != current[key]["m_quarter"]
                        for p in previous_variants)):
            quarters_changed += 1
    if old_keys != fresh_keys:
        verdict = "REPORT_KEYS_ADDED_OR_REMOVED"
    elif historical_disagreement:
        verdict = "HISTORICAL_BUSINESS_FIELD_REVISION"
    elif changed:
        verdict = "BUSINESS_OR_DATE_FIELD_CHANGED"
    elif quarters_changed:
        verdict = "M_QUARTER_ONLY_CANDIDATE_NOT_APPROVED"
    else:
        verdict = "NO_DIFFERENCE_OBSERVED_IN_CURRENT_CACHE"
    result = {
        "previous_report_keys": len(old_keys),
        "cached_report_keys": len(fresh_keys),
        "previous_keys_missing_from_cache": len(old_keys - fresh_keys),
        "cached_keys_absent_from_previous": len(fresh_keys - old_keys),
        "matching_report_keys": len(old_keys & fresh_keys),
        "historical_business_conflicting_keys": historical_disagreement,
        "changed_non_quarter_field_counts": [
            {"field": field, "report_keys": count}
            for field, count in sorted(changed.items())
        ],
        "m_quarter_changed_matching_report_keys": quarters_changed,
        "observed_class": verdict,
        "current_cache_only_not_provider_certified": True,
    }
    if date_details:
        result["report_key_date_details"] = _locate_report_key_dates(
            old, fresh, result)
    return result


def _prepare_verified_histories(state_module: Path | str,
                                market_root: Path | str, expected_sha: str, *,
                                now: datetime | None = None,
                                date_details=False):
    """Verify canonical ledger plus two old Capital snapshot unions, NO QMT."""
    if type(expected_sha) is not str or re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha) is None:
        raise CacheCompareBlocked("explicit_financial_ledger_sha_required")
    expected_sha = expected_sha.lower()
    current = now or datetime.now(CN)
    if current.tzinfo is None or current.utcoffset() is None:
        raise CacheCompareBlocked("timezone_aware_clock_required")
    wall = current.astimezone(CN)
    if 19*60+50 <= wall.hour*60+wall.minute < 20*60+25:
        raise CacheCompareBlocked("reserved_2005_financial_writer_window")
    preview = P3.review(state_module, market_root, now=wall)
    if preview["progress_sha256"] != expected_sha:
        raise CacheCompareBlocked("financial_progress_sha_changed")
    path = P2._trusted_path(Path(state_module))
    ledger, observed = P2._read_ledger(path)
    if observed != expected_sha:
        raise CacheCompareBlocked("financial_progress_changed_before_comparison")
    first = _pick_two(ledger, {row["stock"] for row in preview["samples"]})
    finance = P3._root(Path(market_root))
    extra = Path(market_root) / "qmt_extra"
    histories = []
    total = 0
    for item in first:
        fingerprints, details = _old_verified_fingerprints(
            finance, extra, item, date_details=date_details)
        total += details["snapshot_candidates_verified"]
        if total > MAX_SNAPSHOT_FILES:
            raise CacheCompareBlocked("two_stock_history_file_budget")
        histories.append((item, fingerprints, details))
    # Revalidate ledger before QMT interaction, never allow stale scope.
    if P2.summarize_pending(state_module)["progress_sha256"] != expected_sha:
        raise CacheCompareBlocked("financial_progress_changed_before_qmt")
    return expected_sha, histories


def preflight(state_module: Path | str, market_root: Path | str,
              expected_sha: str, *, now: datetime | None = None) -> dict:
    """Explicit offline gate before the separate opt-in local QMT cache read."""
    expected_sha, histories = _prepare_verified_histories(
        state_module, market_root, expected_sha, now=now)
    return {
        "status": "FINANCE_P5_CAPITAL_TWO_STOCK_OFFLINE_PREFLIGHT_NOT_CERTIFIED",
        "progress_sha256": expected_sha,
        "sample_rule": "ONE_FROM_EACH_CAPITAL_PROOF_CLASS",
        "sample_count": len(histories),
        "samples": [{
            "stock": item["stock"],
            "pending_proof_class": item["proof_class"],
            "historical_snapshot_candidates_verified":
                details["snapshot_candidates_verified"],
            "historical_selected_dates": details["historical_selected_dates"],
            "selected_history_variants": details["selected_history_variants"],
        } for item, _fingerprints, details in histories],
        "selected_historical_snapshot_content_locally_verified": True,
        "current_qmt_cache_compared": False,
        "actual_conflict_report_dates_located": False,
        "only_capital_first_blockers": True,
        "qmt_cache_calls": 0, "download_calls": 0,
        "financial_original_values_emitted": False,
        "source_authenticity_certified": False,
        "can_download": False, "can_repair": False,
        "can_execute": False, "market_file_writes": False,
    }


def compare(state_module: Path | str, market_root: Path | str,
            expected_sha: str, *, now: datetime | None = None,
            read_cache=_run_child, date_details=False) -> dict:
    expected_sha, histories = _prepare_verified_histories(
        state_module, market_root, expected_sha, now=now,
        date_details=date_details)
    results = []
    for item, fingerprints, details in histories:
        fresh = (read_cache(item["stock"], date_details=True)
                 if date_details else read_cache(item["stock"]))
        outcome = _compare(fingerprints, fresh["records"],
                           date_details=date_details)
        if P2.summarize_pending(state_module)["progress_sha256"] != expected_sha:
            raise CacheCompareBlocked("financial_progress_changed_during_qmt")
        results.append({
            "stock": item["stock"], "pending_proof_class": item["proof_class"],
            "pending_asof": item["pending_asof"], "attempts": item["attempts"],
            **details, **outcome,
            "stored_conflict_reproduced_by_cache_read":
                outcome["observed_class"] == item["proof_class"],
        })
    return {
        "status": "FINANCE_P5_CACHED_CAPITAL_DIFF_READONLY_NOT_SOURCE_CERTIFIED",
        "progress_sha256": expected_sha,
        "sample_rule": "ONE_FROM_EACH_CAPITAL_PROOF_CLASS",
        "sample_count": len(results),
        "samples": results,
        "only_capital_first_blockers": True,
        "fresh_qmt_cache_read_only": True,
        "report_key_dates_explicitly_requested": bool(date_details),
        "official_report_periods_certified": False,
        "qmt_cache_calls": len(results),
        "download_calls": 0,
        "temp_files_created": 0,
        "financial_original_values_emitted": False,
        "source_authenticity_certified": False,
        "nine_financial_tables_verified": False,
        "unvisited_stocks_certified": False,
        "can_download": False,
        "can_repair": False,
        "can_execute": False,
        "market_file_writes": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-module", type=Path)
    parser.add_argument("--market-root", type=Path)
    parser.add_argument("--expected-progress-sha256")
    parser.add_argument("--explicit-readonly", action="store_true")
    parser.add_argument("--explicit-qmt-cache-read", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--report-key-date-details", action="store_true")
    parser.add_argument("--internal-cache-fingerprints", action="store_true")
    parser.add_argument("--stock")
    args = parser.parse_args(argv)
    if args.internal_cache_fingerprints:
        # An offline-only invocation must never enter the QMT cache child,
        # even if a caller combines incompatible CLI flags.
        if (args.preflight_only or not args.stock
                or (args.report_key_date_details and not (
                    args.explicit_readonly and args.explicit_qmt_cache_read))):
            return 2
        try:
            payload = _child_cache_fingerprints(
                args.stock, date_details=args.report_key_date_details)
        except Exception:
            return 3
        print(SENTINEL + E.canonical_json(payload))
        return 0
    if args.preflight_only:
        if (not args.explicit_readonly or args.explicit_qmt_cache_read
                or args.report_key_date_details):
            print(json.dumps({
                "status": "FINANCE_P5_OFFLINE_PREFLIGHT_ONLY_READONLY_REQUIRED",
                "qmt_calls": 0, "can_execute": False,
                "market_file_writes": False,
            }, ensure_ascii=False))
            return 2
    elif not args.explicit_readonly or not args.explicit_qmt_cache_read:
        print(json.dumps({
            "status": "FINANCE_P5_TWO_EXPLICIT_OPTINS_REQUIRED",
            "qmt_calls": 0, "can_execute": False, "market_file_writes": False,
        }, ensure_ascii=False))
        return 2
    if not all((args.state_module, args.market_root,
                args.expected_progress_sha256)):
        parser.error("state-module, market-root and expected SHA required")
    try:
        if args.preflight_only:
            result = preflight(args.state_module, args.market_root,
                               args.expected_progress_sha256)
        else:
            result = compare(args.state_module, args.market_root,
                             args.expected_progress_sha256,
                             date_details=args.report_key_date_details)
    except (CacheCompareBlocked, P2.PendingTriageBlocked,
            P3.SnapshotReviewBlocked, P4.IntegrityBlocked,
            OSError, ValueError) as exc:
        print(json.dumps({
            "status": "FINANCE_P5_READONLY_SOURCE_COMPARE_BLOCKED",
            "reason": str(exc)[:160], "can_execute": False,
            "market_file_writes": False,
        }, ensure_ascii=False))
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
