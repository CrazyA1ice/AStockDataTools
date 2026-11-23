#!/usr/bin/env python3
"""Durable, numbered WeCom completion messages; no Windows toast or popup.

Default is dry-run or NOT_CONFIGURED, never an implicit external send.
Credentials belong ONLY in the ignored local qmt_extra work directory.
Provider ACK means accepted by API, never guaranteed handset delivery.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit, parse_qs, urlencode
from urllib.request import Request, urlopen

FORMAT = "market_update_wecom_push_v1"
MAX_RECEIPT = 2 * 1024 * 1024
MAX_CONFIG = 16 * 1024
MAX_PART_BYTES = 1500
NAMES = {
    "EIGHT_PERIODS": "八周期K线",
    "SECTORS": "板块",
    "ADJUSTMENTS_ROTATING": "除权数据",
    "FINANCIAL_DAILY": "QMT财务",
}
STAGES = tuple(NAMES)


class PushBlocked(RuntimeError):
    pass


def _read_json(path: Path, bound: int) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > bound:
        raise PushBlocked("INVALID_PRIVATE_PUSH_INPUT")
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if type(obj) is not dict:
        raise PushBlocked("INVALID_PUSH_DOCUMENT")
    return obj


def _checked_config(path: Path) -> dict:
    cfg = _read_json(path, MAX_CONFIG)
    kind = cfg.get("provider")
    if kind == "wecom_app":
        if (set(cfg) != {"provider", "corp_id", "corp_secret",
                         "agent_id", "to_user"} or
                any(type(cfg[key]) is not str or not cfg[key] or
                    len(cfg[key]) > 256 for key in
                    ("corp_id", "corp_secret", "to_user")) or
                type(cfg["agent_id"]) is not int or
                not 1 <= cfg["agent_id"] <= 2147483647):
            raise PushBlocked("INVALID_WECOM_APP_CONFIG")
    elif kind == "wecom_webhook":
        if set(cfg) != {"provider", "webhook_url"}:
            raise PushBlocked("INVALID_WECOM_WEBHOOK_CONFIG")
        url = cfg.get("webhook_url")
        if type(url) is not str or len(url) > 1024:
            raise PushBlocked("INVALID_WECOM_WEBHOOK_URL")
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        if (parsed.scheme != "https" or
                parsed.hostname != "qyapi.weixin.qq.com" or
                parsed.port is not None or parsed.username is not None or
                parsed.password is not None or
                parsed.path != "/cgi-bin/webhook/send" or
                set(query) != {"key"} or len(query["key"]) != 1 or
                not query["key"][0] or parsed.fragment):
            raise PushBlocked("INVALID_WECOM_WEBHOOK_URL")
    else:
        raise PushBlocked("UNSUPPORTED_PUSH_PROVIDER")
    return cfg


def _report_text(run: dict) -> str:
    started = str(run.get("china_start") or run.get("started_local") or "未知")
    outcome = str(run.get("status") or "UNKNOWN")
    lines = [
        "A股每日数据更新报告",
        "状态：" + {"SUCCESS": "已执行完成", "PARTIAL": "部分完成",
                   "FAILED": "失败"}.get(outcome, outcome),
        "中国时间启动：" + started,
        "结束：" + str(run.get("finished_local") or "未记录"),
        "执行顺序：K线 → 板块 → 除权 → 财务",
    ]
    records = run.get("stage_records")
    if type(records) is not dict:
        records = {}
    completed = run.get("steps_completed")
    completed = completed if type(completed) is list else []
    verification = run.get("validation")
    sections = (verification.get("sections") if type(verification) is dict else None)
    sections = sections if type(sections) is dict else {}
    for stage in STAGES:
        rec = records.get(stage)
        rec = rec if type(rec) is dict else {}
        if rec.get("status") == "DEFERRED_CUTOFF":
            state = "顺延下次（晚间截止）"
        elif rec.get("exit_code") == 0 and stage in completed:
            state = "运行完成"
        elif stage in completed:
            state = "已运行（状态待核实）"
        elif rec.get("exit_code") is not None:
            state = "运行失败"
        else:
            state = "未运行"
        item = sections.get(stage)
        item = item if type(item) is dict else {}
        lines.append(NAMES[stage] + "：" + state)
        if item:
            lines.append("  质量：" + str(item.get("data_validation", "UNVERIFIED")) +
                         "；跨源：" + str(item.get("cross_validation", "UNVERIFIED")))
            if item.get("detail"):
                lines.append("  说明：" + str(item["detail"]))
    if type(verification) is dict:
        lines.append("校验总览：" +
                     str(verification.get("data_validation", "UNVERIFIED")) +
                     "；跨源：" +
                     str(verification.get("cross_validation", "UNVERIFIED")))
    errors = run.get("errors")
    if type(errors) is list:
        for e in errors:
            lines.append("异常：" + str(e))
    if run.get("finance_deferred_by_cutoff"):
        lines.append("财务顺延：当天剩余时间不足，本轮未启动财务下载；保留游标。")
    lines.extend([
        "注意：阶段成功不等于完整历史覆盖或独立来源认证。",
        "完整日志及逐笔回执保留在本机 ParquetLiveSync/work。",
    ])
    return "\n".join(lines)


def _chunks(report: str) -> list[str]:
    """UTF-8 byte budget, never truncate Chinese multi-byte characters."""
    pieces, current = [], ""
    for ch in report:
        if len((current + ch).encode("utf-8")) > MAX_PART_BYTES:
            if not current:
                raise PushBlocked("SINGLE_CHARACTER_EXCEEDS_MESSAGE_BUDGET")
            pieces.append(current)
            current = ch
        else:
            current += ch
    if current:
        pieces.append(current)
    return [f"【A股更新 {i}/{len(pieces)}】\n{piece}"
            for i, piece in enumerate(pieces, 1)]


def _http_json(url: str, *, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(
        url, data=data,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "User-Agent": "AStockDataTools-update-receipt/1.0"},
        method="POST" if data is not None else "GET")
    with urlopen(request, timeout=12) as response:
        if response.status != 200:
            raise PushBlocked("WECOM_HTTP_NOT_200")
        raw = response.read(16385)
    if len(raw) > 16384:
        raise PushBlocked("WECOM_RESPONSE_TOO_LARGE")
    res = json.loads(raw.decode("utf-8"))
    if type(res) is not dict or type(res.get("errcode")) is not int:
        raise PushBlocked("WECOM_RESPONSE_INVALID")
    return res


def _send_one(cfg: dict, message: str) -> None:
    kind = cfg["provider"]
    if kind == "wecom_app":
        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken?" + urlencode({
            "corpid": cfg["corp_id"], "corpsecret": cfg["corp_secret"]})
        token = _http_json(url)
        if token["errcode"] != 0 or not token.get("access_token"):
            raise PushBlocked("WECOM_ACCESS_TOKEN_REJECTED")
        send_url = "https://qyapi.weixin.qq.com/cgi-bin/message/send?" + urlencode({
            "access_token": token["access_token"]})
        body = {"touser": cfg["to_user"], "agentid": cfg["agent_id"],
                "msgtype": "text", "text": {"content": message},
                "safe": 0, "enable_duplicate_check": 1,
                "duplicate_check_interval": 1800}
    else:
        send_url = cfg["webhook_url"]
        body = {"msgtype": "text", "text": {"content": message}}
    res = _http_json(send_url, payload=body)
    if res["errcode"] != 0:
        raise PushBlocked("WECOM_PROVIDER_MESSAGE_REJECTED")
    if kind == "wecom_app" and (
            res.get("invaliduser") or res.get("unlicenseduser")):
        raise PushBlocked("WECOM_APP_RECIPIENT_NOT_ACCEPTED")


def _atomic_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(".part")
    if tmp.exists() or tmp.is_symlink() or path.is_symlink():
        raise PushBlocked("OUTBOX_PARTIAL_OR_LINKED_FILE")
    with tmp.open("x", encoding="utf-8") as stream:
        json.dump(obj, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def dispatch(receipt: Path, private_config: Path, outbox: Path, *,
             dry_run=False, expected_start="", transport=_send_one) -> dict:
    doc = _read_json(receipt, MAX_RECEIPT)
    if doc.get("format") != "qmt_daily_single_trigger_v3":
        raise PushBlocked("WRONG_MARKET_COMPLETION_RECEIPT")
    if expected_start and doc.get("started_local") != expected_start:
        raise PushBlocked("STALE_MARKET_COMPLETION_RECEIPT")
    text = _report_text(doc)
    chunks = _chunks(text)
    if any(len(part.encode("utf-8")) > 1700 for part in chunks):
        raise PushBlocked("WECOM_TEXT_BYTES_EXCEED_SAFE_LIMIT")
    key = hashlib.sha256(
        (str(doc.get("started_local")) + "\n" + text).encode("utf-8")).hexdigest()[:24]
    result = {"run_id": key, "parts": len(chunks),
              "provider_ack_not_device_delivery": True}
    if dry_run:
        return {**result, "status": "DRY_RUN_NO_EXTERNAL_SEND",
                "text": text, "max_bytes": max(map(lambda x: len(x.encode("utf-8")), chunks))}
    outbox.mkdir(parents=True, exist_ok=True)
    if outbox.is_symlink():
        raise PushBlocked("LINKED_NOTIFICATION_OUTBOX")
    file = outbox / (key + ".json")
    if file.exists():
        existing = _read_json(file, MAX_RECEIPT)
        if (existing.get("format") != FORMAT or
                existing.get("text_sha256") !=
                hashlib.sha256(text.encode("utf-8")).hexdigest() or
                len(existing.get("parts", [])) != len(chunks)):
            raise PushBlocked("OUTBOX_ID_COLLISION")
        state = existing
    else:
        state = {"format": FORMAT, "run_id": key,
                 "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                 "parts": ["PENDING"] * len(chunks),
                 "created_utc": datetime.now(timezone.utc).isoformat()}
        _atomic_json(file, state)
    if all(part == "API_ACK" for part in state["parts"]):
        return {**result, "status": "ALREADY_ACKED"}
    # Never automatically resend an uncertain send: the provider may have
    # accepted it before a client crash / timeout. Keep the durable record.
    if any(part in ("ATTEMPTING", "UNKNOWN") for part in state["parts"]):
        raise PushBlocked("PRIOR_DELIVERY_UNCERTAIN_MANUAL_REVIEW")
    if not private_config.is_file():
        return {**result, "status": "NOT_CONFIGURED_LOCAL_RECEIPT_RETAINED"}
    cfg = _checked_config(private_config)
    for i, part in enumerate(chunks):
        if state["parts"][i] == "API_ACK":
            continue
        state["parts"][i] = "ATTEMPTING"
        _atomic_json(file, state)
        try:
            transport(cfg, part)
        except Exception as exc:
            state["parts"][i] = "UNKNOWN"
            _atomic_json(file, state)
            raise PushBlocked("WECOM_SEND_NOT_CONFIRMED") from exc
        state["parts"][i] = "API_ACK"
        _atomic_json(file, state)
    return {**result, "status": "ALL_PARTS_API_ACK"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--outbox", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-config", action="store_true")
    parser.add_argument("--expected-start-local", default="")
    args = parser.parse_args(argv)
    if args.validate_config:
        try:
            cfg = _checked_config(args.config)
        except Exception:
            print("MARKET_PUSH_CONFIG_INVALID=TRUE")
            return 2
        print("MARKET_PUSH_CONFIG_VALID=" + cfg["provider"])
        return 0
    if args.receipt is None or args.outbox is None:
        parser.error("--receipt and --outbox required to dispatch")
    try:
        result = dispatch(args.receipt, args.config, args.outbox,
                          dry_run=args.dry_run,
                          expected_start=args.expected_start_local)
    except Exception as exc:
        # Never print sensitive urllib errors: they can contain credentials
        # in the token URL. Fixed error type only.
        print("MARKET_PUSH_RESULT=" + json.dumps({
            "status": "NOT_CONFIRMED",
            "error_type": type(exc).__name__,
        }, ensure_ascii=False))
        return 2
    result.pop("text", None)
    print("MARKET_PUSH_RESULT=" + json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] in (
        "DRY_RUN_NO_EXTERNAL_SEND", "ALL_PARTS_API_ACK",
        "ALREADY_ACKED") else 2


if __name__ == "__main__":
    raise SystemExit(main())
