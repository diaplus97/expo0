"""웹 앱: 랜딩 + 가입 + 설정. 로그인 없이 이메일 링크(token)로만 접근한다."""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Announcement, Match, User, init_db, session
from app.ingest.base import REGIONS
from app.notify.email import get_backend

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="지원사업 레이더", lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")




def db_dep():
    db = session()
    try:
        yield db
    finally:
        db.close()


def render(request: Request, name: str, status_code: int = 200, **kw):
    s = get_settings()
    context = {"app_name": s.app_name, "regions": REGIONS, "pro_price": f"{s.pro_price_krw:,}", **kw}
    return templates.TemplateResponse(request, name, context, status_code=status_code)


# --- 랜딩 & 가입 ---

@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return render(request, "landing.html", error=None, form={})


@app.post("/signup", response_class=HTMLResponse)
def signup(
    request: Request,
    email: str = Form(...), region: str = Form("전국"), biz_type: str = Form(""),
    keywords: str = Form(""), stage: str = Form("운영중"), employees: int = Form(1),
    years: int = Form(0), consent: str = Form(""),
    db: Session = Depends(db_dep),
):
    s = get_settings()
    email = email.strip().lower()
    form = dict(email=email, region=region, biz_type=biz_type, keywords=keywords, stage=stage, employees=employees, years=years)
    if not EMAIL_RE.match(email):
        return render(request, "landing.html", error="이메일 주소 형식을 확인해 주세요.", form=form, status_code=400)
    if consent != "on":
        return render(request, "landing.html", error="알림 메일 수신에 동의해야 가입할 수 있습니다.", form=form, status_code=400)
    if region not in REGIONS:
        region = "전국"

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email)
        db.add(user)
    user.region, user.biz_type, user.keywords = region, biz_type.strip()[:200], keywords.strip()[:400]
    user.stage, user.employees, user.years = stage, max(0, employees), max(0, years)
    user.active = True
    db.commit()

    confirm_url = f"{s.base_url}/confirm/{user.token}"
    get_backend().send(
        user.email,
        f"[{s.app_name}] 이메일 확인 한 번만 해주세요",
        f"<p>아래 링크를 누르면 알림이 시작됩니다.</p><p><a href=\"{confirm_url}\">{confirm_url}</a></p>"
        f"<p style=\"color:#777;font-size:12px\">본인이 신청하지 않았다면 이 메일은 무시하세요.</p>",
        f"아래 링크를 누르면 알림이 시작됩니다.\n{confirm_url}",
    )
    return render(request, "message.html", title="확인 메일을 보냈습니다",
        body=f"{email} 으로 보낸 메일의 링크를 누르면 알림이 시작됩니다. 메일이 안 보이면 스팸함을 확인해 주세요.")


@app.get("/confirm/{token}", response_class=HTMLResponse)
def confirm(request: Request, token: str, db: Session = Depends(db_dep)):
    user = db.scalar(select(User).where(User.token == token))
    if not user:
        raise HTTPException(404)
    user.confirmed = True
    user.active = True
    db.commit()
    return render(request, "message.html", title="알림이 시작됐습니다",
        body="첫 알림은 다음 배치 때 도착합니다. 조건은 언제든 아래에서 바꿀 수 있어요.",
        link=f"/u/{user.token}", link_text="알림 조건 보기")


# --- 설정 / 수신거부 / 프로 ---

@app.get("/u/{token}", response_class=HTMLResponse)
def settings_page(request: Request, token: str, db: Session = Depends(db_dep)):
    user = db.scalar(select(User).where(User.token == token))
    if not user:
        raise HTTPException(404)
    recent = db.scalars(select(Match).where(Match.user_id == user.id).order_by(Match.score.desc()).limit(10)).all()
    return render(request, "settings.html", user=user, recent=recent, today=date.today(),
        payment_link=get_settings().payment_link_url, saved=request.query_params.get("saved"))


@app.post("/u/{token}", response_class=HTMLResponse)
def settings_save(
    token: str, region: str = Form("전국"), biz_type: str = Form(""), keywords: str = Form(""),
    stage: str = Form("운영중"), employees: int = Form(1), years: int = Form(0), note: str = Form(""),
    frequency: str = Form("weekly"), db: Session = Depends(db_dep),
):
    user = db.scalar(select(User).where(User.token == token))
    if not user:
        raise HTTPException(404)
    user.region = region if region in REGIONS else "전국"
    user.biz_type, user.keywords, user.note = biz_type.strip()[:200], keywords.strip()[:400], note.strip()[:1000]
    user.stage, user.employees, user.years = stage, max(0, employees), max(0, years)
    user.frequency = frequency if (user.plan == "pro" and frequency in ("daily", "weekly")) else "weekly"
    db.commit()
    return RedirectResponse(f"/u/{token}?saved=1", status_code=303)


@app.get("/u/{token}/unsubscribe", response_class=HTMLResponse)
def unsubscribe(request: Request, token: str, db: Session = Depends(db_dep)):
    user = db.scalar(select(User).where(User.token == token))
    if not user:
        raise HTTPException(404)
    user.active = False
    db.commit()
    return render(request, "message.html", title="수신을 중단했습니다", body="더 이상 알림 메일을 보내지 않습니다. 다시 받고 싶으면 같은 이메일로 다시 가입하면 됩니다.")


# --- 관리자 (숫자만) ---

@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, key: str = "", db: Session = Depends(db_dep)):
    if key != get_settings().admin_key:
        raise HTTPException(403)
    stats = {
        "users_total": db.scalar(select(func.count(User.id))),
        "users_confirmed": db.scalar(select(func.count(User.id)).where(User.confirmed.is_(True), User.active.is_(True))),
        "users_pro": db.scalar(select(func.count(User.id)).where(User.plan == "pro")),
        "announcements": db.scalar(select(func.count(Announcement.id))),
        "matches": db.scalar(select(func.count(Match.id))),
        "matches_sent": db.scalar(select(func.count(Match.id)).where(Match.sent_at.is_not(None))),
    }
    return render(request, "admin.html", stats=stats)


@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return render(request, "privacy.html")


@app.get("/health")
def health():
    return {"ok": True}
