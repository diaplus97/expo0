"""서비스 전역 설정. 모든 값은 환경변수(.env)로 주입한다."""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- 기본 ---
    app_name: str = "지원사업 레이더"
    base_url: str = "http://localhost:8000"          # 이메일 링크 생성용 (배포 후 실제 도메인)
    secret_key: str = "change-me"                    # 토큰 서명용
    database_url: str = "sqlite:///./radar.db"
    admin_key: str = "change-me-admin"               # /admin 접근 키

    # --- 수집 소스 ---
    # fixture: 로컬 샘플 데이터 (개발/테스트). 실제 운영은 "bizinfo,kstartup" 등 콤마 구분.
    ingest_sources: str = "fixture"
    bizinfo_api_key: str = ""                        # 기업마당 오픈API 인증키 (bizinfo.go.kr 에서 발급)
    bizinfo_api_url: str = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
    datago_api_key: str = ""                         # 공공데이터포털(data.go.kr) 서비스키
    kstartup_api_url: str = ""                       # 공공데이터포털에서 확인한 K-Startup 공고 API 엔드포인트

    # --- 매칭(LLM) ---
    scorer: Literal["mock", "anthropic"] = "mock"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"   # 비용 우선. 품질 필요 시 sonnet 계열로 교체
    max_llm_candidates_per_user: int = 25            # 하루 1인당 LLM 채점 상한 (비용 상한)
    min_score_to_notify: int = 55                    # 이 점수 미만은 알림에서 제외

    # --- 이메일 ---
    email_backend: Literal["console", "resend", "smtp"] = "console"
    email_from: str = "지원사업 레이더 <noreply@example.com>"
    resend_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # --- 요금제 ---
    free_max_items_per_digest: int = 3
    pro_price_krw: int = 9900
    payment_link_url: str = ""                       # 결제 페이지 URL (토스페이먼츠 등 연동 전엔 비워 둠)


@lru_cache
def get_settings() -> Settings:
    return Settings()
