#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云端版：检查到点的提醒并发送。跑在 GitHub Actions 上，不依赖本地电脑。

环境变量（仓库 Secrets）：
  MAIL_TO / MAIL_FROM / QQ_AUTH_CODE / REMINDERS_JSON

关键设计 —— 「补发，不丢」：
  GitHub 的 cron 会被降频，实际可能几小时才跑一次，所以不能用
  「只看最近 N 分钟」的窗口判断。这里改成：
    只要 due <= 现在、而且没发过 -> 就发。
  已发记录存在仓库根目录的 sent.json 里（只存哈希，不含标题正文，
  所以公开仓库也不会泄露内容）。一次都没跑成也不会丢，只会迟到。
"""
import datetime as dt
import hashlib
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formataddr, formatdate

STATE = "sent.json"
REPEAT_CATCHUP_HOURS = 6       # 重复型提醒最多往回补 6 小时（避免刚建好就补发昨天那次）
TZ_OFFSET = int(os.environ.get("TZ_OFFSET_HOURS", "8"))


def now_local():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=TZ_OFFSET)


def key_of(subject, occ):
    return hashlib.sha1(("%s|%s" % (subject, occ.strftime("%Y-%m-%d %H:%M"))).encode("utf-8")).hexdigest()[:16]


def load_state():
    if os.path.exists(STATE):
        try:
            return set(json.load(open(STATE, encoding="utf-8")))
        except Exception:
            pass
    return set()


def save_state(s):
    json.dump(sorted(s), open(STATE, "w", encoding="utf-8"), indent=0)


def send(subject, body):
    to = os.environ["MAIL_TO"]
    user = os.environ["MAIL_FROM"]
    pw = os.environ["QQ_AUTH_CODE"]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("蓝色大肥鱼", user))
    msg["To"] = to
    msg["Date"] = formatdate(localtime=False)
    msg.set_content(body, charset="utf-8")

    with smtplib.SMTP_SSL("smtp.qq.com", 465,
                          context=ssl.create_default_context(), timeout=30) as s:
        s.login(user, pw)
        s.send_message(msg)

    stamp = now_local().strftime("%Y-%m-%d %H:%M:%S")
    print("SENT -> %s | %s" % (to, subject))
    try:
        with open("sent.log", "a", encoding="utf-8") as f:
            f.write("%s  已发送 [cloud] -> %s | %s\n" % (stamp, to, subject))
    except OSError:
        pass


def fires_on(base, day, repeat):
    if day < base.date():
        return False
    repeat = (repeat or "none").lower()
    if repeat == "daily":
        return True
    if repeat == "weekdays":
        return day.weekday() < 5
    if repeat == "weekly":
        return day.weekday() == base.weekday()
    return day == base.date()


def occurrences(base, repeat, now):
    """列出这条提醒在 [base, now] 之间应该触发的时刻。
    重复型只取最近一次，避免补发风暴。"""
    repeat = (repeat or "none").lower()
    if repeat == "none":
        return [base] if base <= now else []
    out = []
    day = base.date()
    limit = (now - dt.timedelta(hours=REPEAT_CATCHUP_HOURS)).date()
    if day < limit:
        day = limit
    while day <= now.date():
        if fires_on(base, day, repeat):
            occ = base.replace(year=day.year, month=day.month, day=day.day)
            if base <= occ <= now:
                out.append(occ)
        day += dt.timedelta(days=1)
    return out[-1:]          # 只补最近一次


def main():
    raw = os.environ.get("REMINDERS_JSON", "").strip()
    if not raw:
        print("REMINDERS_JSON 为空，无事可做")
        return 0

    items = json.loads(raw)
    now = now_local()
    state = load_state()
    print("现在 %s（时区 +%d），共 %d 条提醒，已发记录 %d 条"
          % (now.strftime("%Y-%m-%d %H:%M"), TZ_OFFSET, len(items), len(state)))

    sent = 0
    for r in items:
        if not r.get("enabled", True):
            continue
        try:
            base = dt.datetime.strptime(r["due"], "%Y-%m-%d %H:%M")
        except Exception as e:
            print("跳过格式不对的提醒：%s (%s)" % (r.get("subject"), e))
            continue
        for occ in occurrences(base, r.get("repeat"), now):
            k = key_of(r["subject"], occ)
            if k in state:
                continue
            try:
                send(r["subject"], r["body"])
            except Exception as e:
                print("发送失败：%s -> %s" % (r.get("subject"), e))
                save_state(state)
                return 1
            state.add(k)
            save_state(state)
            sent += 1

    print("本次共发出 %d 封" % sent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
