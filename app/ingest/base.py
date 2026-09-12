"""수집 소스 공통 인터페이스. 모든 소스는 fetch() 로 RawAnnouncement 리스트를 돌려준다."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

REGIONS = [
    "전국", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
]

_REGION_ALIASES = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
    "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종",
    "경기도": "경기", "강원도": "강원", "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남",
    "전라북도": "전북", "전북특별자치도": "전북", "전라남도": "전남", "경상북도": "경북",
    "경상남도": "경남", "제주특별자치도": "제주", "제주도": "제주",
}


@dataclass
class RawAnnouncement:
    source: str
    source_id: str
    title: str
    agency: str = ""
    region: str = "전국"
    category: str = ""
    target: str = ""
    apply_start: date | None = None
    apply_end: date | None = None
    url: str = ""
    body: str = ""
    extra: dict = field(default_factory=dict)


class Source(Protocol):
    name: str

    def fetch(self) -> list[RawAnnouncement]: ...


# --- 정규화 헬퍼 ---

def normalize_region(text: str | None) -> str:
    """'서울특별시 강남구', '경기도' 같은 문자열을 시/도 단위 표준 이름으로. 못 찾으면 '전국'."""
    if not text:
        return "전국"
    t = text.strip()
    for long, short in _REGION_ALIASES.items():
        if t.startswith(long):
            return short
    for r in REGIONS:
        if t.startswith(r):
            return r
    return "전국"


_DATE_PATTERNS = ["%Y%m%d", "%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"]


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    t = text.strip()
    for p in _DATE_PATTERNS:
        try:
            return datetime.strptime(t[:10] if "-" in p or "." in p or "/" in p else t[:8], p).date()
        except ValueError:
            continue
    return None


def parse_date_range(text: str | None) -> tuple[date | None, date | None]:
    """'20260901 ~ 20260930', '2026-09-01~2026-09-30', '예산 소진 시까지' 등을 (시작, 종료)로."""
    if not text:
        return None, None
    parts = re.split(r"\s*[~∼～-]\s*(?=\d{4})", text.strip(), maxsplit=1)
    if len(parts) == 2:
        return parse_date(parts[0]), parse_date(parts[1])
    d = parse_date(parts[0])
    return d, d if d else None
