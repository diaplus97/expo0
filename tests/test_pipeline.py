"""엔드투엔드에 가까운 테스트. 임시 SQLite + fixture 소스 + mock 채점기 + console 메일."""
from __future__ import annotations

import os
from datetime import date, timedelta

import pytest

os.environ["DATABASE_URL"] = "sqlite:///./test_radar.db"
os.environ["INGEST_SOURCES"] = "fixture"
os.environ["SCORER"] = "mock"
os.environ["EMAIL_BACKEND"] = "console"
os.environ["ADMIN_KEY"] = "t"

from app import db as dbmod  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Announcement, Base, Match, User, get_engine, session  # noqa: E402
from app.ingest.base import normalize_region, parse_date_range  # noqa: E402
from app.ingest.sources import run_ingest  # noqa: E402
from app.matching.prefilter import prefilter  # noqa: E402
from app.matching.run import run_matching  # noqa: E402
from app.matching.scorer import parse_score  # noqa: E402
from app.notify.email import ConsoleBackend  # noqa: E402
from app.notify.run import run_notify  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    get_settings.cache_clear()
    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
    yield


def add_user(**kw):
    with session() as db:
        u = User(email=kw.pop("email", "owner@example.com"), confirmed=True, **kw)
        db.add(u); db.commit()
        return u.id


# --- 파싱 ---

def test_region_and_date_parsing():
    assert normalize_region("서울특별시 강남구") == "서울"
    assert normalize_region("전북특별자치도") == "전북"
    assert normalize_region("중소벤처기업부") == "전국"
    assert parse_date_range("20260901 ~ 20260930") == (date(2026, 9, 1), date(2026, 9, 30))
    assert parse_date_range("2026-09-01~2026-09-30") == (date(2026, 9, 1), date(2026, 9, 30))
    assert parse_date_range("예산 소진 시까지") == (None, None)


def test_parse_score_tolerates_noise():
    s = parse_score('설명입니다. {"score": 87, "eligible": "yes", "one_liner": "판로 200만원", "reasons": ["서울", "업력"]} 끝')
    assert (s.score, s.eligible, s.one_liner, len(s.reasons)) == (87, "yes", "판로 200만원", 2)
    bad = parse_score("모델이 이상한 걸 뱉음")
    assert bad.score == 0 and bad.eligible == "unclear"
    assert parse_score('{"score": 140, "eligible": "maybe"}').score == 100


# --- 수집 ---

def test_ingest_is_idempotent():
    r1 = run_ingest("fixture")["fixture"]
    r2 = run_ingest("fixture")["fixture"]
    assert r1["new"] == 8 and r2["new"] == 0 and r2["updated"] == 0
    with session() as db:
        assert db.query(Announcement).count() == 8


# --- 필터 ---

def test_prefilter_rules():
    run_ingest("fixture")
    uid = add_user(region="서울", stage="운영중", keywords="소상공인, 온라인판매")
    with session() as db:
        u = db.get(User, uid)
        anns = db.query(Announcement).all()
        kept = prefilter(u, anns, date.today())
        titles = [a.title for a in kept]
        assert not any("마감된" in t for t in titles)          # 마감 제외
        assert not any("경기도" in t for t in titles)          # 타 지역 제외
        assert not any("예비창업패키지" in t for t in titles)   # 운영중 → 예비창업 전용 제외
        assert "2026년 하반기 소상공인 온라인 판로 지원사업 (2차 모집)" == titles[0]  # 키워드 2개 적중이 맨 앞


def test_prefilter_pre_startup_excludes_experience_requirements():
    run_ingest("fixture")
    uid = add_user(region="경기", stage="예비창업")
    with session() as db:
        u = db.get(User, uid)
        kept = prefilter(u, db.query(Announcement).all(), date.today())
        assert not any("수출 바우처" in a.title for a in kept)   # 업력 3년 이상 요구 → 제외


# --- 매칭 + 발송 ---

def test_full_daily_batch_free_and_pro():
    run_ingest("fixture")
    free_id = add_user(email="free@example.com", region="서울", keywords="소상공인, 온라인판매")
    pro_id = add_user(email="pro@example.com", region="서울", keywords="소상공인", plan="pro", frequency="daily")

    m = run_matching(date.today())
    assert m["users"] == 2 and m["scored"] > 0
    with session() as db:
        assert db.query(Match).filter(Match.user_id == free_id).count() >= 3

    n = run_notify(date.today(), backend=ConsoleBackend())
    assert n["sent"] == 2
    last = ConsoleBackend.last
    assert last["to"] == "pro@example.com"
    assert "적합도" in last["html"] and "수신 거부" in last["html"]

    # 두 번째 실행: 매일(pro)은 오늘 이미 보냈으니 skip, 무료도 skip
    n2 = run_notify(date.today(), backend=ConsoleBackend())
    assert n2["sent"] == 0
    # 다음 날: pro 는 새 매칭이 없으면 빈 메일을 보내지 않는다
    n3 = run_notify(date.today() + timedelta(days=1), backend=ConsoleBackend())
    assert n3["sent"] == 0 and n3["skipped_empty"] >= 1


def test_free_digest_caps_items_and_upsells():
    run_ingest("fixture")
    add_user(email="free@example.com", region="전국", keywords="소상공인")
    run_matching(date.today())
    run_notify(date.today(), backend=ConsoleBackend())
    html = ConsoleBackend.last["html"]
    assert html.count("적합도 ") <= get_settings().free_max_items_per_digest
    assert "프로로 바꾸기" in html


# --- 웹 ---

def test_web_signup_confirm_settings_unsubscribe():
    from fastapi.testclient import TestClient
    from app.web.main import app

    c = TestClient(app)
    assert c.get("/").status_code == 200
    r = c.post("/signup", data={"email": "new@example.com", "region": "부산", "biz_type": "카페", "keywords": "", "stage": "운영중", "employees": 2, "years": 1, "consent": "on"})
    assert r.status_code == 200 and "확인 메일" in r.text
    assert c.post("/signup", data={"email": "bad", "consent": "on"}).status_code == 400
    assert c.post("/signup", data={"email": "x@example.com"}).status_code == 400  # 동의 없음

    with session() as db:
        u = db.query(User).filter_by(email="new@example.com").one()
        assert not u.confirmed
        token = u.token

    assert "알림이 시작" in c.get(f"/confirm/{token}").text
    r = c.post(f"/u/{token}", data={"region": "부산", "biz_type": "카페", "keywords": "마케팅", "stage": "운영중", "employees": 3, "years": 2, "note": "", "frequency": "daily"}, follow_redirects=True)
    assert r.status_code == 200 and "저장했습니다" in r.text
    with session() as db:
        u = db.query(User).filter_by(email="new@example.com").one()
        assert u.confirmed and u.keywords == "마케팅" and u.frequency == "weekly"  # free 는 daily 불가

    assert "수신을 중단" in c.get(f"/u/{token}/unsubscribe").text
    assert c.get("/admin").status_code == 403
    assert c.get("/admin?key=t").status_code == 200
    assert c.get("/privacy").status_code == 200
    assert c.get("/u/nope").status_code == 404
