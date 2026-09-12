# 배포

## 로컬 실행
```bash
pip install -r requirements.txt
cp .env.example .env            # 값 비워 두면 fixture/mock/console 로 동작
uvicorn app.web.main:app --reload
python -m app.jobs.daily        # 수집→매칭→발송 1회 실행 (console 이면 메일이 터미널에 찍힘)
python -m pytest -q
```

## 운영 전 필요한 것 (본인만 할 수 있는 일)
1. **기업마당 오픈API 인증키** — bizinfo.go.kr 오픈API 신청 → `BIZINFO_API_KEY`
2. **공공데이터포털 서비스키** — data.go.kr 에서 'K-Startup 창업지원사업 공고' 활용신청 → `DATAGO_API_KEY`, `KSTARTUP_API_URL`
   - 발급 후 반드시 실제 응답 1건을 받아 `app/ingest/bizinfo.py` 의 `FIELD` 와 `app/ingest/sources.py` 의 `KSTARTUP_MAPPING` 을 대조해 고친다.
3. **Anthropic API 키** → `ANTHROPIC_API_KEY`, `SCORER=anthropic`
4. **도메인 + 이메일 발송** — Resend 가입, 도메인 인증(SPF/DKIM/DMARC 레코드 추가) → `RESEND_API_KEY`, `EMAIL_FROM`, `EMAIL_BACKEND=resend`
5. **BASE_URL** 을 실제 도메인으로 (메일 안 링크가 이걸로 만들어짐)

## 호스팅 (예: Fly.io / Railway / Render 중 하나)
- Dockerfile 그대로 사용. 웹 프로세스: `uvicorn app.web.main:app --host 0.0.0.0 --port 8000`
- SQLite 파일은 **영구 볼륨**에 두고 `DATABASE_URL=sqlite:////data/radar.db` 로. 유료 사용자 생기면 Postgres 로 이전 (SQLAlchemy 라 URL만 바꾸면 됨).
- 배치: 매일 07:00 KST(= 22:00 UTC 전날) 에 `python -m app.jobs.daily`
  - Fly: `fly machine run` 스케줄 또는 GitHub Actions cron 에서 `fly ssh console -C "python -m app.jobs.daily"`
  - Railway/Render: Cron Job 서비스로 같은 이미지에서 위 명령 실행
- `/health` 를 헬스체크에 등록.

## 결제 (사업자등록 후)
- 국내 카드 정기결제는 토스페이먼츠/포트원 등 PG 가 필요하고, 모두 사업자등록번호 + 통신판매업 신고를 요구한다.
- 가장 빠른 임시 방법: PG 의 '결제 링크' 기능으로 월 9,900원 상품 링크를 만들어 `PAYMENT_LINK_URL` 에 넣고, 결제 완료 메일을 보고 관리자가 `users.plan='pro'` 로 바꾼다. 자동화(웹훅)는 프로 10명 넘으면.

## 운영 체크
- `/admin?key=ADMIN_KEY` 에서 가입/발송 건수 확인
- 배치 로그의 `ingest.*.error` 가 계속 뜨면 API 키 만료 또는 필드 변경
