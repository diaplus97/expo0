# Claude Code 인수인계

이 저장소는 fixture 데이터 + mock 채점 + console 메일로 **끝까지 돌아가는 상태**다 (`python -m pytest -q` 8/8 통과, `python -m app.jobs.daily` 실행 시 데모 메일 출력).
남은 건 외부 연결과 검증이다. 아래 순서대로 Claude Code 에 시키면 된다. 각 블록을 그대로 붙여 넣어도 된다.

## 0. 먼저 읽을 것
```
이 프로젝트의 README.md, docs/PRD.md, HANDOFF.md 를 읽고 구조를 파악해. 그 다음 python -m pytest -q 로 테스트가 통과하는지 확인하고, python -m app.jobs.daily 를 실행해서 console 메일 출력을 보여줘. 아직 아무것도 고치지 마.
```

## 1. 기업마당 API 실제 연결 (사람이 먼저: bizinfo.go.kr 오픈API 신청해서 키 발급)
```
.env 에 BIZINFO_API_KEY 를 넣었어. app/ingest/bizinfo.py 의 BizinfoSource 로 실제 API 를 한 번 호출해서 응답 JSON 1건을 그대로 보여줘. 그 응답의 실제 필드명과 FIELD 매핑을 대조해서 틀린 것을 고치고, 접수기간 문자열 형식이 parse_date_range 로 파싱되는지 확인해. 지역 정보가 어느 필드에 있는지 찾아서 normalize_region 이 제대로 시/도를 뽑는지 샘플 20건으로 검증하고, 안 되면 어댑터를 고쳐. 마지막으로 tests/ 에 실제 응답 1건을 픽스처로 저장한 파싱 테스트를 추가해.
```

## 2. K-Startup 연결 (사람이 먼저: data.go.kr 에서 '창업지원사업 공고' API 활용신청)
```
data.go.kr 에서 받은 K-Startup 공고 API 의 엔드포인트와 샘플 응답을 줄게: [여기에 붙여넣기]. app/ingest/sources.py 의 KSTARTUP_MAPPING 과 DataGoKrSource 를 실제 응답 구조에 맞게 고치고, 1번과 같은 방식으로 검증·테스트를 추가해. INGEST_SOURCES=bizinfo,kstartup 으로 배치를 돌려서 두 소스가 모두 수집되고 중복이 없는지 확인해.
```

## 3. LLM 채점 품질 검수
```
.env 에 ANTHROPIC_API_KEY 를 넣고 SCORER=anthropic 으로 바꿨어. 내 실제 사업 프로필로 사용자 1명을 만들고(프로필: [지역/업종/직원수/업력/설명]) 배치를 돌려서 채점 결과 20건을 표로 보여줘: 제목, score, eligible, one_liner, reasons. 내가 보기에 틀린 판정을 지적할 테니, app/matching/scorer.py 의 SYSTEM_PROMPT 를 고쳐서 다시 채점하고 전후를 비교해. 특히 (1) 공고에 없는 요건을 지어내는지 (2) 지역 제한을 놓치는지 (3) one_liner 가 '얼마를 지원받는지'를 담는지를 본다.
```

## 4. 이메일 발송 (사람이 먼저: Resend 가입 + 도메인 DNS 레코드 추가)
```
EMAIL_BACKEND=resend, RESEND_API_KEY, EMAIL_FROM, BASE_URL 을 .env 에 넣었어. 내 이메일로 가입 → 확인 메일 → 다이제스트까지 실제로 받아보게 해줘. 받은 메일을 Gmail 모바일에서 봤을 때 깨지는 부분을 내가 알려줄 테니 app/notify/templates/digest.html 을 고쳐. 발송 실패 시 배치가 죽지 않고 해당 사용자만 건너뛰도록 run_notify 에 예외 처리를 추가하고 테스트를 써.
```

## 5. 배포
```
docs/DEPLOY.md 대로 [Fly.io | Railway | Render] 에 배포해줘. SQLite 를 영구 볼륨에 두고, 매일 07:00 KST 에 python -m app.jobs.daily 가 도는 크론을 설정해. /health 를 헬스체크로 등록하고, 배포 후 랜딩 페이지 → 가입 → 확인 메일까지 실제 도메인으로 한 번 테스트해.
```

## 6. 결제 (사람이 먼저: 사업자등록 + PG 가입)
```
토스페이먼츠 결제 링크 URL 을 PAYMENT_LINK_URL 에 넣었어. 1단계로는 결제 완료를 내가 관리자 화면에서 수동 처리할 거니까 /admin 에 '이메일로 사용자 검색 → plan 을 pro 로 변경/해제' 기능을 추가해줘 (ADMIN_KEY 로 보호). 2단계로 PG 웹훅으로 자동 전환하는 엔드포인트를 설계만 먼저 보여줘.
```

## 7. 개선 후보 (프로 10명 이후)
- 사용자 셀프 삭제 버튼 (개인정보 삭제 요청 대응)
- 마감 3일 전 리마인더 메일 (pro)
- 카카오 알림톡 채널 (사업자·템플릿 심사 필요)
- 신청서 초안 자동 작성 (유료 부가 서비스)
- Postgres 이전, 채점 병렬화

## 코드 지도
```
app/config.py            환경변수 → Settings
app/db.py                User / Announcement / Match 모델, 세션
app/ingest/base.py       RawAnnouncement DTO, 지역·날짜 정규화
app/ingest/bizinfo.py    기업마당 어댑터 (FIELD 매핑 확인 필요)
app/ingest/sources.py    data.go.kr 범용 어댑터, 픽스처 소스, upsert, run_ingest
app/matching/prefilter.py 규칙 필터 (지역/마감/단계/키워드 정렬)
app/matching/scorer.py   MockScorer, AnthropicScorer, SYSTEM_PROMPT, parse_score
app/matching/run.py      사용자별 채점 실행 (캐시·상한)
app/notify/email.py      console / resend / smtp 백엔드
app/notify/run.py        요금제별 다이제스트 구성·발송
app/notify/templates/    digest.html (메일)
app/web/main.py          FastAPI 라우트
app/web/templates/       base / landing / settings / message / admin / privacy
app/jobs/daily.py        수집→매칭→발송 배치
fixtures/                샘플 공고 8건
tests/test_pipeline.py   8개 테스트
docs/                    PRD, DEPLOY, LEGAL_CHECKLIST
```
