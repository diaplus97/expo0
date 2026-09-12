"""LLM에 보내기 전 규칙 필터. 목적은 정확도가 아니라 '명백히 아닌 것' 제거."""
from __future__ import annotations

from datetime import date

from app.db import Announcement, User


def region_ok(user_region: str, ann_region: str) -> bool:
    return user_region == "전국" or ann_region == "전국" or user_region == ann_region


def deadline_ok(ann: Announcement, today: date | None = None, min_days: int = 1) -> bool:
    """마감이 지났거나 오늘 마감(신청 준비 불가)인 건 제외. 마감 미상은 통과."""
    d = ann.days_left(today)
    return d is None or d >= min_days


def stage_ok(user: User, ann: Announcement) -> bool:
    """예비창업자에게 '업력 N년 이상' 공고를, 운영중 사업자에게 '예비창업자 전용' 공고를 보내지 않는다."""
    text = (ann.title + " " + ann.target + " " + ann.body)
    if user.stage == "예비창업":
        return not any(k in text for k in ["업력 3년", "업력 5년", "3년 이상", "5년 이상", "7년 이상"])
    return "예비창업자 전용" not in text and "예비창업자만" not in text


def keyword_hits(user: User, ann: Announcement) -> int:
    kws = [k.strip() for k in user.keywords.split(",") if k.strip()]
    text = (ann.title + " " + ann.target + " " + ann.body + " " + ann.category)
    return sum(1 for k in kws if k in text)


def prefilter(user: User, anns: list[Announcement], today: date | None = None) -> list[Announcement]:
    out = []
    for a in anns:
        if not region_ok(user.region, a.region):
            continue
        if not deadline_ok(a, today):
            continue
        if not stage_ok(user, a):
            continue
        out.append(a)
    # 키워드 적중 많은 순 → 마감 임박 순. LLM 상한에 걸릴 때 좋은 후보가 먼저 채점되게.
    out.sort(key=lambda a: (-keyword_hits(user, a), a.days_left(today) if a.days_left(today) is not None else 9999))
    return out
