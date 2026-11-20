"""One-shot explicitly scoped V2-B historical market *read-only* survey.

This entry point never writes a report file or accesses QMT. Windows uses
the *same* named mutex as the 20:05 unified runner while reading Parquet.
A separate writer not using that mutex is still handled by file stat checks;
this is NOT a certified immutable snapshot.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

from market_center_v2_readonly_audit import AuditBlocked, PERIODS, survey

RUN_MUTEX = r"Local\AStockDataTools2005AllStages"
CHINA = timezone(timedelta(hours=8))


def _scheduled_window_reserved(now: datetime | None = None) -> bool:
    """Do not delay the 20:05 task by holding its mutex for a UI read."""
    now = (now or datetime.now(CHINA)).astimezone(CHINA)
    local = now.hour * 60 + now.minute
    return 19 * 60 + 55 <= local < 20 * 60 + 20


@contextmanager
def shared_market_read_guard():
    """Windows fail-fast access to existing scheduled/manual update mutex."""
    if os.name != "nt":
        yield
        return
    if _scheduled_window_reserved():
        raise AuditBlocked("reserved_2005_automatic_update_window")
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel.ReleaseMutex.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    handle = kernel.CreateMutexW(None, 0, RUN_MUTEX)
    if not handle:
        raise AuditBlocked("named_mutex_unavailable")
    acquired = False
    try:
        status = kernel.WaitForSingleObject(handle, 0)
        if status == 0:
            acquired = True
        elif status == 0x80:
            # A previous writer died. Refuse to interpret a potentially
            # interrupted transaction as a stable snapshot.
            kernel.ReleaseMutex(handle)
            raise AuditBlocked("abandoned_market_writer_mutex_refuse_read")
        elif status == 258:
            raise AuditBlocked("market_2005_task_or_manual_writer_is_running")
        else:
            raise AuditBlocked("market_mutex_wait_error")
        yield
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def audited_query(*, root: str | Path, start: str, end: str,
                  symbols: list[str] | tuple[str, ...],
                  periods: list[str] | tuple[str, ...],
                  explicit_readonly: bool = False) -> dict:
    if explicit_readonly is not True:
        raise AuditBlocked("explicit_readonly_optin_required")
    with shared_market_read_guard():
        return survey(root=root, start=start, end=end,
                      symbols=symbols, periods=periods,
                      explicit_readonly=explicit_readonly)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--market-root", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--symbols", required=True,
                   help="comma-separated exchange-qualified symbols")
    p.add_argument("--period", choices=PERIODS, action="append", required=True)
    p.add_argument("--explicit-readonly", action="store_true")
    args = p.parse_args(argv)
    symbols = [v.strip().upper() for v in args.symbols.split(",") if v.strip()]
    try:
        result = audited_query(
            root=args.market_root, start=args.start, end=args.end,
            symbols=symbols, periods=args.period,
            explicit_readonly=args.explicit_readonly)
    except AuditBlocked as exc:
        print(json.dumps({
            "status": "V2B_AUDIT_BLOCKED", "reason": str(exc),
            "market_file_writes": False, "qmt_calls": 0,
        }, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
