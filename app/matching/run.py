"""매칭 파이프라인: 사용자별 미채점 공고 → prefilter → 채점 → Match 저장."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.config import get_settings
from app.db import Announcement, Match, User, session
from app.matching.prefilter import prefilter
from app.matching.scorer import get_scorer


def run_matching(today: date | None = None, scorer=None) -> dict:
    s = get_settings()
    scorer = scorer or get_scorer()
    today = today or date.today()
    report = {"users": 0, "scored": 0, "skipped_by_cap": 0}

    with session() as db:
        users = db.scalars(select(User).where(User.confirmed.is_(True), User.active.is_(True))).all()
        for u in users:
            report["users"] += 1
            done_ids = {m.announcement_id for m in u.matches}
            candidates = db.scalars(select(Announcement).where(
                (Announcement.apply_end.is_(None)) | (Announcement.apply_end >= today))).all()
            candidates = [a for a in candidates if a.id not in done_ids]
            candidates = prefilter(u, candidates, today)

            cap = s.max_llm_candidates_per_user
            if len(candidates) > cap:
                report["skipped_by_cap"] += len(candidates) - cap
                candidates = candidates[:cap]

            for a in candidates:
                sc = scorer.score(u, a)
                db.add(Match(
                    user_id=u.id, announcement_id=a.id, score=sc.score, eligible=sc.eligible,
                    one_liner=sc.one_liner, reasons="\n".join(sc.reasons),
                ))
                report["scored"] += 1
            db.commit()
    return report
