"""One-shot, bounded, non-downloading QMT xtquant service availability check.

The 20:05 runner owns the six attempts and fixed 10-second waits. This
module makes only ONE connection attempt in an isolated child so a blocked
vendor client cannot hang the scheduled runner indefinitely. Importing this
module is offline and side-effect free. Do not turn this into a download or
a historical QMT data query.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

CONNECT_SENTINEL = "QMT_XTDATA_GET_CLIENT_OK"
CHILD = (
    "from xtquant import xtdata; "
    "client=xtdata.get_client(); "
    "assert client is not None, 'xtdata.get_client returned None'; "
    f"print({CONNECT_SENTINEL!r}, flush=True)"
)
DEFAULT_TIMEOUT = 25


def _last_error(message: str) -> str:
    lines = [part.strip() for part in message.splitlines() if part.strip()]
    line = next(
        (part for part in reversed(lines)
         if "无法连接" in part or "Exception:" in part
         or "Error:" in part or "Timeout" in part),
        lines[-1] if lines else "no stderr diagnostics",
    )
    return line.replace("\r", " ").replace("\t", " ")[:240]


def probe_once(*, timeout_seconds: int = DEFAULT_TIMEOUT,
               runner=subprocess.run) -> tuple[bool, str]:
    """Return availability and a short explanation; never contact a remote API."""
    if type(timeout_seconds) is not int or not 5 <= timeout_seconds <= 30:
        raise ValueError("probe timeout must be an integer between 5 and 30")
    command = [sys.executable, "-u", "-B", "-c", CHILD]
    try:
        result = runner(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False, timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return False, f"client_probe_timeout_{timeout_seconds}s"
    except OSError as exc:
        return False, f"client_probe_spawn_error_{type(exc).__name__}"
    output = result.stdout or ""
    if result.returncode == 0 and CONNECT_SENTINEL in output.splitlines():
        return True, "xtdata_get_client_connected"
    if result.returncode == 0:
        return False, "xtdata_get_client_success_sentinel_missing"
    return False, "xtdata_exit_{}: {}".format(
        result.returncode, _last_error(result.stderr or output))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)
    try:
        ready, detail = probe_once(timeout_seconds=args.timeout_seconds)
    except ValueError as exc:
        parser.error(str(exc))
    if ready:
        print("QMT_SERVICE_PROBE_RESULT=CONNECTED", flush=True)
        return 0
    print("QMT_SERVICE_PROBE_RESULT=UNAVAILABLE", flush=True)
    print("QMT_SERVICE_PROBE_REASON=" + detail, flush=True)
    return 3


if __name__ == "__main__":
    sys.exit(main())
