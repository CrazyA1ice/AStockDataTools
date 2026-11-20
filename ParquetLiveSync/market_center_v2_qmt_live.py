"""V2-D2 optional, one-shot QMT *connection-only* health observation.

Invoked only by explicit user action. Calls the existing bounded
qmt_connect_preflight.probe_once(), which launches a subprocess to perform
xtdata.get_client() only. No market query, QMT download or writes.

This health observation NEVER grants finance resume/market write permissions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

CN = timezone(timedelta(hours=8))
DEFAULT_TIMEOUT_SECONDS = 15
SCHEDULE_START_MINUTE = 19 * 60 + 55
SCHEDULE_END_MINUTE = 20 * 60 + 20


def outstanding_resume_gates(preview: dict, *, qmt_observation: dict | None = None) -> list[dict]:
    """Display explicit non-cleared gates even when static blockers=[].

    These are four *separate* gates; NONE authorizes execution even if
    connection-only observation succeeds.
    """
    static_good = (
        type(preview) is dict and
        preview.get("status") == "PREVIEW_CHECKS_PASSED_EXECUTION_STILL_DISABLED" and
        preview.get("allowed_to_execute") is False)
    qmt_ok = (
        type(qmt_observation) is dict and
        qmt_observation.get("status") == "QMT_CONNECTION_OBSERVED_ONLY" and
        qmt_observation.get("connected_now") is True)
    return [
        {"key": "static_evidence", "ok": bool(static_good),
         "label": "同次回执、失败批次与持久化游标",
         "detail": "已通过只读核对" if static_good else "未通过或尚未核对"},
        {"key": "qmt_live", "ok": bool(qmt_ok),
         "label": "QMT 当前连接（仅即时观察）",
         "detail": "当前连接测试成功，不能保证续跑时仍在线"
                   if qmt_ok else "未检测成功；点击检查连接，不会下载行情"},
        {"key": "writer_exclusive", "ok": False,
         "label": "正式 20:05 任务锁与独占写入许可",
         "detail": "尚未进入正式执行入口；不可仅凭锁空闲状态授权写入"},
        {"key": "production_version", "ok": False,
         "label": "正式执行版本与固定 SHA",
         "detail": "尚未确认受控重试模块已部署到 canonical 正式目录"},
        {"key": "finance_backup", "ok": False,
         "label": "财务历史版本快照、备份与回滚",
         "detail": "尚未执行财务事务和可恢复性预检"},
    ]


def observe_qmt_connection(*, now: datetime | None = None,
                           probe: Callable | None = None,
                           timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """One explicit bounded xtdata.get_client() observation; never download.

    Does NOT start/stop or launch QMT itself. Refuses the scheduled update
    window to avoid even a harmless connection probe competing with 20:05.
    """
    if type(timeout_seconds) is not int or not 5 <= timeout_seconds <= 25:
        raise ValueError("bounded probe timeout must be between 5 and 25 seconds")
    now = now or datetime.now(CN)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone_aware_clock_required")
    china = now.astimezone(CN)
    minute = china.hour * 60 + china.minute
    base = {
        "observed_at_china": china.isoformat(),
        "allowed_to_execute": False,
        "allowed_to_download": False,
        "allowed_to_write_market": False,
        "allowed_to_modify_finance_progress": False,
        "download_calls": 0,
        "is_connection_only": True,
        "connection_stability_certified": False,
    }
    if SCHEDULE_START_MINUTE <= minute < SCHEDULE_END_MINUTE:
        return {**base, "status": "QMT_CONNECTION_PROBE_SCHEDULE_BLOCKED",
                "connected_now": False, "qmt_connection_attempts": 0,
                "detail": "北京时间19:55至20:20保留给20:05自动任务"}
    if probe is None:
        # Import is side-effect free; only the explicit invocation below
        # launches an isolated subprocess to call xtdata.get_client().
        from qmt_connect_preflight import probe_once
        probe = probe_once
    try:
        ok, detail = probe(timeout_seconds=timeout_seconds)
        if type(ok) is not bool or type(detail) is not str:
            raise ValueError("malformed_qmt_probe_reply")
    except Exception as exc:
        return {**base, "status": "QMT_CONNECTION_PROBE_FAILED",
                "connected_now": False, "qmt_connection_attempts": 1,
                "detail": "probe_exception_" + type(exc).__name__}
    return {
        **base,
        "status": ("QMT_CONNECTION_OBSERVED_ONLY"
                   if ok else "QMT_CONNECTION_UNAVAILABLE"),
        "connected_now": ok, "qmt_connection_attempts": 1,
        "detail": detail[:240],
    }
