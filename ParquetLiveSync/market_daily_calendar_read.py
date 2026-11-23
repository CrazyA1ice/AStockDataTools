"""One bounded, read-only QMT exchange-calendar probe for the GUI date default.

No QMT history download, no market files, no schedule task changes.
The child process is killed on timeout by subprocess.run.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import re
from pathlib import Path
import subprocess
import sys

CN = timezone(timedelta(hours=8))
SENTINEL = "MARKET_SIMPLE_CALENDAR="
ISO8 = re.compile(r"\d{8}")


class CalendarUnavailable(ValueError):
    pass


def parse_exchange_day(value) -> str:
    if isinstance(value, bool):
        raise CalendarUnavailable("invalid_calendar_day")
    if isinstance(value, (int, float)) and value >= 1_000_000_000:
        number = float(value)
        if number >= 100_000_000_000:
            number /= 1000
        day = datetime.fromtimestamp(number, CN).date()
        return day.isoformat()
    if not isinstance(value, (str, int)):
        raise CalendarUnavailable("unknown_calendar_day_type")
    raw = str(value)
    if not ISO8.fullmatch(raw):
        raise CalendarUnavailable("unsupported_calendar_day_format")
    try:
        return datetime.strptime(raw, "%Y%m%d").date().isoformat()
    except ValueError as exc:
        raise CalendarUnavailable("invalid_calendar_day") from exc


def last_session(values, cutoff: date) -> str:
    if not isinstance(values, (list, tuple)) or len(values) > 500:
        raise CalendarUnavailable("unbounded_exchange_calendar")
    lower = cutoff - timedelta(days=90)
    dates = []
    for value in values:
        try:
            d = date.fromisoformat(parse_exchange_day(value))
        except (CalendarUnavailable, OSError, OverflowError, ValueError):
            raise CalendarUnavailable("invalid_exchange_calendar_reply")
        if lower <= d <= cutoff:
            dates.append(d)
    if not dates:
        raise CalendarUnavailable("no_recent_confirmed_session")
    return max(dates).isoformat()


def _child_calendar(cutoff: date) -> dict:
    from xtquant import xtdata
    from_date = cutoff - timedelta(days=60)
    # Read only trading dates, never history download or QMT writes.
    result = xtdata.get_trading_dates(
        "SH", start_time=from_date.strftime("%Y%m%d"),
        end_time=cutoff.strftime("%Y%m%d"), count=-1)
    return {
        "market": "SH",
        "cutoff": cutoff.isoformat(),
        "last": last_session(result, cutoff),
        "source": "QMT交易日历",
    }


def query_calendar(cutoff: date, *, runner=subprocess.run,
                   timeout_seconds: int = 9) -> dict:
    if not isinstance(cutoff, date) or not 2 <= timeout_seconds <= 15:
        raise CalendarUnavailable("invalid_calendar_scope")
    script = Path(__file__).resolve()
    try:
        p = runner([sys.executable, "-u", "-B", str(script),
                    "--read-calendar", cutoff.isoformat()],
                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                   check=False, timeout=timeout_seconds)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CalendarUnavailable("qmt_calendar_timeout_or_unavailable") from exc
    if p.returncode != 0 or type(p.stdout) is not bytes or len(p.stdout) > 16384:
        raise CalendarUnavailable("qmt_calendar_child_failed")
    messages = [s[len(SENTINEL):] for s in
                p.stdout.decode("utf-8", errors="replace").splitlines()
                if s.startswith(SENTINEL)]
    if len(messages) != 1:
        raise CalendarUnavailable("qmt_calendar_receipt_missing")
    try:
        data = json.loads(messages[0])
    except ValueError as exc:
        raise CalendarUnavailable("bad_qmt_calendar_json") from exc
    if (not isinstance(data, dict) or data.get("market") != "SH"
            or data.get("cutoff") != cutoff.isoformat()
            or data.get("source") != "QMT交易日历"
            or not isinstance(data.get("last"), str)):
        raise CalendarUnavailable("qmt_calendar_receipt_mismatch")
    try:
        day = date.fromisoformat(data["last"])
    except ValueError as exc:
        raise CalendarUnavailable("qmt_calendar_day_not_iso") from exc
    if (day > cutoff or day < cutoff - timedelta(days=90)
            or day.isoformat() != data["last"]):
        raise CalendarUnavailable("qmt_calendar_day_out_of_bounds")
    return data


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "--read-calendar":
        return 2
    try:
        cutoff = date.fromisoformat(args[1])
        if cutoff.isoformat() != args[1]:
            return 2
        payload = _child_calendar(cutoff)
    except (CalendarUnavailable, OSError, ImportError, RuntimeError,
            ValueError, TypeError):
        return 2
    print(SENTINEL + json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
