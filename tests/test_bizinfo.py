"""기업마당 어댑터 파싱 테스트. tests/fixtures/bizinfo_raw.json (실제 응답) 이 있으면 그것도 파싱해 본다."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.ingest.base import region_from_title
from app.ingest.bizinfo import FIELD, BizinfoSource, extract_items, infer_region

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_region_from_title_prefix():
    assert region_from_title("[경기] 2026년 지원사업") == "경기"
    assert region_from_title("[서울특별시] 공고") == "서울"
    assert region_from_title("[전국] 공고") == "전국"
    assert region_from_title("[긴급] 공고") is None
    assert region_from_title("접두 없음") is None


def test_extract_items_handles_nesting():
    row = {FIELD["id"]: "PBLN_1", FIELD["title"]: "x"}
    assert extract_items({"jsonArray": [row]}) == [row]
    assert extract_items({"jsonArray": {"item": [row]}}) == [row]
    assert extract_items({"jsonArray": {"item": row}}) == [row]
    assert extract_items([row, {"noise": 1}]) == [row]
    assert extract_items({"resultCode": "00", "jsonArray": []}) == []


def test_parse_synthetic_sample():
    items = extract_items(load("bizinfo_sample.json"))
    assert len(items) == 3
    src = BizinfoSource(api_key="test")
    a, b, c = (src.parse(it) for it in items)

    # 1) 공고명 접두 지역, 실측 날짜 형식, 절대 URL, HTML 제거 + 엔티티 복원, 분야 대>중
    assert a.source_id == "PBLN_000000000120806"
    assert a.region == "경기"
    assert (a.apply_start, a.apply_end) == (date(2026, 9, 1), date(2026, 10, 2))
    assert a.url.endswith("pblancId=PBLN_000000000120806")
    assert a.category == "내수 > 판로·마케팅"
    assert "<" not in a.body and "최대 300만원" in a.body and "온라인 접수 & 이메일 제출" in a.body
    assert a.target.startswith("경기도 소재 소상공인")
    assert a.extra["printFlpthNm"].startswith("https://")

    # 2) 상시 접수 → 마감 없음, 상대 URL 보정, 지역 단서 없음 → 전국
    assert b.apply_end is None and b.region == "전국"
    assert b.url == "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000120807"
    assert b.category == "금융"

    # 3) 접두 없으면 소관기관명에서 지역, YYYYMMDD 형식
    assert c.region == "부산"
    assert (c.apply_start, c.apply_end) == (date(2026, 9, 1), date(2026, 9, 19))


def test_infer_region_priority():
    assert infer_region({FIELD["title"]: "[전남] x", FIELD["agency"]: "서울특별시"}) == "전남"
    assert infer_region({FIELD["title"]: "x", FIELD["agency"]: "중소벤처기업부", FIELD["exec_agency"]: "대구테크노파크"}) == "대구"
    assert infer_region({FIELD["title"]: "x"}) == "전국"


@pytest.mark.skipif(not (FIXTURES / "bizinfo_raw.json").exists(), reason="실제 응답 픽스처 없음 (scripts/bizinfo_probe.py --save)")
def test_parse_real_response():
    """실제 응답이 있으면: 항목이 있고, 모든 항목이 파싱되며, 매핑의 핵심 키가 응답에 존재해야 한다."""
    items = extract_items(load("bizinfo_raw.json"))
    assert items, "jsonArray 에서 항목을 못 찾음"
    keys = set().union(*(it.keys() for it in items))
    for k in ("id", "title", "date_range", "url", "summary"):
        assert FIELD[k] in keys, f"FIELD[{k}]={FIELD[k]} 가 실제 응답에 없음"
    src = BizinfoSource(api_key="test")
    parsed = [src.parse(it) for it in items]
    assert all(p.title and p.source_id for p in parsed)
    dated = [p for p in parsed if p.extra.get(FIELD["date_range"], "").strip()[:4].isdigit()]
    assert all(p.apply_start for p in dated), "날짜가 있는 항목인데 파싱 실패"
