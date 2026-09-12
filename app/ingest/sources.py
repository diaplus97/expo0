"""공공데이터포털(data.go.kr) 범용 JSON 어댑터, 로컬 픽스처 소스, 그리고 수집 실행기."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.db import Announcement, session
from app.ingest.base import RawAnnouncement, normalize_region, parse_date, parse_date_range
from app.ingest.bizinfo import BizinfoSource

ROOT = Path(__file__).resolve().parents[2]


class DataGoKrSource:
    """공공데이터포털 JSON API를 필드 매핑만으로 붙이는 범용 어댑터.

    ⚠ 확인 필요: K-Startup(창업진흥원) 공고 API의 정확한 엔드포인트·필드명은 data.go.kr 에서
       '창업지원사업 공고' 로 검색해 활용신청 후 샘플 응답을 보고 mapping 을 채운다.
    """

    def __init__(self, name: str, url: str, mapping: dict, api_key: str | None = None, extra_params: dict | None = None):
        self.name = name
        self.url = url
        self.mapping = mapping
        self.api_key = api_key or get_settings().datago_api_key
        self.extra_params = extra_params or {}

    def fetch(self) -> list[RawAnnouncement]:
        if not self.url or not self.api_key:
            raise RuntimeError(f"{self.name}: 엔드포인트 또는 DATAGO_API_KEY 미설정")
        params = {"serviceKey": self.api_key, "type": "json", "numOfRows": 200, "pageNo": 1, **self.extra_params}
        r = httpx.get(self.url, params=params, timeout=30)
        r.raise_for_status()
        items = self._dig(r.json(), self.mapping.get("_items_path", "response.body.items"))
        return [self.parse(it) for it in items if it.get(self.mapping["title"])]

    @staticmethod
    def _dig(data, path: str):
        cur = data
        for key in path.split("."):
            if isinstance(cur, dict):
                cur = cur.get(key, [])
        if isinstance(cur, dict):  # {"item": [...]} 형태
            cur = cur.get("item", [])
        return cur or []

    def parse(self, it: dict) -> RawAnnouncement:
        m = self.mapping
        if "date_range" in m:
            start, end = parse_date_range(it.get(m["date_range"]))
        else:
            start, end = parse_date(it.get(m.get("start", ""))), parse_date(it.get(m.get("end", "")))
        return RawAnnouncement(
            source=self.name,
            source_id=str(it.get(m["id"]) or it.get(m["title"])),
            title=str(it.get(m["title"])),
            agency=str(it.get(m.get("agency", ""), "") or ""),
            region=normalize_region(it.get(m.get("region", ""), "")),
            category=str(it.get(m.get("category", ""), "") or ""),
            target=str(it.get(m.get("target", ""), "") or "")[:300],
            apply_start=start,
            apply_end=end,
            url=str(it.get(m.get("url", ""), "") or ""),
            body=str(it.get(m.get("body", ""), "") or ""),
            extra=it,
        )


# K-Startup 예시 매핑 — 실제 응답으로 검증 후 수정
KSTARTUP_MAPPING = {
    "_items_path": "response.body.items",
    "id": "pbanc_sn", "title": "biz_pbanc_nm", "agency": "pbanc_ntrp_nm",
    "start": "pbanc_rcpt_bgng_dt", "end": "pbanc_rcpt_end_dt",
    "region": "supt_regin", "category": "supt_biz_clsfc", "target": "aply_trgt",
    "url": "detl_pg_url", "body": "pbanc_ctnt",
}


class FixtureSource:
    """fixtures/announcements_sample.json 을 읽는 개발/테스트용 소스."""
    name = "fixture"

    def __init__(self, path: Path | None = None):
        self.path = path or ROOT / "fixtures" / "announcements_sample.json"

    def fetch(self) -> list[RawAnnouncement]:
        rows = json.loads(self.path.read_text(encoding="utf-8"))
        out = []
        for r in rows:
            out.append(RawAnnouncement(
                source=self.name, source_id=r["id"], title=r["title"], agency=r.get("agency", ""),
                region=normalize_region(r.get("region")), category=r.get("category", ""),
                target=r.get("target", ""), apply_start=parse_date(r.get("apply_start")),
                apply_end=parse_date(r.get("apply_end")), url=r.get("url", ""), body=r.get("body", ""),
            ))
        return out


def build_sources(names: str | None = None) -> list:
    s = get_settings()
    out = []
    for n in (names or s.ingest_sources).split(","):
        n = n.strip()
        if n == "fixture":
            out.append(FixtureSource())
        elif n == "bizinfo":
            out.append(BizinfoSource())
        elif n == "kstartup":
            out.append(DataGoKrSource("kstartup", s.kstartup_api_url, KSTARTUP_MAPPING))
        elif n:
            raise ValueError(f"알 수 없는 소스: {n}")
    return out


def upsert(raws: list[RawAnnouncement]) -> tuple[int, int]:
    """(신규 건수, 갱신 건수). source+source_id 기준으로 멱등."""
    new = updated = 0
    with session() as db:
        for r in raws:
            existing = db.scalar(select(Announcement).where(
                Announcement.source == r.source, Announcement.source_id == r.source_id))
            if existing:
                changed = False
                for f in ("title", "agency", "region", "category", "target", "apply_start", "apply_end", "url", "body"):
                    if getattr(existing, f) != getattr(r, f):
                        setattr(existing, f, getattr(r, f)); changed = True
                if changed:
                    existing.fetched_at = datetime.now(timezone.utc); updated += 1
            else:
                db.add(Announcement(**{f: getattr(r, f) for f in (
                    "source", "source_id", "title", "agency", "region", "category", "target",
                    "apply_start", "apply_end", "url", "body")}))
                new += 1
        db.commit()
    return new, updated


def run_ingest(names: str | None = None) -> dict:
    report = {}
    for src in build_sources(names):
        try:
            raws = src.fetch()
            n, u = upsert(raws)
            report[src.name] = {"fetched": len(raws), "new": n, "updated": u}
        except Exception as e:  # 한 소스 실패가 전체를 막지 않게
            report[src.name] = {"error": f"{type(e).__name__}: {e}"}
    return report
