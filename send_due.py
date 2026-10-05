#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云端版：检查到点的提醒并发送。
在 GitHub Actions 里跑，完全不依赖本地电脑。

环境变量（都放在仓库 Secrets 里）：
  MAIL_TO        收件人，如 2046466062@qq.com
  MAIL_FROM      发件人，等于 QQ 邮箱地址
  QQ_AUTH_CODE   QQ 邮箱 16 位授权码
  REMINDERS_JSON 提醒清单（JSON 数组）

清单里每条：
  { "subject": "...", "body": "...", "due": "2026-10-06 07:30", "repeat": "none" }

去重靠「时间窗口」：只发 due 落在 [now-WINDOW, now] 区间内的，
所以不需要往仓库里写状态文件。
"""
import datetime as dt
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formataddr, formatdate

WINDOW_MIN = int(os.environ.get("WINDOW_MIN", "7"))  # 容忍 cron 延迟
TZ_OFFSET = int(os.environ.get("TZ_OFFSET_HOURS", "8"))  # Asia/Shanghai


def now_local():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=TZ_OFFSET)


def fires_on(base, day, repeat):
    """base 是提醒的首次时间；判断 day（同一天的日期）是否该触发。"""
    if day < base.date():
        return False
    repeat = (repeat or "none").lower()
    if repeat == "none":
        return day == base.date()
    if repeat == "daily":
        return True
    if repeat == "weekdays":
        return day.weekday() < 5
    if repeat == "weekly":
        return day.weekday() == base.weekday()
    return day == base.date()


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
    print("SENT -> %s | %s" % (to, subject))


def main():
    raw = os.environ.get("REMINDERS_JSON", "").strip()
    if not raw:
        print("REMINDERS_JSON 为空，无事可做")
        return 0

    items = json.loads(raw)
    now = now_local()
    lo = now - dt.timedelta(minutes=WINDOW_MIN)
    print("当前时间 %s，窗口 %s ~ %s，共 %d 条提醒"
          % (now.strftime("%Y-%m-%d %H:%M"), lo.strftime("%H:%M"),
             now.strftime("%H:%M"), len(items)))

    hit = 0
    for r in items:
        if not r.get("enabled", True):
            continue
        try:
            base = dt.datetime.strptime(r["due"], "%Y-%m-%d %H:%M")
        except Exception as e:
            print("跳过格式不对的提醒：%s (%s)" % (r.get("subject"), e))
            continue
        # 把重复规则展开成"今天这一次"的绝对时间
        cands = []
        for day in {lo.date(), now.date()}:
            if fires_on(base, day, r.get("repeat")):
                cands.append(day)
        if not cands:
            continue
        fired = False
        for day in sorted(cands):
            occ = base.replace(year=day.year, month=day.month, day=day.day)
            if lo <= occ <= now:
                fired = True
        if not fired:
            continue
        try:
            send(r["subject"], r["body"])
            hit += 1
        except Exception as e:
            print("发送失败：%s -> %s" % (r.get("subject"), e))
            return 1

    if hit == 0:
        print("本窗口内没有到点的提醒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
