#!/usr/bin/env python3
"""Ubuntu owner-only WeCom self-report sender. No news/QQ/Weixin DB access.

No retries. One date -> one durable intent -> at most one provider POST.
The provider ACK is not proof that a phone displayed the message.
"""
import json
from datetime import date as Date, datetime, timedelta, timezone
import os
from pathlib import Path
import re
import ssl
import stat
import sys
import urllib.parse
import urllib.request

ROOT = Path('/home/ubuntu/.local/state/tecent-intelligence')
CONFIG = ROOT / 'wecom-app-v1' / 'owner-private.json'
OUTBOX = ROOT / 'astock-market-report-once-v1'
CHINA = timezone(timedelta(hours=8))


def now_china():
    return datetime.now(CHINA)


class Refused(Exception):
    pass


def secure_file(path, mode=0o600):
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_nlink != 1 or s.st_mode & 0o077:
        raise Refused('UNTRUSTED_PRIVATE_FILE')


def secure_directory(path):
    s = path.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
        raise Refused('UNTRUSTED_PRIVATE_DIRECTORY')


def load_config():
    if os.geteuid() == 0 or Path.home() != Path('/home/ubuntu'):
        raise Refused('NOT_UBUNTU_OWNER')
    secure_directory(ROOT)
    secure_directory(CONFIG.parent)
    secure_file(CONFIG)
    cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
    if cfg.get('member_is_active_in_app') is not True or cfg.get('wechat_plugin_opted_in') is not True:
        raise Refused('MEMBER_NOT_APPROVED')
    for key in ('corp_id', 'secret', 'member_userid'):
        if not isinstance(cfg.get(key), str) or not cfg[key].strip():
            raise Refused('BAD_CONFIG')
    if type(cfg.get('agent_id')) is not int or cfg['agent_id'] <= 0:
        raise Refused('BAD_AGENT')
    return cfg


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    NoRedirect())


def api(path, token=None, payload=None):
    if path not in ('gettoken', 'agent/get', 'message/send'):
        raise Refused('UNAPPROVED_API_PATH')
    params = token or {}
    url = 'https://qyapi.weixin.qq.com/cgi-bin/' + path + '?' + urllib.parse.urlencode(params)
    data = None if payload is None else json.dumps(payload, ensure_ascii=False,
                                                    separators=(',', ':')).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json; charset=utf-8'}
                                 if data is not None else {}, method='POST' if data is not None else 'GET')
    with OPENER.open(req, timeout=12) as response:
        if response.status != 200:
            raise Refused('PROVIDER_HTTP_ERROR')
        raw = response.read(8193)
    if len(raw) > 8192:
        raise Refused('PROVIDER_RESPONSE_TOO_LARGE')
    return json.loads(raw.decode('utf-8'))


def preflight(cfg):
    token_reply = api('gettoken', {'corpid': cfg['corp_id'], 'corpsecret': cfg['secret']})
    if token_reply.get('errcode') != 0 or not token_reply.get('access_token'):
        raise Refused('WECOM_AUTH_FAILED')
    token = token_reply['access_token']
    profile = api('agent/get', {'access_token': token, 'agentid': cfg['agent_id']})
    members = profile.get('allow_userinfos', {}).get('user', [])
    if (profile.get('errcode') != 0 or profile.get('agentid') != cfg['agent_id']
            or profile.get('close') != 0 or not isinstance(members, list)
            or not any(isinstance(x, dict) and isinstance(x.get('userid'), str)
                       and x['userid'].casefold() == cfg['member_userid'].casefold() for x in members)):
        raise Refused('MEMBER_SCOPE_UNVERIFIED')
    return token


def validate_request(doc):
    if not isinstance(doc, dict) or set(doc) != {'date', 'receipt_sha256', 'text'}:
        raise Refused('BAD_REQUEST_SHAPE')
    date, sha, message = doc['date'], doc['receipt_sha256'], doc['text']
    if not isinstance(date, str) or not re.fullmatch(r'20\d{2}-\d\d-\d\d', date):
        raise Refused('BAD_DATE')
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
        raise Refused('BAD_RECEIPT_HASH')
    try:
        real_date = Date.fromisoformat(date)
    except ValueError as exc:
        raise Refused('BAD_DATE') from exc
    now = now_china()
    day_ok = (real_date == now.date() and (now.hour, now.minute) >= (20, 5))
    rollover_ok = (real_date == now.date() - timedelta(days=1) and now.hour < 4)
    if not (day_ok or rollover_ok):
        raise Refused('OUTSIDE_RUN_DATE_WINDOW')
    if not isinstance(message, str) or not 10 <= len(message.encode('utf-8')) <= 2048:
        raise Refused('BAD_MESSAGE_LENGTH')
    if not message.startswith('【A股每日更新详情｜' + date + '】'):
        raise Refused('MESSAGE_DATE_MISMATCH')
    return date, sha, message


def write_result(path, result):
    tmp = path.with_suffix('.tmp')
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        json.dump(result, out, ensure_ascii=False)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)


def send_once(req):
    date, sha, message = validate_request(req)
    cfg = load_config()
    # Authentication/recipient-scope check does not send a message.
    token = preflight(cfg)
    try:
        OUTBOX.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        raise Refused('OUTBOX_UNAVAILABLE') from exc
    secure_directory(OUTBOX)
    marker = OUTBOX / (date + '.json')
    fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        json.dump({'date': date, 'receipt_sha256': sha, 'status': 'UNKNOWN_NO_RETRY'}, out)
        out.flush()
        os.fsync(out.fileno())
    status = 'UNKNOWN_NO_RETRY'
    code = None
    try:
        reply = api('message/send', {'access_token': token}, {
            'touser': cfg['member_userid'], 'msgtype': 'text', 'agentid': cfg['agent_id'],
            'text': {'content': message}, 'safe': 0})
        code = reply.get('errcode')
        if type(code) is int and code == 0 and all(
                reply.get(k) in (None, '', [])
                for k in ('invaliduser', 'invalidparty', 'invalidtag', 'unlicenseduser')):
            status = 'API_ACK_NOT_DEVICE_PROOF'
        elif type(code) is int:
            status = 'PROVIDER_REJECTED_OR_PARTIAL'
    except Exception:
        pass  # Treat all provider transport exceptions as UNKNOWN, without retry.
    try:
        write_result(marker, {'date': date, 'receipt_sha256': sha,
                              'status': status, 'provider_error_code': code if type(code) is int else None})
    except Exception:
        raise Refused('RECEIPT_WRITE_UNKNOWN_NO_RETRY')
    print('WECOM_MARKET_' + status, flush=True)
    if type(code) is int:
        print('WECOM_MARKET_PROVIDER_CODE=' + str(code), flush=True)
    return 0 if status == 'API_ACK_NOT_DEVICE_PROOF' else 4


def main():
    try:
        data = sys.stdin.buffer.read(8193)
        if len(data) > 8192:
            raise Refused('REQUEST_TOO_LARGE')
        doc = json.loads(data.decode('utf-8'))
        if doc == {'mode': 'preflight'}:
            load_config()
            print('WECOM_MARKET_PREFLIGHT_OK', flush=True)
            return 0
        return send_once(doc)
    except FileExistsError:
        print('WECOM_MARKET_ALREADY_ATTEMPTED_NO_RETRY', flush=True)
        return 5
    except (Refused, ValueError, KeyError, OSError) as exc:
        print('WECOM_MARKET_' + str(exc) if isinstance(exc, Refused)
              else 'WECOM_MARKET_LOCAL_PREFLIGHT_FAILED_NO_SEND', flush=True)
        return 3


if __name__ == '__main__':
    sys.exit(main())
