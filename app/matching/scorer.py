"""공고 × 사업 프로필 적합도 채점. 결과는 Score 데이터클래스.

- MockScorer: 키워드/지역 규칙으로 점수를 흉내낸다 (테스트·개발용, 비용 0).
- AnthropicScorer: Claude에게 JSON 한 덩어리로 판정을 받는다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.config import get_settings
from app.db import Announcement, User
from app.matching.prefilter import keyword_hits


@dataclass
class Score:
    score: int                 # 0~100
    eligible: str              # yes | no | unclear
    one_liner: str             # 사장님이 3초 안에 읽을 한 줄
    reasons: list[str]         # 근거 2~4개 (자격 요건, 왜 맞는지/안 맞는지)


SYSTEM_PROMPT = """당신은 소상공인·중소기업 정부 지원사업 컨설턴트다.
주어진 사업 프로필과 공고를 비교해, 이 사업자가 실제로 신청 자격이 되는지와 얼마나 유용한지를 판정한다.

규칙:
- 공고에 없는 요건을 지어내지 않는다. 판단 근거가 부족하면 eligible 을 "unclear" 로 두고 reasons 에 무엇이 불확실한지 쓴다.
- 지역 제한, 업력, 직원 수, 예비창업 여부, 업종 제한을 우선 확인한다.
- score 는 '이 사장님이 신청해서 도움을 받을 가능성' 이다. 자격 미달이면 20 이하.
- one_liner 는 30자 내외, 사장님 입장에서 '무엇을 얼마나 지원받는지'를 쓴다. 광고 문구 금지.
- 반드시 아래 JSON 만 출력한다. 다른 텍스트, 코드블록 금지.

{"score": <0-100 정수>, "eligible": "yes|no|unclear", "one_liner": "<문자열>", "reasons": ["<근거1>", "<근거2>"]}"""


def build_user_prompt(user: User, ann: Announcement) -> str:
    deadline = ann.apply_end.isoformat() if ann.apply_end else "미상"
    return (
        f"[사업 프로필]\n{user.profile_text()}\n\n"
        f"[공고]\n제목: {ann.title}\n기관: {ann.agency}\n지역: {ann.region}\n분야: {ann.category}\n"
        f"지원대상: {ann.target}\n접수마감: {deadline}\n내용:\n{ann.body[:3000]}"
    )


def parse_score(text: str) -> Score:
    """모델 출력에서 JSON 객체를 뽑아 Score 로. 실패 시 unclear/0."""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        d = json.loads(m.group(0) if m else text)
        score = max(0, min(100, int(d.get("score", 0))))
        eligible = d.get("eligible", "unclear")
        if eligible not in ("yes", "no", "unclear"):
            eligible = "unclear"
        reasons = [str(r) for r in d.get("reasons", [])][:4]
        return Score(score, eligible, str(d.get("one_liner", ""))[:300], reasons)
    except (json.JSONDecodeError, ValueError, AttributeError, TypeError):
        return Score(0, "unclear", "", ["모델 응답을 해석하지 못했습니다."])


class MockScorer:
    name = "mock"

    def score(self, user: User, ann: Announcement) -> Score:
        hits = keyword_hits(user, ann)
        base = 45 + min(hits, 3) * 15
        if user.region != "전국" and ann.region == user.region:
            base += 10
        if user.stage == "예비창업" and "예비창업" in (ann.title + ann.target):
            base += 10
        base = min(base, 98)
        return Score(
            score=base,
            eligible="yes" if base >= 60 else "unclear",
            one_liner=f"{ann.category or '지원'} 분야, {ann.agency or '기관'} 공고",
            reasons=[f"키워드 {hits}개 일치", f"지역 조건: 사용자 {user.region} / 공고 {ann.region}"],
        )


class AnthropicScorer:
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        import anthropic  # 지연 임포트: mock 모드에선 불필요

        s = get_settings()
        self.client = anthropic.Anthropic(api_key=api_key or s.anthropic_api_key)
        self.model = model or s.anthropic_model

    def score(self, user: User, ann: Announcement) -> Score:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_prompt(user, ann)}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        return parse_score(text)


def get_scorer():
    s = get_settings()
    return AnthropicScorer() if s.scorer == "anthropic" else MockScorer()
