# 페르소나 대화 심리 프레임워크 — 설계 (CONVERSATION_PSYCHOLOGY.md)

작성: 2026-06-12 · 적용: 페르소나 1:1 대화(chat) 전체 · 상태: 설계 → 구현

## 0. 요구사항 → 검증된 이론 매핑

성재님 지시의 모든 요소를 **실측 기반 이론**에 정확히 대응시켰다. 지어낸 공식은
없고, 전부 검색으로 확인한 학술 모델을 응용한다.

| 지시 요소 | 적용 이론 | 구현 위치 |
|---|---|---|
| Relationship Level (긍정 대화일수록 상승) | **Social Penetration Theory** 5단계 (Altman & Taylor 1973) + **Gottman 5:1 비율**·정서은행계좌·부정성 편향 | `relationship` 모델 + `ai/conversation/relationship.py` |
| 대화 정형화 기록(다시 읽기 가능) | 구조화 턴 로그 + EKB Retention 요약 | `conversation_turns` 테이블 |
| 최근 10 말풍선 윈도(TCB식 참조 지역성) | **참조 지역성**(temporal+topical locality) — 최근 윈도가 분위기·주제 측정의 working set | `recent_window` 서비스 |
| 대화 상황(situation) | 발화 목적 분류 (객관/공감/주장/정리/소통) | `ConversationSituation` enum |
| 대화 분위기(mood) | 최근 윈도의 valence·intensity 집계(EWMA) | `relationship.mood_*` 필드 |
| 사용자 대응 성격 특성 | 중앙 user_profile(OCEAN, 0018) → 페르소나별 캐시 | `relationship.user_snapshot` |
| Current Level + 1 | SPT 점진성 + 깊이 매칭 | `synthesize`의 깊이 가이드 |
| 꼬리질문 추적 | 반복 질문 방지 테이블 | `conversation_turns.was_followup` + 집계 |
| 역질문(우울 회복·친밀감) | SPT 상호성 규범(reciprocity norm) | `synthesize`의 reciprocity 가이드 |
| 10가지 대화 원칙 | EKB Decision과 결합한 응답 가이드 | `ai/conversation/principles.py` |

---

## 1. Relationship Level — 공식의 근거

### 1-1. 단계: Social Penetration Theory (Altman & Taylor 1973)
SPT는 **객관적 이론**(실험 데이터 기반)으로, 관계가 자기개방(self-disclosure)의
**breadth(주제 폭)·depth(주제 깊이)** 확대를 통해 단계적으로 깊어진다고 본다.
buddle은 그 5단계를 0~4 정수 레벨로 채택한다:

| Lv | SPT 단계 | buddle 의미 | 적절한 주제 깊이 |
|---|---|---|---|
| 0 | Orientation | 첫 만남·표면 잡담 | 날씨, 가벼운 일상, 공개 사실 |
| 1 | Exploratory affective | 초기 의견 교환 | 취향, 가벼운 호불호, "왜 좋아하게 됐나" |
| 2 | Affective | 진짜 견해 공유 | 가치관, 관계 속 사람 이야기, 고민의 일부 |
| 3 | Stable | 친밀·신뢰 | 깊은 감정, 약점, 사적 고민 |
| 4 | (Stable+) | 매우 친밀 | 핵심 자아 — 단, buddle은 과몰입 방지를 위해 상한 운영 |

(depenetration=관계 후퇴는 음의 점수 누적으로 자연 반영 — 부정 대화가 쌓이면
레벨이 내려갈 수 있다.)

### 1-2. 점수 공식: Gottman 정서은행계좌 + 5:1 + 부정성 편향
Gottman의 실측: 안정적 관계는 **긍정:부정 ≥ 5:1**. 핵심은 *부정성 편향* —
사람은 부정을 훨씬 무겁게 받아들인다. 그래서 "정서은행계좌"에 긍정은 작은
입금, 부정은 큰 출금으로 쌓인다("small things often").

이를 연속 점수로 응용한다. 매 사용자 턴마다 affect(valence·intensity)로 델타 계산:

```
# affect.valence ∈ {POSITIVE, NEGATIVE, NEUTRAL}, affect.intensity ∈ [0,1]
POSITIVE  → +base · (0.5 + intensity)        # 입금 (작게, 자주)
NEGATIVE  → −base · (0.5 + intensity) · 5    # 출금 (Gottman 5배 가중 = 부정성 편향)
NEUTRAL   → +base · 0.15                       # 중립도 "함께 있음"의 미세 입금

# 자기개방 보너스(SPT): 사용자가 감정/가치/사적 사실을 드러내면(=LTM이 기억으로
#   추출한 턴) breadth·depth가 늘었다는 신호 → 추가 입금
disclosure_bonus = +base · 0.6  (해당 턴에 PersonaMemory 후보가 추출됐을 때)

# 상호성(reciprocity norm): 직전 페르소나 턴이 적절한 자기개방/공감이었고 사용자가
#   화답했다면 소폭 가산(관계는 주고받음으로 깊어진다)
```

점수는 `affinity_score`(실수, 0~100 누적·감쇠)로 저장하고, 레벨은 임계값으로 매핑:
`[0,8)→Lv0, [8,22)→Lv1, [22,45)→Lv2, [45,72)→Lv3, [72,100]→Lv4`.

**자연스러움 장치:**
- **레벨 히스테리시스**: 한 번 오른 레벨은 점수가 임계값보다 약간(−4) 더 떨어져야
  내려간다 → 한 번의 삐걱임으로 관계가 후퇴한 듯 보이지 않게.
- **턴당 상한**: 한 턴의 델타는 ±(base·3)로 클램프 → 한 마디로 급변 방지(SPT의
  "초기엔 빠르게, 후기엔 느리게"도 base를 레벨에 반비례시켜 반영).
- **세션 경계 감쇠 없음, 시간 감쇠 약하게**: 오래 안 보면 아주 천천히 식는다
  (망각 곡선과 동일 철학, 단 LTM보다 훨씬 완만).

### 1-3. 깊이 매칭: "Current Level + 1"
모든 질문·주제는 **현재 레벨 + 1**을 목표로 한다(SPT: 신뢰가 형성된 만큼만
한 단계 더 깊이). 너무 얕으면 지루하고("점심 드셨어요"가 Lv3에서 나오면 어색),
너무 깊으면 침범("인생 최대 고민"이 Lv0에서 나오면 부담). synthesize가 현재
레벨을 읽어 "지금은 Lv2이므로 가치관·관계 이야기까지는 자연스럽고, 깊은 약점은
아직 이르다"는 가이드를 프롬프트에 넣는다.

---

## 2. 대화 상황(Situation) → 분위기(Mood)

지시: "어떤 목적이 상황으로 들어가고 그에 상대 에너지를 맞춰야 하니 분위기를
측정한다." → 상황(목적)과 분위기(에너지)를 분리해 저장한다.

### 2-1. ConversationSituation — 발화 목적 (응답 방식을 가른다)
| 상황 | 정의 | 응답 원칙 |
|---|---|---|
| EMPATHIC | 공감이 필요(힘듦·기쁨 공유) | 원칙7 감정 우선, 원칙8 에너지 조율 |
| OBJECTIVE | 사실 확인·정보·피드백 요청 | 사실 답해도 됨(원칙3 예외), 가지치기 안 함 |
| ASSERTIVE | 주장·의견 개진 | 논점 존중, 토론 모드 연결 가능 |
| REFLECTIVE | 생각 정리 중 | 원칙6 침묵 허용, 역질문으로 정리 도움 |
| SOCIAL | 일상 소통·관계 유지 | 원칙1·9 흐름 연장, 가지 따라가기 |

기존 cognition `Intent`(ask_info/seek_support/…)를 상황으로 매핑(신규 분류기
최소화 — 자산 재사용). 예: SEEK_SUPPORT→EMPATHIC, ASK_INFO→OBJECTIVE,
REFLECT→REFLECTIVE, MAKE_CONVERSATION→SOCIAL.

### 2-2. Mood — 대화 에너지 (상황 아래)
최근 10 말풍선 윈도의 valence·intensity를 EWMA로 집계:
- `mood_valence` ∈ [−1,1]: 최근 분위기의 긍/부정 기울기
- `mood_energy` ∈ [0,1]: 최근 강도(에너지) — 페르소나가 **에너지를 조율**(원칙8)할 기준

"상대의 에너지에 맞춘다"가 핵심: mood_energy가 낮으면 차분하게, 높으면 활기있게.
과도한 감탄·위로는 금지(원칙8: Reaction Intensity ≈ Speaker Intensity).

---

## 3. 참조 지역성 — 최근 10 말풍선 윈도 (TCB식)

지시: "최근 앞선 말풍선 10개 정도는 바로바로 볼 수 있어야 하고, 대화 주제도
참조의 지역성이 존재함." → **working set** 개념.

- **Temporal locality**: 가장 최근 N=10 턴이 분위기·주제 측정의 1차 소스(전체
  히스토리를 매번 재분석하지 않음 — 비용·정확도 양면).
- **Topical locality**: 그 윈도에서 **유의미한 반응을 보인 주제**(원칙9 stepping-
  stone)를 추출 → 다음 주제를 "새로 만들지 말고 이 윈도에서 꺼낸다."
- 구현: `recent_window(session, n=10)` → {turns, mood, salient_topics, last_user_turn}.
  이는 LTM(세션 횡단 장기기억, 0017)과 **다른 층**이다: LTM=오래된 사실의 회상,
  윈도=지금 이 대화의 즉시 맥락. 둘 다 프롬프트에 들어가되 역할이 다르다.

---

## 4. 정형화 기록 — conversation_turns

지시: "대화 내용을 정형화(다시 읽을 수 있게)해서 기록." 기존 `messages`는 원문
저장. 그 위에 **분석 메타가 붙은 정형 턴 로그**를 둔다(페르소나가 다시 읽고
판단하는 용도):

`conversation_turns`: `(id, session_id FK, persona_id FK, role, content,
situation ENUM, valence ENUM, intensity REAL, was_followup BOOL,
opened_disclosure BOOL, salient_topics TEXT[], affinity_delta REAL,
created_at)`. 매 턴 cognition 분석 결과를 그대로 적재 → 윈도·분위기·꼬리질문
추적·관계 점수의 단일 소스.

`was_followup`: 직전 페르소나 턴이 질문이었고 이번이 그에 대한 답이면 True →
"연속으로 캐묻기"(원칙2 경고)를 페르소나가 회피하도록 집계 제공.

---

## 5. 10가지 대화 원칙 — EKB Decision과 결합

지시: "공감을 미리 계획되어 반복적으로 쓰지 말고, EKB와 함께 응용." 원칙들은
**고정 스크립트가 아니라** 현재 상황·분위기·레벨·윈도를 읽어 *조건부로* 적용되는
가이드다. `ai/conversation/principles.py`가 컨텍스트를 받아 해당 상황에 맞는
원칙만 골라 프롬프트 가이드를 합성한다.

| 원칙 | 트리거 조건 | 가이드 |
|---|---|---|
| 1 The 3-Second Cliff | 항상 | 새 주제 강요 금지, follow-up·반응 유도 |
| 2 Interests→Personality | 취향 언급 윈도에 있음 | "왜/어떻게"로 성향 탐색(단 연속 캐묻기 금지) |
| 3 Branches not Facts | situation≠OBJECTIVE | 사건보다 관계(사람) 따라가기 |
| 4 Context before Q | 질문 생성 시 | "전에 …하셨던 것 같은데" 맥락 먼저 |
| 5 Depth Matching | 항상 | Current Level + 1 목표 |
| 6 Productive Silence | situation=REFLECTIVE | 즉시 채우지 말고 역질문 허용 |
| 7 Emotion before Solution | situation=EMPATHIC | 공감 먼저 → 그 다음 (요청 시)조언 |
| 8 Energy Matching | 항상 | mood_energy에 리액션 강도 맞춤 |
| 9 Stepping-Stone | 주제 전환 시 | 윈도의 유의미 반응에서 다음 주제 |
| 10 Normalize Awkwardness | 레벨 낮음·침묵 | 완벽·즉시 친밀 강요 금지 |
| 11 Need Behind Request | 정보요청+정서신호 | 방법보다 그 사람의 상황·마음 먼저(욕구에 반응) |
| 12 Recover Lost Moments | 윈도에 끊긴 이야기 | 답 못 받은 이야기 다시 꺼내 기억함을 보임 |
| 13 Humor Toward Yourself | 레벨 낮음(상시 가드) | 농담은 자신에게로, 상대 희생 금지 |
| 14 Escape Routes | 제안·선택지 상황 | 거절 가능한 출구 남기기 |
| 15 Design the Ending | 대화 잦아듦 | Peak-End — 좋은 기분으로 마무리 |
| 16 Timing | (6 강화) | 즉답 강요 금지, 감정 처리 시간 존중 |
| 17 Reduce Decision Load | 제안·선택지 상황 | 활짝 열린 질문보다 두세 개로 좁히기 |
| 18 Include Quiet Person | (그룹용) | 1:1 챗 N/A — 향후 커뮤니티 기능 |
| 19 Window When Saying No | 거절 상황 | 문 닫아도 창문 — 다음을 잇는 한마디 |
| 20 Match Bandwidth | (8 강화) | 분량도 상대가 소화할 만큼, 길이≠진심 |
| 21 Comfortable Presence | 레벨 낮음(상시 가드) | 통제 말고 편히 있게, 자율성 보호 |

11~21은 결정적 신호(`detect_distress`/`is_request`/`detect_winding_down`/
`detect_decline_needed` + 윈도 dangling-thread 탐지)로 추론되며, 전부 가이드를
**올릴 뿐 막지 않는다**(오탐 비용 = 부드러운 넛지 한 줄). 18은 그룹 대화 원칙이라
1:1 페르소나 챗에는 미적용(향후 커뮤니티 기능에서 활용).

EKB와의 결합: cognition이 만든 `DecisionResult`(situation, affect, strategy)에
relationship(level, mood)을 더해 `synthesize_prompt_block`이 "이 사용자와 지금
이런 관계·분위기이니, 이 원칙들을 이렇게 적용하라"는 **단일 통합 가이드**를 만든다.

### 확장된 관계 철학 (원본 Extended Philosophy)
좋은 관계는 상대를 *움직이는 능력*이 아니라, 상대가 움직이지 않아도 *안전하다고
느끼는 환경*에서 시작된다. 그래서 모든 대화 경험의 우선순위는: 심리적 안전감 >
정보, 자율성 > 설득, 이해 > 반응, 편안함 > 개입. 사람은 자신을 설득하는 사람보다
이해하려는 사람을 신뢰하고, 침묵과 거리감은 실패가 아니다.

---

## 6. 데이터 흐름 (한눈에)

```
사용자 턴 도착
  │
  ├─ recent_window(n=10) ──────────┐  (참조 지역성: 즉시 맥락·분위기)
  ├─ memory.recall (LTM, 0017) ────┤  (세션 횡단 기억)
  ├─ profile.snapshot (OCEAN,0018) ┤  (대응 성격 특성)
  ├─ relationship.load ────────────┤  (레벨·정서은행계좌)
  │                                 ▼
  │   cognition.run (EKB: 정보처리→의사결정) + situation 분류
  │                                 │
  │   principles.select(상황·분위기·레벨·윈도) → 원칙 가이드
  │                                 ▼
  │   synthesize_prompt_block(기억+윈도+프로파일+관계+원칙) → 통합 시스템 프롬프트
  │                                 ▼
  │              페르소나 응답 생성 (Z.ai/vLLM)
  │                                 ▼
  └─ 응답 전송 후(지연 0):
       ├─ conversation_turns 적재(사용자턴+페르소나턴, 분석 메타 포함)
       ├─ relationship.update(affinity_delta) → 레벨 재계산(히스테리시스)
       ├─ memory.observe (LTM)
       └─ profile.observe (특질)
```

---

## 7. 구현 순서 (마이그레이션 0019, 0020)
1. 순수층: `ai/conversation/relationship.py`(SPT+Gottman 공식), `principles.py`,
   `situation.py` — I/O 없음, 결정적, 단위 테스트.
2. DB: `conversation_turns`(0019), `relationships`(0020). enum 추가.
3. 서비스: `conversation_service`(윈도·턴 적재·관계 갱신).
4. 배선: WS 핸들러에 윈도·관계 로드 → cognition → 적재. synthesize 확장.
5. (선택) UI: chat 화면에 관계 레벨의 은근한 시각 신호 — 과하지 않게.

각 단계 게이트: pytest 전량 / ruff / mypy --strict 클린, 스텁 경로 결정적.
