"""기업마당(bizinfo.go.kr) 지원사업 공고 오픈API 어댑터.

⚠ 확인 필요: 아래 FIELD 매핑은 기업마당 오픈API 응답 필드명에 대한 기억을 바탕으로 작성한 것이다.
   운영 전 반드시 실제 응답(JSON 1건)을 받아 필드명을 대조하고 FIELD 딕셔너리만 고치면 된다.
   인증키 발급: bizinfo.go.kr → 오픈API 신청.
"""
from __future__ import annotations

import re

import httpx

from app.config import get_settings
from app.ingest.base import RawAnnouncement, normalize_region, parse_date_range

# 응답 필드명 → 내부 필드 매핑 (실제 응답으로 검증 후 수정)
FIELD = {
    "id": "pblancId",
    "title": "pblancNm",
    "agency": "jrsdInsttNm",        # 소관기관
    "exec_agency": "excInsttNm",    # 수행기관
    "date_range": "reqstBeginEndDe",# "20260901 ~ 20260930"
    "url": "pblancUrl",
    "target": "trgetNm",            # 지원대상
    "category": "pldirSportRealmLclasCodeNm",  # 분야 대분류명
    "region": "jrsdInsttNm",        # 지역 전용 필드가 없으면 소관기관명에서 추정
    "hashtags": "hashtags",
    "summary": "bsnsSumryCn",
}


def _strip_html(s: str | None) -> str:
    return re.sub(r"<[^>]+>", " ", s or "").replace("&nbsp;", " ").strip()


class BizinfoSource:
    name = "bizinfo"

    def __init__(self, api_key: str | None = None, url: str | None = None, count: int = 200):
        s = get_settings()
        self.api_key = api_key or s.bizinfo_api_key
        self.url = url or s.bizinfo_api_url
        self.count = count

    def fetch(self) -> list[RawAnnouncement]:
        if not self.api_key:
            raise RuntimeError("BIZINFO_API_KEY 가 비어 있습니다.")
        params = {"crtfcKey": self.api_key, "dataType": "json", "searchCnt": self.count}
        r = httpx.get(self.url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        items = data.get("jsonArray") if isinstance(data, dict) else data
        return [self.parse(it) for it in (items or []) if it.get(FIELD["title"])]

    def parse(self, it: dict) -> RawAnnouncement:
        start, end = parse_date_range(it.get(FIELD["date_range"]))
        region_hint = it.get(FIELD["region"], "")
        url = it.get(FIELD["url"], "") or ""
        if url.startswith("/"):
            url = "https://www.bizinfo.go.kr" + url
        body = "\n".join(
            x for x in [
                _strip_html(it.get(FIELD["summary"])),
                "지원대상: " + _strip_html(it.get(FIELD["target"])),
                "수행기관: " + (it.get(FIELD["exec_agency"]) or ""),
                "태그: " + (it.get(FIELD["hashtags"]) or ""),
            ] if x and not x.endswith(": ")
        )
        return RawAnnouncement(
            source=self.name,
            source_id=str(it.get(FIELD["id"]) or url or it.get(FIELD["title"])),
            title=_strip_html(it.get(FIELD["title"])),
            agency=it.get(FIELD["agency"]) or "",
            region=normalize_region(region_hint),
            category=it.get(FIELD["category"]) or "",
            target=_strip_html(it.get(FIELD["target"]))[:300],
            apply_start=start,
            apply_end=end,
            url=url,
            body=body,
            extra=it,
        )
