"""기업마당(bizinfo.go.kr) 지원사업정보 오픈API 어댑터.

필드명 근거 (2026-09-14 정리). 공식 문서 페이지는 로그인/차단으로 직접 확인하지 못했고, 아래 공개 구현체 두 곳의
응답 처리 코드를 대조했다. 두 곳이 일치하는 키만 FIELD 에 넣었다.
  - cweon611/Solverthon lib/ingest/bizinfo.ts — "실측(2026-09-03)" 주석: 응답 {jsonArray:[...]},
    reqstBeginEndDe "2026-09-01 ~ 2026-10-02", pblancUrl 은 selectSIIA200Detail.do?pblancId= 상세 링크(정상 열림),
    공고명 "[경기] …" 접두로 지역 표시, 지역 전용 필드 없음, searchCnt 1000까지, hashtags 서버 필터 미동작.
  - kwanGDss/mcp-bizinfo server.py — 같은 키 집합(pblancId/pblancNm/jrsdInsttNm/excInsttNm/reqstBeginEndDe/
    pblancUrl/trgetNm/pldirSportRealmLclasCodeNm/bsnsSumryCn/creatPnttm), jsonArray 아래 item 중첩 가능성.
아직 이 저장소의 키로 받은 실제 응답은 없다. `python scripts/bizinfo_probe.py --save tests/fixtures/bizinfo_raw.json`
으로 원본을 저장하면 tests/test_bizinfo.py 가 그 파일을 우선 사용한다.
"""
from __future__ import annotations

import html
import re
from typing import Any

import httpx

from app.config import get_settings
from app.ingest.base import RawAnnouncement, normalize_region, parse_date_range, region_from_title

BASE = "https://www.bizinfo.go.kr"

# 응답 필드명 → 내부 필드
FIELD = {
    "id": "pblancId",                     # 'PBLN_000000000120806' 형식
    "title": "pblancNm",                  # 공고명. '[경기] …' 시도 접두가 붙는 경우가 있음
    "agency": "jrsdInsttNm",              # 소관기관
    "exec_agency": "excInsttNm",          # 수행기관
    "date_range": "reqstBeginEndDe",      # '2026-09-01 ~ 2026-10-02' (실측) 또는 '20260901 ~ 20261002'
    "url": "pblancUrl",                   # 상세 링크
    "apply_url": "rceptEngnHmpgUrl",      # 접수 기관 홈페이지
    "target": "trgetNm",                  # 지원대상
    "category": "pldirSportRealmLclasCodeNm",    # 분야 대분류명 (금융/기술/인력/수출/내수/창업/경영/기타)
    "subcategory": "pldirSportRealmMlsfcCodeNm", # 분야 중분류명
    "method": "reqstMthPapersCn",         # 신청방법 (HTML 포함 가능)
    "contact": "refrncNm",                # 문의처
    "summary": "bsnsSumryCn",             # 사업개요 (HTML 포함 가능)
    "hashtags": "hashtags",
    "created": "creatPnttm",              # 등록일시
    "attachment_name": "printFileNm",
    "attachment_url": "printFlpthNm",     # 첨부파일 링크
}

_ROLLING = re.compile(r"상시|수시|예산\s*소진|연중")


def _strip_html(s: str | None) -> str:
    s = html.unescape(s or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def extract_items(payload: Any, depth: int = 0) -> list[dict]:
    """응답에서 공고 dict 배열을 꺼낸다. {jsonArray:[...]}, {jsonArray:{item:[...]}}, [...] 모두 처리."""
    if depth > 6 or payload is None:
        return []
    if isinstance(payload, list):
        rows = [x for x in payload if isinstance(x, dict) and FIELD["id"] in x]
        if rows:
            return rows
        return [r for x in payload for r in extract_items(x, depth + 1)]
    if isinstance(payload, dict):
        if FIELD["id"] in payload:
            return [payload]
        return [r for v in payload.values() for r in extract_items(v, depth + 1)]
    return []


def infer_region(it: dict) -> str:
    """지역 전용 필드가 없다. 공고명 접두 '[경기]' → 소관기관명 → 수행기관명 순으로 시/도를 찾고, 없으면 '전국'."""
    r = region_from_title(it.get(FIELD["title"]))
    if r:
        return r
    for key in ("agency", "exec_agency"):
        r = normalize_region(it.get(FIELD[key]) or "")
        if r != "전국":
            return r
    return "전국"


class BizinfoSource:
    name = "bizinfo"

    def __init__(self, api_key: str | None = None, url: str | None = None, count: int = 200, category_code: str | None = None):
        s = get_settings()
        self.api_key = api_key or s.bizinfo_api_key
        self.url = url or s.bizinfo_api_url
        self.count = min(count, 1000)
        self.category_code = category_code  # searchLclasId (분야 코드) 필터. 예: '01'

    def fetch(self) -> list[RawAnnouncement]:
        if not self.api_key:
            raise RuntimeError("BIZINFO_API_KEY 가 비어 있습니다.")
        params = {"crtfcKey": self.api_key, "dataType": "json", "searchCnt": self.count}
        if self.category_code:
            params["searchLclasId"] = self.category_code
        r = httpx.get(self.url, params=params, timeout=30)
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError as e:
            raise RuntimeError(f"기업마당 응답이 JSON 이 아닙니다 (앞 300자): {r.text[:300]!r}") from e
        return [self.parse(it) for it in extract_items(data) if it.get(FIELD["title"])]

    def parse(self, it: dict) -> RawAnnouncement:
        g = lambda k: it.get(FIELD[k]) or ""  # noqa: E731
        period = g("date_range")
        start, end = parse_date_range(period)
        if _ROLLING.search(period):
            end = None  # '상시', '예산 소진 시까지' 는 마감 없음으로 본다

        url = g("url")
        if url and not url.startswith("http"):
            url = BASE + ("" if url.startswith("/") else "/") + url
        if not url:
            url = f"{BASE}/sii/siia/selectSIIA200Detail.do?pblancId={g('id')}"

        category = g("category") + (f" > {g('subcategory')}" if g("subcategory") else "")
        parts = [
            _strip_html(g("summary")),
            f"지원대상: {_strip_html(g('target'))}",
            f"신청방법: {_strip_html(g('method'))}",
            f"수행기관: {g('exec_agency')}",
            f"문의: {_strip_html(g('contact'))}",
            f"접수기간: {period}",
            f"태그: {g('hashtags')}",
        ]
        body = "\n".join(x for x in parts if x and not x.endswith(": "))

        return RawAnnouncement(
            source=self.name,
            source_id=str(g("id") or url),
            title=_strip_html(g("title")),
            agency=g("agency"),
            region=infer_region(it),
            category=category,
            target=_strip_html(g("target"))[:300],
            apply_start=start,
            apply_end=end,
            url=url,
            body=body,
            extra=it,
        )
