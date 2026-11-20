"""V2-D bounded diagnostics of the *same* 20:05 run and FINANCE resume preview.

Only reads canonical private receipts and exact same-run stage logs. No xtquant,
process launch, downloads, market writes, mutex acquisition or progress mutation.
A preview is NOT permission to execute an update from a detached worktree.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

CN = timezone(timedelta(hours=8))
STAGES = ("EIGHT_PERIODS", "SECTORS", "ADJUSTMENTS_ROTATING", "FINANCIAL_DAILY")
MAX_RECEIPT_BYTES = 2 * 1024 * 1024
MAX_PROGRESS_BYTES = 2 * 1024 * 1024
MAX_LOG_TAIL_BYTES = 192 * 1024
CODE = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")
CHECKPOINT = "QMT_FINANCIAL_CACHE_CHECKPOINT="
FAILED_GROUP = re.compile(
    r'(?:QMT cache batch worker nonzero exit=\d+ stocks=|'
    r'QMT client unavailable after three isolated worker attempts; '
    r'batch not checkpointed: )(\[[^\r\n]{1,1000}\])'
)


class FaultEvidenceBlocked(ValueError):
    pass


def _json_bytes(path: Path, cap: int) -> tuple[dict, str]:
    if path.is_symlink() or not path.is_file():
        raise FaultEvidenceBlocked("missing_or_redirected_receipt_" + path.name)
    if path.stat().st_size > cap:
        raise FaultEvidenceBlocked("oversized_receipt_" + path.name)
    raw = path.read_bytes()
    if len(raw) > cap:
        raise FaultEvidenceBlocked("receipt_exceeded_budget_" + path.name)
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise FaultEvidenceBlocked("malformed_receipt_" + path.name) from exc
    if type(obj) is not dict:
        raise FaultEvidenceBlocked("receipt_not_an_object_" + path.name)
    return obj, hashlib.sha256(raw).hexdigest()


def _log_tail(path_text: str, root: Path, run_stamp: str,
              stage: str) -> tuple[str, bool]:
    """Reject even existing foreign/stale/symlinked logs. Never search files."""
    if stage not in STAGES or type(path_text) is not str or not path_text:
        return "", False
    path = Path(path_text)
    expected = f"afternoon-{run_stamp}-{stage}.log"
    if not path.is_absolute() or path.name != expected or path.is_symlink():
        return "", False
    try:
        home = root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(home) or not resolved.is_file():
            return "", False
        with resolved.open("rb") as fh:
            size = fh.seek(0, 2)
            if size > MAX_LOG_TAIL_BYTES:
                fh.seek(size - MAX_LOG_TAIL_BYTES)
                fh.readline()
            else:
                fh.seek(0)
            return fh.read(MAX_LOG_TAIL_BYTES).decode(
                "utf-8-sig", errors="replace"), True
    except (OSError, ValueError):
        return "", False


def _run_identity(latest: dict) -> tuple[str, str]:
    started = latest.get("china_start")
    if type(started) is not str:
        raise FaultEvidenceBlocked("missing_run_china_start")
    try:
        timestamp = datetime.fromisoformat(started)
        if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(hours=8):
            raise ValueError("not_beijing_timezone")
        stamp = timestamp.strftime("%Y%m%d-%H%M%S")
        return timestamp.date().isoformat(), stamp
    except ValueError as exc:
        raise FaultEvidenceBlocked("invalid_run_identity") from exc


def _last_checkpoint(text: str) -> str | None:
    last = None
    for line in text.splitlines():
        if not line.startswith(CHECKPOINT):
            continue
        try:
            record = json.loads(line[len(CHECKPOINT):])
        except (ValueError, TypeError):
            continue
        if (type(record) is dict and type(record.get("cursor")) is str
                and CODE.fullmatch(record["cursor"])):
            last = record["cursor"]
    return last


def _failed_group(text: str) -> list[str]:
    matched = list(FAILED_GROUP.finditer(text))
    if not matched:
        return []
    try:
        rows = json.loads(matched[-1].group(1))
    except ValueError:
        return []
    if (type(rows) is not list or not 1 <= len(rows) <= 20
            or any(type(s) is not str or CODE.fullmatch(s) is None for s in rows)
            or rows != sorted(set(rows))):
        return []
    return rows


def _case(stage: str, item: dict, quality: dict, log: str, evidenced: bool) -> dict | None:
    code = item.get("exit_code")
    if type(code) is not int:
        code = None
    label = {
        "EIGHT_PERIODS": "八周期行情", "SECTORS": "板块",
        "ADJUSTMENTS_ROTATING": "除权", "FINANCIAL_DAILY": "财务",
    }[stage]
    validation = quality.get("data_validation")
    if code is None:
        return None
    category = None
    severity = "ERROR"
    title = ""
    advice = ""
    repair = "INSPECT"
    if code != 0:
        if not evidenced:
            category = "FAILED_LOG_UNVERIFIED"
            title = label + "执行失败；本次日志证据不足"
            advice = "先核对同一运行的日志路径与回执，不应猜测故障原因"
        elif stage == "FINANCIAL_DAILY" and (
                "QMT_CACHE_WORKER_CONNECT_UNAVAILABLE=" in log or
                "无法连接xtquant服务" in log or
                "QMT client unavailable after three isolated worker attempts" in log):
            category = "QMT_FINANCE_CONNECTION_LOST"
            title = "财务：QMT 服务在批次处理中断"
            advice = ("检查QMT是否登录且服务可用；核对真实检查点后只续跑尚未完成的财务批次，"
                      "不能重下全量或清空历史版本")
            repair = "FINANCE_RESUME_PREFLIGHT_ONLY"
        elif "QMT_CACHE_WORKER_UTF8_DECODE_ERROR=" in log:
            category = "QMT_FINANCE_TEXT_DECODE"
            title = "财务：供应商缓存文本解码异常"
            advice = "使用现有单股票隔离机制复核来源，不要把编码错误当成无财务记录"
        elif "timed out" in log.lower() and stage == "FINANCIAL_DAILY":
            category = "QMT_FINANCE_WORKER_TIMEOUT"
            title = "财务：批次工作进程超时"
            advice = "检查QMT响应与超时范围；保持本轮已保存的游标和版本"
        elif "SOURCE_HISTORY_CONFLICT" in log and stage == "FINANCIAL_DAILY":
            category = "FINANCE_HISTORY_CONFLICT"
            title = "财务：历史版本和本轮来源存在冲突"
            advice = "保留来源版本，人工审核历史字段和报告日，不应自动覆盖"
        else:
            category = "STAGE_FAILURE_UNCLASSIFIED"
            title = label + "运行失败，尚未识别具体类型"
            advice = "查看本次阶段日志；禁止直接全量重下"
    elif stage == "ADJUSTMENTS_ROTATING" and validation == "PARTIAL" and (
            "后续仍有批次" in str(quality.get("detail", ""))):
        category = "ADJUSTMENTS_ROTATION_PENDING"
        severity = "INFO"
        title = "除权：本批成功，轮换仍有后续批次"
        advice = "这不是本批错误；按原计划继续后续轮换，不要重新覆盖本批"
        repair = "NONE"
    elif quality.get("cross_validation") == "FAIL":
        category = "CROSS_SOURCE_SAMPLE_DISAGREEMENT"
        severity = "WARN"
        title = label + "跨数据源抽样存在价格差异"
        advice = "保留双方来源版本，按股票和时间比对价量；不能自动覆盖本地记录"
    elif validation in ("FAIL", "PARTIAL"):
        category = "STAGE_DATA_QUALITY_REVIEW"
        severity = "WARN"
        title = label + "本轮数据校验需要复核"
        advice = "查看本次结构化验证详情与来源差异；不能将阶段成功当作数据完整"
    if category is None:
        return None
    return {
        "stage": stage, "name": label,
        "severity": severity, "category": category,
        "title": title, "explanation": advice,
        "repair_route": repair,
        "stage_exit_code": code,
        "same_run_log_verified": evidenced,
        "last_checkpoint_in_log": _last_checkpoint(log) if stage == "FINANCIAL_DAILY" else None,
        "failed_stock_batch": _failed_group(log) if stage == "FINANCIAL_DAILY" else [],
        "automatic_repair_allowed": False,
    }


def _finance_preview(case: dict | None, progress: dict | None,
                     run_day: str, now: datetime) -> dict:
    """Evidence-gated *preview*; running anything always remains prohibited."""
    reasons = []
    batch = case.get("failed_stock_batch", []) if case else []
    logfile_cursor = case.get("last_checkpoint_in_log") if case else None
    ledger_cursor = progress.get("daily_cursor") if progress else None
    daily_date = progress.get("daily_date") if progress else None
    if not case or case["category"] != "QMT_FINANCE_CONNECTION_LOST":
        reasons.append("not_a_verified_finance_connect_outage")
    if not batch:
        reasons.append("failed_batch_not_anchored")
    if not logfile_cursor:
        reasons.append("log_checkpoint_not_anchored")
    if progress is None:
        reasons.append("financial_progress_missing_or_invalid")
    else:
        if daily_date != run_day:
            reasons.append("saved_daily_date_differs_from_failed_run")
        if ledger_cursor != logfile_cursor:
            reasons.append("financial_cursor_changed_since_failure")
        if batch and (not isinstance(ledger_cursor, str)
                      or batch[0] <= ledger_cursor):
            reasons.append("failed_batch_not_after_persisted_cursor")
    if now.astimezone(CN).date().isoformat() != run_day:
        reasons.append("run_day_elapsed_do_not_replay_old_daily_window")
    hm = now.astimezone(CN).hour * 60 + now.astimezone(CN).minute
    if 19 * 60 + 55 <= hm < 20 * 60 + 20:
        reasons.append("reserved_2005_automatic_schedule_window")
    if case and not case["same_run_log_verified"]:
        reasons.append("same_run_log_not_verified")
    return {
        "status": "PREVIEW_CHECKS_PASSED_EXECUTION_STILL_DISABLED"
                  if not reasons else "PREVIEW_BLOCKED",
        "source_run_day": run_day,
        "failed_batch": batch,
        "saved_daily_cursor": ledger_cursor,
        "same_run_log_checkpoint": logfile_cursor,
        "saved_daily_date": daily_date,
        "checks": {"same_run_log_and_cursor_checked": not reasons,
                   "qmt_connected_now_verified": False,
                   "writer_mutex_free_verified": False,
                   "canonical_deployed_worker_version_verified": False,
                   "rollback_and_finance_version_snapshot_verified": False},
        "blockers": reasons,
        "allowed_to_execute": False,
        "allowed_to_download": False,
        "allowed_to_modify_progress": False,
        "market_file_writes": False,
        "qmt_calls": 0,
        "required_next_action": (
            "完成QMT实时连接、生产版本、共享写锁及财务版本备份核验后，"
            "独立部署受控的单财务续跑入口；此预览不会执行"),
    }


def diagnose_latest(module_dir: str | Path,
                    *, now: datetime | None = None) -> dict:
    """Bounded, unprivileged read of the exact latest canonical 20:05 receipt."""
    module = Path(module_dir)
    if (not module.is_absolute() or module.name.lower() != "parquetlivesync"
            or not module.is_dir() or any(p.is_symlink()
                                         for p in (module, *module.parents))):
        raise FaultEvidenceBlocked("canonical_module_directory_required")
    now = now or datetime.now(CN)
    if now.tzinfo is None or now.utcoffset() is None:
        raise FaultEvidenceBlocked("aware_clock_required")
    work = module / "work"
    receipt, receipt_sha = _json_bytes(
        work / "last-afternoon-unified.json", MAX_RECEIPT_BYTES)
    run_day, stamp = _run_identity(receipt)
    if type(receipt.get("stage_records")) is not dict:
        raise FaultEvidenceBlocked("run_stage_records_missing")
    validation = receipt.get("validation")
    sections = validation.get("sections", {}) if type(validation) is dict else {}
    if type(sections) is not dict:
        sections = {}
    stage_records = receipt["stage_records"]
    cases = []
    for stage in STAGES:
        item = stage_records.get(stage)
        if type(item) is not dict:
            continue
        log, evidenced = _log_tail(item.get("log_path"), work, stamp, stage)
        quality = sections.get(stage)
        if type(quality) is not dict:
            quality = {}
        case = _case(stage, item, quality, log, evidenced)
        if case is not None:
            cases.append(case)
    progress = None
    progress_sha = None
    try:
        progress, progress_sha = _json_bytes(
            work / "qmt_extra" / "financial-cache-progress.json",
            MAX_PROGRESS_BYTES)
        if (progress.get("format") != "qmt_financial_cache_import_v1" or
                type(progress.get("daily_date")) is not str or
                type(progress.get("daily_cursor")) is not str or
                type(progress.get("pending")) is not dict):
            progress = None
            progress_sha = None
    except FaultEvidenceBlocked:
        pass
    if receipt.get("qmt_preflight_status") == "QMT_SERVICE_UNAVAILABLE":
        cases.append({
            "stage": "RUNNER", "name": "任务预检",
            "severity": "ERROR", "category": "QMT_PRECHECK_UNAVAILABLE",
            "title": "20:05 任务预检无法连接 QMT",
            "explanation": "各更新阶段可能尚未执行；检查当前QMT服务，不能将预检失败当作行情文件损坏",
            "repair_route": "CONNECT_CHECK_BEFORE_ANY_RETRY",
            "stage_exit_code": None, "same_run_log_verified": False,
            "last_checkpoint_in_log": None, "failed_stock_batch": [],
            "automatic_repair_allowed": False,
        })
    failure = next((c for c in cases
                    if c["category"] == "QMT_FINANCE_CONNECTION_LOST"), None)
    preview = _finance_preview(failure, progress, run_day, now)
    priorities = {"ERROR": 0, "WARN": 1, "INFO": 2}
    cases.sort(key=lambda c: (priorities[c["severity"]], c["stage"]))
    return {
        "status": "V2D_READONLY_FAULT_DIAGNOSIS_NOT_EXECUTABLE",
        "run_status": receipt.get("status", "UNKNOWN"),
        "run_day": run_day,
        "run_stamp": stamp,
        "receipt_sha256": receipt_sha,
        "finance_progress_sha256": progress_sha,
        "fault_count": sum(x["severity"] == "ERROR" for x in cases),
        "warning_count": sum(x["severity"] == "WARN" for x in cases),
        "notice_count": sum(x["severity"] == "INFO" for x in cases),
        "cases": cases,
        "finance_resume_preview": preview,
        "requires_live_qmt_preflight": True,
        "source_crosscheck_not_automatically_certified": True,
        "allowed_to_execute": False,
        "market_file_writes": False,
        "qmt_calls": 0,
    }
