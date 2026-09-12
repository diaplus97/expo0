"""일일 배치. `python -m app.jobs.daily` 로 실행. 매일 오전 7시 KST 권장."""
from __future__ import annotations

import json
import sys
from datetime import date

from app.db import init_db
from app.ingest.sources import run_ingest
from app.matching.run import run_matching
from app.notify.run import run_notify


def main(today: date | None = None) -> dict:
    init_db()
    report = {
        "ingest": run_ingest(),
        "matching": run_matching(today),
        "notify": run_notify(today),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None
    main(d)
