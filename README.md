# 지원사업 레이더

소상공인·1인 사업자에게 **실제로 신청 자격이 되는** 정부 지원사업 공고만 골라, 자격 근거와 마감일을 붙여 이메일로 보내는 구독 서비스.

- 무료: 주 1회, 가장 잘 맞는 공고 3건
- 프로(월 9,900원 가설): 매일, 맞는 공고 전부, 자격 판정 근거

## 어떻게 동작하나
1. `ingest` — 기업마당·K-Startup 공고를 매일 수집해 SQLite 에 저장 (멱등)
2. `matching` — 지역·마감·단계로 규칙 필터 → LLM 이 프로필과 공고 원문을 대조해 적합도·자격·한 줄 요약·근거를 JSON 으로 판정 (사용자×공고 1회만 채점)
3. `notify` — 요금제 규칙대로 잘라 HTML/텍스트 다이제스트 발송 (더블 옵트인, 수신거부)
4. `web` — 랜딩·가입·설정·수신거부·개인정보처리방침·관리자 현황

## 바로 실행
```bash
pip install -r requirements.txt
cp .env.example .env
python -m pytest -q
uvicorn app.web.main:app --reload      # http://localhost:8000
```

배치(`python -m app.jobs.daily`)는 **확인된 사용자에게만** 메일을 보낸다. 사용자가 없으면 수집 리포트만 나오고 메일은 안 나온다. 데모 메일을 보려면 먼저 사용자를 만든다.

- 가입 흐름 그대로: 랜딩 페이지에서 가입 → `EMAIL_BACKEND=console` 이라 확인 메일은 uvicorn 터미널에 찍힌다 → 그 안의 `/confirm/<token>` 링크를 연다.
- 또는 DB 에 바로 넣기:
  ```bash
  python -c "
  from app.db import init_db, session, User
  init_db()
  with session() as db:
      db.add(User(email='demo@example.com', confirmed=True, region='서울', biz_type='카페', keywords='소상공인,마케팅', employees=2, years=1))
      db.commit()
  "
  ```

그 다음 배치를 돌리면 fixture 공고 8건 중 맞는 것이 mock 채점을 거쳐 console 메일로 출력된다.
```bash
python -m app.jobs.daily               # 기본은 fixture + mock + console
```
무료 요금제는 주 1회 발송이라 같은 사용자에게 다시 보려면 `radar.db` 를 지우고 처음부터 한다. 자세한 건 `HANDOFF.md` 0단계.

## 문서
- `HANDOFF.md` — Claude Code 에 이어서 시킬 작업, 순서대로
- `docs/PRD.md` — 기획·가설·경쟁·리스크
- `docs/DEPLOY.md` — 배포와 외부 서비스 연결
- `docs/LEGAL_CHECKLIST.md` — 출시 전/유료 전환 시 확인 사항

## 현재 상태
코드는 fixture 데이터로 끝까지 동작한다. 외부 API 키, 이메일 도메인, 배포, 결제는 계정 소유자만 할 수 있어 미완이다. 특히 `app/ingest/bizinfo.py` 의 필드 매핑은 실제 응답으로 검증해야 한다.
