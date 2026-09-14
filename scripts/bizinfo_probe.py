"""기업마당 오픈API 응답을 받아 FIELD 매핑·날짜·지역 파싱을 검증한다 (HANDOFF 1단계용).

사용법 (로컬, .env 에 BIZINFO_API_KEY 필요):
    python scripts/bizinfo_probe.py --save tests/fixtures/bizinfo_raw.json   # 실제 호출 + 원본 저장 + 진단
    python scripts/bizinfo_probe.py --file tests/fixtures/bizinfo_raw.json   # 저장된 응답으로 진단만 (네트워크 불필요)

출력: 응답 최상위 구조, 1건 원본 JSON, FIELD 매핑 중 응답에 없는 키, 접수기간 문자열과 파싱 결과,
      지역 후보 필드 값 분포(최대 20건). 어댑터 코드는 건드리지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.ingest.base import normalize_region, parse_date_range  # noqa: E402
from app.ingest.bizinfo import FIELD, BizinfoSource  # noqa: E402

REGION_HINT_WORDS = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
                     "충북", "충남", "전북", "전남", "경북", "경남", "제주", "특별시", "광역시", "도")


def fetch_raw(count: int) -> dict | list:
    s = get_settings()
    if not s.bizinfo_api_key:
        sys.exit("BIZINFO_API_KEY 가 비어 있습니다 (.env 확인).")
    params = {"crtfcKey": s.bizinfo_api_key, "dataType": "json", "searchCnt": count}
    r = httpx.get(s.bizinfo_api_url, params=params, timeout=30)
    print(f"HTTP {r.status_code}  content-type={r.headers.get('content-type')}  bytes={len(r.content)}")
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        print("응답이 JSON 이 아닙니다. 앞 500자:\n", r.text[:500])
        sys.exit(1)


def extract_items(data) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        print("최상위 키:", list(data.keys()))
        for k in ("jsonArray", "items", "item", "data", "list"):
            if isinstance(data.get(k), list):
                print(f"항목 배열 키: '{k}'  (어댑터는 'jsonArray' 를 기대)")
                return data[k]
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--save", metavar="PATH", help="실제 호출 후 원본 응답을 이 파일에 저장")
    g.add_argument("--file", metavar="PATH", help="저장된 원본 응답 파일로 진단만")
    ap.add_argument("--count", type=int, default=20)
    a = ap.parse_args()

    if a.file:
        data = json.loads(Path(a.file).read_text(encoding="utf-8"))
    else:
        data = fetch_raw(a.count)
        Path(a.save).parent.mkdir(parents=True, exist_ok=True)
        Path(a.save).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"원본 저장: {a.save}")

    items = extract_items(data)
    print(f"\n항목 수: {len(items)}")
    if not items:
        print("항목이 없습니다. 위 최상위 키를 보고 어댑터의 items 추출을 고쳐야 합니다.")
        return

    first = items[0]
    print("\n=== 1건 원본 ===")
    print(json.dumps(first, ensure_ascii=False, indent=2))

    print("\n=== FIELD 매핑 대조 ===")
    keys = set().union(*(it.keys() for it in items))
    for k, v in FIELD.items():
        mark = "OK " if v in keys else "없음"
        print(f"  {mark}  {k:11s} -> {v}")
    unused = sorted(keys - set(FIELD.values()))
    print("  매핑에 없는 응답 키:", unused)

    print("\n=== 접수기간 파싱 (date_range) ===")
    dr_key = FIELD["date_range"]
    for it in items[:10]:
        raw = it.get(dr_key)
        print(f"  {raw!r:40s} -> {parse_date_range(raw)}")
    print("  후보 키(기간/일자 포함):", [k for k in keys if any(w in k.lower() for w in ("de", "date", "dt", "pd", "term", "begin", "end"))])

    print("\n=== 지역 추출 (최대 20건) ===")
    cand = [k for k in keys if any(w in k.lower() for w in ("area", "region", "zone", "loc", "sido", "ctpv", "insttnm"))]
    print("  지역 후보 키:", cand)
    for k in cand:
        dist = Counter(normalize_region(str(it.get(k) or "")) for it in items[:20])
        print(f"  {k}: normalize_region 분포 {dict(dist)}")
        print(f"     원본 예시: {[it.get(k) for it in items[:5]]}")
    other = [k for k in keys if k not in cand and any(
        any(w in str(items[i].get(k) or "") for w in REGION_HINT_WORDS) for i in range(min(5, len(items))))]
    print("  값에 지역 단어가 보이는 다른 키:", other)

    print("\n=== 어댑터 parse() 결과 (앞 3건) ===")
    src = BizinfoSource(api_key="probe")
    for it in items[:3]:
        try:
            r = src.parse(it)
            print(f"  [{r.region}] {r.apply_start}~{r.apply_end} | {r.title[:40]} | {r.agency} | {r.category} | {r.url[:50]}")
        except Exception as e:  # noqa: BLE001
            print("  parse 실패:", repr(e))


if __name__ == "__main__":
    main()
