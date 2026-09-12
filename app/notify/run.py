"""다이제스트 발송: 미발송 매칭을 모아 요금제 규칙대로 잘라 보낸다."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select

from app.config import get_settings
from app.db import Match, User, session
from app.notify.email import get_backend

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def is_due(user: User, today: date) -> bool:
    """free=주간(월요일), pro=설정대로. 첫 발송은 즉시."""
    freq = user.frequency if user.plan == "pro" else "weekly"
    if user.last_sent_at is None:
        return True
    if freq == "daily":
        return user.last_sent_at.date() < today
    return today.weekday() == 0 and user.last_sent_at.date() < today


def render_digest(user: User, matches: list[Match], hidden_count: int, today: date) -> tuple[str, str, str]:
    """(subject, html, text)"""
    s = get_settings()
    is_pro = user.plan == "pro"
    n = len(matches)
    subject = f"[{s.app_name}] 신청할 만한 지원사업 {n}건" + (f" (마감 임박 {sum(1 for m in matches if (m.announcement.days_left(today) or 99) <= 7)}건)" if n else "")
    html = _env.get_template("digest.html").render(
        app_name=s.app_name,
        heading=f"{user.region} · {user.biz_type or '사업자'}님께 맞는 공고 {n}건",
        subheading=today.strftime("%Y년 %m월 %d일 기준") + (" · 매일 발송" if is_pro and user.frequency == "daily" else " · 주 1회 발송"),
        items=[{"ann": m.announcement, "score": m.score, "one_liner": m.one_liner, "reasons": m.reasons} for m in matches],
        show_reasons=is_pro,
        upsell=(not is_pro) and hidden_count > 0,
        hidden_count=hidden_count,
        upgrade_url=f"{s.base_url}/u/{user.token}#pro",
        pro_price=f"{s.pro_price_krw:,}",
        settings_url=f"{s.base_url}/u/{user.token}",
        unsubscribe_url=f"{s.base_url}/u/{user.token}/unsubscribe",
        today=today,
    )
    lines = [f"{s.app_name} — 맞는 공고 {n}건 ({today.isoformat()})", ""]
    for m in matches:
        d = m.announcement.days_left(today)
        lines.append(f"- [{'D-'+str(d) if d is not None else '상시'}] {m.announcement.title} ({m.announcement.agency}) 적합도 {m.score}")
        if m.one_liner:
            lines.append(f"  {m.one_liner}")
        lines.append(f"  {m.announcement.url}")
    lines += ["", f"알림 조건 바꾸기: {s.base_url}/u/{user.token}", f"수신 거부: {s.base_url}/u/{user.token}/unsubscribe"]
    return subject, html, "\n".join(lines)


def run_notify(today: date | None = None, backend=None) -> dict:
    s = get_settings()
    backend = backend or get_backend()
    today = today or date.today()
    report = {"sent": 0, "skipped_not_due": 0, "skipped_empty": 0}

    with session() as db:
        users = db.scalars(select(User).where(User.confirmed.is_(True), User.active.is_(True))).all()
        for u in users:
            if not is_due(u, today):
                report["skipped_not_due"] += 1
                continue
            pending = db.scalars(select(Match).where(
                Match.user_id == u.id, Match.sent_at.is_(None), Match.score >= s.min_score_to_notify)).all()
            pending = [m for m in pending if m.announcement.days_left(today) is None or m.announcement.days_left(today) >= 0]
            pending.sort(key=lambda m: (-m.score, m.announcement.days_left(today) if m.announcement.days_left(today) is not None else 9999))
            if not pending:
                report["skipped_empty"] += 1
                continue

            if u.plan == "pro":
                to_send, hidden = pending, 0
            else:
                to_send, hidden = pending[: s.free_max_items_per_digest], max(0, len(pending) - s.free_max_items_per_digest)

            subject, html, text = render_digest(u, to_send, hidden, today)
            backend.send(u.email, subject, html, text)
            now = datetime.now(timezone.utc)
            for m in to_send:
                m.sent_at = now
            # 무료 사용자에게 숨긴 항목도 '이번 주치'로 소진 처리 (다음 주에 오래된 걸 다시 보여주지 않게)
            for m in pending[len(to_send):]:
                m.sent_at = now
            u.last_sent_at = now
            db.commit()
            report["sent"] += 1
    return report
