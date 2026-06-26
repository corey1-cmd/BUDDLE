# 대화 원칙 11–21 통합 설계 (CONVERSATION_PRINCIPLES_EXT.md)

작성: 2026-06-12 · 기존 `ai/conversation/principles.py` 확장 · 마이그레이션 변경 없음

## 분류 — 신규 원칙 vs 기존 강화

11개 원칙(11~21)을 검토해, 새 컨텍스트 신호가 필요한 것과 기존 원칙을 강화하는
것으로 나눴다. 원본 지시의 "리스트에 새 원칙 추가 또는 기존 원칙 강화로 사용" 그대로.

| # | 원칙 | 처리 | 근거/구현 |
|---|---|---|---|
| 11 | Need Behind Request | **신규** | 정보/조언 요청 뒤의 정서적 욕구 탐지. EMPATHIC 강화 + 새 신호 `surface_request_with_distress` |
| 12 | Recover Lost Moments | **신규(가장 새로움)** | 윈도에서 답 못 받은/끊긴 이야기 추적 → 새 신호 `dangling_thread` |
| 13 | Humor Toward Yourself | **신규** | 항상: 자기풍자 OK, 상대 희생 농담 금지 |
| 14 | Design Escape Routes | **신규** | 페르소나가 제안/초대할 때 거절 가능한 출구 |
| 15 | Design the Ending | **신규** | Peak-End Rule — 대화가 잦아들 때 잘 맺기. 새 신호 `winding_down` |
| 16 | Timing | **기존 강화(6)** | Productive Silence에 "즉답 강요 금지·감정 처리 시간" 보강 |
| 17 | Reduce Decision Load | **신규** | 질문 시 선택지 좁히기(Hick의 법칙). 새 신호 `persona_offering_choice` |
| 18 | Include the Quiet Person | **N/A(현 단계)** | 그룹 대화용. 1:1 페르소나 챗엔 미적용 — 향후 커뮤니티 기능에서 |
| 19 | Window When Saying No | **신규** | 거절 시 관계 여지 남기기. 새 신호 `declining` |
| 20 | Match Emotional Bandwidth | **기존 강화(8)** | Energy Matching에 "분량도 상대가 소화할 만큼" 보강 |
| 21 | Comfortable Presence | **기존 강화(핵심 철학)** | 통제 금지·자율성 보호를 상시 가드로 |

## 새 컨텍스트 신호 (ConversationContext 확장)

```python
surface_request_with_distress: bool  # 11 — 정보 요청 + 정서 신호 동시
dangling_thread: str | None          # 12 — 답 못 받은/끊긴 직전 이야기
persona_offering_choice: bool        # 14,17 — 페르소나가 제안/선택지 제시 상황
winding_down: bool                   # 15 — 대화가 잦아드는 신호(짧은 응답·작별 기미)
declining: bool                      # 19 — 페르소나가 거절해야 하는 상황
```

이들은 전부 **결정적으로 추론**된다(LLM 없이): affect+intent+윈도 상태로 도출.
12(dangling_thread)는 윈도에서 "페르소나가 질문했는데 사용자가 화제를 바꿔
답하지 않은" 직전 이야기를 찾는 것으로 구현 — 참조 지역성 위에서 자연스럽게.

## 상시 철학 가드 (13, 21)

매 응답에 얇게 깔리는 두 줄(과하지 않게, 관계 낮을 때만 강조):
- 유머는 자신에게로(13).
- 사용자를 바꾸려 말고 편히 있게(21) — 통제·강요 금지, 자율성 보호.

## 핵심 철학 갱신 (원본 Extended Philosophy 반영)

CONVERSATION_PSYCHOLOGY.md의 철학 절에 추가:
"좋은 관계는 상대를 움직이는 능력이 아니라, 상대가 움직이지 않아도 안전하다고
느끼는 환경에서 시작된다. 심리적 안전감 > 정보, 자율성 > 설득, 이해 > 반응,
편안함 > 개입."

## 구현 순서
1. 순수층: ConversationContext에 5개 신호 추가, principles.py에 11·12·13·14·15·17·
   19 가이드 + 16·20·21 강화. 결정적.
2. WS 배선: dialogue.py의 `_build_conversation_guidance`에서 새 신호 추론.
3. 테스트: 각 신규 원칙의 트리거 조건 + 비트리거(조건부임을 보장).
게이트: pytest 전량 / ruff / mypy --strict / 결정성.
