"""이메일 전송 백엔드. EMAIL_BACKEND 환경변수로 선택."""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from app.config import get_settings


class ConsoleBackend:
    """개발용: 메일을 보내지 않고 stdout 에 찍는다. 마지막 메일은 .last 에 보관 (테스트용)."""
    last: dict | None = None

    def send(self, to: str, subject: str, html: str, text: str = "") -> None:
        ConsoleBackend.last = {"to": to, "subject": subject, "html": html, "text": text}
        print(f"\n=== [console email] to={to}\nsubject={subject}\n{text or '(html only)'}\n=== end\n")


class ResendBackend:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or get_settings().resend_api_key

    def send(self, to: str, subject: str, html: str, text: str = "") -> None:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"from": get_settings().email_from, "to": [to], "subject": subject, "html": html, "text": text or None},
            timeout=20,
        )
        r.raise_for_status()


class SMTPBackend:
    def send(self, to: str, subject: str, html: str, text: str = "") -> None:
        s = get_settings()
        msg = MIMEMultipart("alternative")
        msg["Subject"], msg["From"], msg["To"] = subject, s.email_from, to
        if text:
            msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP(s.smtp_host, s.smtp_port) as srv:
            srv.starttls()
            if s.smtp_user:
                srv.login(s.smtp_user, s.smtp_password)
            srv.sendmail(s.email_from, [to], msg.as_string())


def get_backend():
    b = get_settings().email_backend
    return {"console": ConsoleBackend, "resend": ResendBackend, "smtp": SMTPBackend}[b]()
