"""SQLAlchemy 모델과 세션. SQLite로 시작하고, 규모가 커지면 DATABASE_URL만 Postgres로 바꾼다."""
from __future__ import annotations

import secrets
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)          # 수신거부 시 False
    token: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: secrets.token_urlsafe(32))
    plan: Mapped[str] = mapped_column(String(16), default="free")        # free | pro
    frequency: Mapped[str] = mapped_column(String(16), default="weekly") # daily | weekly (free는 weekly 고정)

    # 사업 프로필 — 매칭 입력값
    region: Mapped[str] = mapped_column(String(32), default="전국")      # 시/도 단위
    biz_type: Mapped[str] = mapped_column(String(200), default="")       # 업종 (자유 서술)
    keywords: Mapped[str] = mapped_column(String(400), default="")       # 콤마 구분
    stage: Mapped[str] = mapped_column(String(16), default="운영중")      # 예비창업 | 운영중
    employees: Mapped[int] = mapped_column(Integer, default=1)
    years: Mapped[int] = mapped_column(Integer, default=0)               # 업력(년)
    note: Mapped[str] = mapped_column(Text, default="")                  # 자유 서술 (LLM에 그대로 전달)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    matches: Mapped[list[Match]] = relationship(back_populates="user", cascade="all, delete-orphan")

    def profile_text(self) -> str:
        """LLM 프롬프트에 넣는 사람이 읽는 형태의 프로필."""
        kw = self.keywords.strip() or "없음"
        return (
            f"지역: {self.region}\n업종: {self.biz_type or '미입력'}\n단계: {self.stage}\n"
            f"직원 수: {self.employees}명\n업력: {self.years}년\n관심 키워드: {kw}\n추가 설명: {self.note or '없음'}"
        )


class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)          # bizinfo | kstartup | fixture ...
    source_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(500))
    agency: Mapped[str] = mapped_column(String(200), default="")         # 소관/수행 기관
    region: Mapped[str] = mapped_column(String(64), default="전국")      # 지역 (시/도 or 전국)
    category: Mapped[str] = mapped_column(String(100), default="")       # 금융/기술/인력/수출/내수/창업/경영/기타
    target: Mapped[str] = mapped_column(String(300), default="")         # 지원 대상 요약
    apply_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    apply_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    url: Mapped[str] = mapped_column(String(1000), default="")
    body: Mapped[str] = mapped_column(Text, default="")                  # 요약/본문/해시태그 (LLM 입력)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    matches: Mapped[list[Match]] = relationship(back_populates="announcement", cascade="all, delete-orphan")

    def days_left(self, today: date | None = None) -> int | None:
        if not self.apply_end:
            return None
        return (self.apply_end - (today or date.today())).days


class Match(Base):
    """사용자 × 공고 채점 결과. 한 번 채점하면 다시 채점하지 않는다 (비용 캐시)."""
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("user_id", "announcement_id", name="uq_user_ann"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    announcement_id: Mapped[int] = mapped_column(ForeignKey("announcements.id"), index=True)
    score: Mapped[int] = mapped_column(Integer)                          # 0~100
    eligible: Mapped[str] = mapped_column(String(16), default="unclear") # yes | no | unclear
    one_liner: Mapped[str] = mapped_column(String(300), default="")
    reasons: Mapped[str] = mapped_column(Text, default="")               # 줄바꿈 구분
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="matches")
    announcement: Mapped[Announcement] = relationship(back_populates="matches")


# --- 세션 ---
_engine = None
SessionLocal = None


def get_engine():
    global _engine, SessionLocal
    if _engine is None:
        url = get_settings().database_url
        kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
        _engine = create_engine(url, **kwargs)
        SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def init_db() -> None:
    Base.metadata.create_all(get_engine())


def session():
    get_engine()
    return SessionLocal()
