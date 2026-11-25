#!/usr/bin/env python3
"""Isolated Windows report observer; NEVER starts QMT or modifies market ledgers.

Sending requires an explicit approval flag and a working, unattended SSH key.
Durable O_EXCL intent prevents a second attempt for the same China date even
when SSH times out after the provider has accepted a message.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

CHINA = timezone(timedelta(hours=8))
STAGES = ("EIGHT_PERIODS", "FINANCIAL_DAILY", "SECTORS", "ADJUSTMENTS_ROTATING")
TASK = "AStockDataTools-ParquetLiveSync"
DEFAULT_REMOTE = "/home/ubuntu/.local/bin/astock-market-wecom-once.py"
SERVER_PATTERN = re.compile(r"^ubuntu@[A-Za-z0-9][A-Za-z0-9.-]{0,250}$")


class UnsafeReport(ValueError):
    pass


def now_china():
    return datetime.now(CHINA)


def read_receipt(path: Path):
    first = path.read_bytes()
    digest = hashlib.sha256(first).hexdigest()
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise UnsafeReport("RECEIPT_CHANGED_WHILE_READING")
    try:
        doc = json.loads(first.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UnsafeReport("RECEIPT_INVALID_JSON") from exc
    if not isinstance(doc, dict):
        raise UnsafeReport("RECEIPT_NOT_OBJECT")
    return doc, digest


def receipt_date(receipt):
    stamp = receipt.get("china_start")
    if not isinstance(stamp, str):
        raise UnsafeReport("CHINA_START_MISSING")
    try:
        dt = datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise UnsafeReport("CHINA_START_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() != timedelta(hours=8):
        raise UnsafeReport("CHINA_START_OFFSET_NOT_PLUS8")
    return dt


def check_contract(receipt, target_day, now):
    dt = receipt_date(receipt)
    if dt.date().isoformat() != target_day:
        raise UnsafeReport("RECEIPT_NOT_TODAYS_SCHEDULED_RUN")
    if dt.hour < 20 or (dt.hour == 20 and dt.minute < 5):
        raise UnsafeReport("RECEIPT_BEFORE_2005")
    if now < dt or now - dt > timedelta(hours=10):
        raise UnsafeReport("RECEIPT_OUTSIDE_FRESH_WINDOW")
    expected = {
        "format": "qmt_daily_single_trigger_v3",
        "invocation": "Scheduled",
        "mode": "UNIFIED_SINGLE_RUN",
        "run_scope": "ALL_FOUR_SECTIONS",
        "history_only": False,
    }
    for key, value in expected.items():
        if receipt.get(key) != value or type(receipt.get(key)) is not type(value):
            raise UnsafeReport("BAD_RECEIPT_CONTRACT_" + key.upper())
    if not isinstance(receipt.get("finished_local"), str):
        raise UnsafeReport("RECEIPT_UNFINISHED")
    records = receipt.get("stage_records")
    if not isinstance(records, dict) or not set(records).issubset(STAGES):
        raise UnsafeReport("BAD_STAGE_RECORDS")
    completed = receipt.get("steps_completed")
    if not isinstance(completed, list) or any(x not in STAGES for x in completed):
        raise UnsafeReport("BAD_COMPLETED_STAGES")
    if len(set(completed)) != len(completed):
        raise UnsafeReport("DUPLICATE_COMPLETED_STAGE")
    if not isinstance(receipt.get("errors"), list):
        raise UnsafeReport("BAD_ERRORS")
    if receipt.get("status") not in ("SUCCESS", "PARTIAL", "FAILED"):
        raise UnsafeReport("BAD_EXECUTION_STATUS")
    return dt


def market_task_info():
    ps = ("$ErrorActionPreference='Stop';"
          "$t=Get-ScheduledTask -TaskName 'AStockDataTools-ParquetLiveSync' -TaskPath '\\';"
          "$i=Get-ScheduledTaskInfo -TaskName 'AStockDataTools-ParquetLiveSync' -TaskPath '\\';"
          "[pscustomobject]@{state=[string]$t.State;last_run=$i.LastRunTime.ToString('o');"
          "last_result=[int]$i.LastTaskResult}|ConvertTo-Json -Compress")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                       text=True, capture_output=True, timeout=20, check=True)
    d = json.loads(r.stdout)
    if not isinstance(d, dict) or d.get("state") not in ("Ready", "Running", "Disabled", "Queued"):
        raise UnsafeReport("SCHEDULE_STATUS_INVALID")
    if d.get("last_result") == 267009 and d["state"] == "Ready":
        raise UnsafeReport("SCHEDULE_RESULT_INCONSISTENT")
    return d


def validate_task_completion(task, receipt_start):
    if task.get("state") != "Ready":
        raise UnsafeReport("WINDOWS_TASK_NOT_COMPLETE")
    value = task.get("last_run")
    if not isinstance(value, str):
        raise UnsafeReport("SCHEDULE_LAST_RUN_MISSING")
    try:
        started = datetime.fromisoformat(value)
    except ValueError as exc:
        raise UnsafeReport("SCHEDULE_LAST_RUN_INVALID") from exc
    if started.tzinfo is None:
        # Task Scheduler can return an Unspecified DateTime kind in PS5.1.
        started = started.replace(tzinfo=datetime.now().astimezone().tzinfo)
    if abs((started.astimezone(CHINA) - receipt_start).total_seconds()) > 1800:
        raise UnsafeReport("SCHEDULE_AND_RECEIPT_START_DIVERGED")
    if task.get("last_result") == 267009:
        raise UnsafeReport("SCHEDULE_STILL_RUNNING_CODE")


def format_message(receipt, task, day):
    v = receipt.get("validation") or {}
    if not isinstance(v, dict):
        v = {}
    stage = receipt.get("stage_records") or {}
    lines = ["【A股每日更新详情｜" + day + "】",
             "运行结果：" + str(receipt["status"]),
             "Windows任务退出码：" + str(task["last_result"]),
             "开始：" + str(receipt["china_start"]),
             "结束：" + str(receipt["finished_local"]),
             "QMT预检：" + str(receipt.get("qmt_preflight_status", "未验证")),
             "执行验证：" + str(v.get("execution", "UNVERIFIED")),
             "数据质量：" + str(v.get("data_validation", "UNVERIFIED")),
             "跨源验证：" + str(v.get("cross_validation", "UNVERIFIED")),
             "正常轮换：" + ("是" if v.get("routine_continuation") is True else "未确认"),
             "运行分类：" + str(receipt.get("operational_classification", "未分类"))]
    for name in STAGES:
        record = stage.get(name)
        code = record.get("exit_code") if isinstance(record, dict) else None
        lines.append(name + "：" + (str(code) if type(code) is int else "未执行"))
    sections = v.get("sections") if isinstance(v.get("sections"), dict) else {}
    finance = sections.get("FINANCIAL_DAILY")
    if isinstance(finance, dict):
        details = []
        for label, field in (("本轮处理", "processed"), ("待审", "pending_total"),
                             ("未遍历", "remaining_unvisited")):
            n = finance.get(field)
            if type(n) is int and n >= 0:
                details.append(label + str(n) + "只")
        if details:
            lines.append("财务详情：" + "；".join(details))
    adjustment = sections.get("ADJUSTMENTS_ROTATING")
    if isinstance(adjustment, dict):
        n = adjustment.get("processed")
        if type(n) is int and n >= 0:
            lines.append("除权本轮处理：" + str(n) + "只")
        if adjustment.get("next_batch_required") is True:
            lines.append("除权：后续仍需轮换")
    lines.append("错误数：" + str(len(receipt["errors"])))
    # Don't copy potentially secret exception strings or file paths into WeCom.
    lines.append("注：执行成功不等于财务历史、跨源及复权质量全部认证。")
    result = "\n".join(lines)
    if len(result.encode("utf-8")) > 2048:
        raise UnsafeReport("REPORT_TOO_LONG")
    return result


def reserve_once(path: Path, day: str, digest: str):
    path.mkdir(parents=True, exist_ok=True)
    marker = path / (day + ".intent.json")
    fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"day": day, "receipt_sha256": digest,
                   "status": "RESERVED_UNKNOWN_NO_AUTORETRY"}, f)
        f.flush()
        os.fsync(f.fileno())
    return marker


def dispatch(server, ssh_key, message, day, digest, remote):
    if not SERVER_PATTERN.fullmatch(server):
        raise UnsafeReport("SSH_TARGET_MUST_BE_UBUNTU_HOST")
    if not ssh_key.is_file():
        raise UnsafeReport("SSH_KEY_MISSING")
    if remote != DEFAULT_REMOTE:
        raise UnsafeReport("REMOTE_SCRIPT_PATH_NOT_PINNED")
    payload = json.dumps({"date": day, "receipt_sha256": digest, "text": message},
                         ensure_ascii=False).encode("utf-8")
    args = ["ssh.exe", "-T", "-p", "22", "-o", "BatchMode=yes", "-o", "PreferredAuthentications=publickey",
            "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10",
            "-o", "ClearAllForwardings=yes", "-i", str(ssh_key), server, "id -un"]
    try:
        response = subprocess.run(args, input=payload, capture_output=True, timeout=40)
    except subprocess.TimeoutExpired as exc:
        raise UnsafeReport("SSH_TIMEOUT_UNKNOWN_DO_NOT_RETRY") from exc
    # Dedicated authorized_keys forced-command runs the pinned sender even
    # though the client requests an innocuous id command. No general SSH shell.
    # Only print statuses from the fixed remote sender, never arbitrary stdout.
    output = response.stdout.decode("utf-8", errors="replace")
    codes = [s for s in output.splitlines() if s.startswith("WECOM_MARKET_") and len(s) < 120]
    return response.returncode, codes


def run(args):
    target = args.date or now_china().date().isoformat()
    if args.mode != "preview" and target <= "2026-11-25":
        raise UnsafeReport("NOV25_ALREADY_SENT_CUTOFF_NO_RESEND")
    now = now_china()
    if args.mode == "watch":
        # A 20:10 local task can wait through midnight but must not send stale results.
        deadline = datetime.fromisoformat(target).replace(tzinfo=CHINA) + timedelta(days=1, hours=4)
    else:
        deadline = now + timedelta(seconds=1)
    while True:
        now = now_china()
        if now > deadline:
            print("WECOM_MARKET_WATCH_DEADLINE_NO_SEND", flush=True)
            return 2
        info = market_task_info()
        if info["state"] == "Ready" and Path(args.receipt).is_file():
            receipt, digest = read_receipt(Path(args.receipt))
            try:
                started = check_contract(receipt, target, now)
                validate_task_completion(info, started)
            except UnsafeReport as exc:
                if args.mode != "watch":
                    raise
                # Old receipt while the newest task has not yet written its own.
                if str(exc) != "RECEIPT_NOT_TODAYS_SCHEDULED_RUN":
                    raise
            else:
                if args.mode == "preview":
                    print("WECOM_MARKET_PREVIEW_ONLY_NO_SEND")
                    print(format_message(receipt, info, target))
                    return 0
                if not args.approve_self_send:
                    raise UnsafeReport("SEND_NOT_APPROVED")
                # All local checks BEFORE reservation; transport cannot be retried after intent.
                message = format_message(receipt, info, target)
                if not SERVER_PATTERN.fullmatch(args.server) or args.remote != DEFAULT_REMOTE:
                    raise UnsafeReport("SSH_TARGET_OR_REMOTE_NOT_PINNED")
                if not Path(args.ssh_key).is_file():
                    raise UnsafeReport("SSH_KEY_MISSING")
                reserve_once(Path(args.intent_dir), target, digest)
                print("WECOM_MARKET_LOCAL_INTENT_RESERVED", flush=True)
                exit_code, statuses = dispatch(args.server, Path(args.ssh_key),
                                                message, target, digest, args.remote)
                for status in statuses:
                    print(status, flush=True)
                print("WECOM_MARKET_SSH_EXIT=" + str(exit_code), flush=True)
                return 0 if exit_code == 0 and "WECOM_MARKET_API_ACK_NOT_DEVICE_PROOF" in statuses else 4
        if args.mode != "watch":
            raise UnsafeReport("TASK_NOT_READY_OR_RECEIPT_MISSING")
        time.sleep(30)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("preview", "once", "watch"), default="preview")
    p.add_argument("--receipt", default=str(Path(__file__).resolve().parent / "work" / "last-afternoon-unified.json"))
    p.add_argument("--intent-dir", default=str(Path(__file__).resolve().parent / "work" / "wecom-report-once"))
    p.add_argument("--date", help="China calendar date YYYY-MM-DD; defaults to today")
    p.add_argument("--server", default="ubuntu@43.142.32.208")
    p.add_argument("--ssh-key", default=str(Path.home() / ".ssh" / "astock-market-wecom-only"))
    p.add_argument("--remote", default=DEFAULT_REMOTE)
    p.add_argument("--approve-self-send", action="store_true")
    a = p.parse_args(argv)
    if a.date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.date):
        p.error("Bad --date")
    try:
        return run(a)
    except FileExistsError:
        print("WECOM_MARKET_ALREADY_ATTEMPTED_NO_RETRY", flush=True)
        return 5
    except (UnsafeReport, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        # Don't display untrusted exception text from subprocess or receipts.
        if isinstance(exc, UnsafeReport):
            print("WECOM_MARKET_" + str(exc), flush=True)
        else:
            print("WECOM_MARKET_LOCAL_PREFLIGHT_FAILED_NO_SEND", flush=True)
        return 3


if __name__ == "__main__":
    sys.exit(main())
