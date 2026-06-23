# 통합 (InsightBundle) — 상세 설계서

> 레이어 B의 마지막 조각. 선별·연관·풀·참조(이미 구현) 위에서, **가치 있을 때만**
> 여러 단위를 재조합·논리추론·분석해 통합 산출물(InsightBundle)을 만든다.
> 무조건이 아니라 트리거/임계 충족 시에만. 결론을 "강제"하지 않는 선별적 합성.

---

## 1. 상호관계 + 입출력 + 데이터 변환 분석

### 1-1. 데이터 변환 흐름 (글 → 통합)

```
Post.content_transformed (페르소나 정제문)
   │ extract_units (이미 구현)
   ▼
RawUnit ×1~5  ──선별게이트(이미 구현)──▶  KnowledgeUnit (보존된 것만)
   │                                          │ gist, embedding, topic_tags, visibility
   │ update_topic_edges / build_pool (이미 구현)
   ▼
ConversationPool (주제별 단위 묶음)  ←─ PoolUnit ─→ KnowledgeUnit
   │
   │ ★ synthesize_bundle (신규) — 여기가 이번 작업
   │    입력: 한 풀의 단위 N개 (gist 목록 + 태그)
   │    변환: (a) 재조합 — 비슷/대조되는 생각 묶기  (b) 논리추론 — 공통점/긴장/함의 도출
   │          (c) 분석 — 요약 + 추론 흔적(reasoning_trace)
   │    출력: InsightBundle
   ▼
InsightBundle (summary + reasoning_trace + 기여 단위 추적 + status)
   │ 감독 3종 검사 (백혈구 윤리 / 기술자 서명 / 중앙 승인)
   ▼
fetch_context 확장 — 페르소나 대화에 "통합 인사이트"도 참고자료로 제공 (수신자 언어)
```

### 1-2. 입력 (무엇을 받나)

| 입력 | 출처 | 형태 |
|---|---|---|
| pool_id | ConversationPool | 어떤 주제 풀을 통합할지 |
| 단위들 | PoolUnit→KnowledgeUnit | gist[], topic_tags[], embedding[], visibility[] |
| 통합기 | `get_synthesizer()` (신규, 프로토콜) | stub(규칙) ↔ LLM |
| 가중치/임계 | config + central | 언제 통합할 가치가 있나 |

**핵심 입력 제약 (변수 의존성)**:
- **visibility 동질성**: 한 번들의 모든 입력 단위는 **같은 visibility**여야 함. PUBLIC 단위만으로 PUBLIC 번들, PRIVATE는 소유 페르소나 경계 내에서만. (비공개 누출 방지 — 백혈구·중앙 트리거가 재확인.)
- **최소 단위 수** `BUNDLE_MIN_UNITS`(기본 3): 이보다 적으면 통합 안 함(재조합할 게 없음 → 그냥 풀로 충분).
- **풀 freshness/size**: 충분히 크고 신선할 때만 통합 대상(중앙관리자가 tick에서 선택).

### 1-3. 출력 (무엇을 만드나)

`InsightBundle`:
- `summary`: 통합 요약 (여러 단위를 관통하는 핵심)
- `reasoning_trace`: 추론 흔적 (어떻게 그 결론에 도달했는지 — 재현성/감사)
- `contributing_unit_ids`: 기여 단위 추적 (어느 단위에서 나왔나)
- `status`: draft → (백혈구 통과) approved / (차단) blocked
- `language` + 번역: 수신자 언어로 제공 (translation 패턴 재사용)

### 1-4. 기존 코드와의 상호관계 (연결점)

| 연결 | 방향 | 방식 |
|---|---|---|
| `knowledge_service` | 통합 호출처 | `synthesize_bundle(db, pool_id)` 추가 |
| `knowledge_tick` | 상시 통합 | 중앙관리자가 "통합할 가치 있는 풀" 골라 synthesize (트리거 모드) |
| `fetch_context` | 출력 소비 | 번들 요약을 참고자료에 포함(옵션 플래그) |
| 백혈구 `screen_response` | 출력 검사 | 번들 summary 윤리 재검사(재조합 특유 위험) |
| 기술자 `_sign_unit` 패턴 | 출력 서명 | 번들에 HMAC 서명 |
| 중앙 `render_digest` | 모니터링 | 번들 생성/승인/차단 리포트 |
| translation | 출력 다국어 | 번들 summary를 수신자 언어로 |

→ 본체(create_post/dialogue) 추가 수정 **0줄**. 통합은 knowledge_service 내부 + tick에서만 발동. fetch_context만 1개 옵션 플래그 추가.

---

## 2. 상세 구조 (코드)

### 2-1. 순수 코어 `ai/knowledge/synthesis.py`

```python
@dataclass(frozen=True, slots=True)
class UnitView:          # 통합 입력 (DB 비의존 뷰)
    unit_id: str
    gist: str
    tags: tuple[str,...]

@dataclass(frozen=True, slots=True)
class SynthesisPlan:     # 통합 "계획" (LLM 없이 만드는 구조)
    groups: list[list[str]]      # 재조합: 비슷한 unit_id 묶음
    bridge_topics: list[str]     # 가로지르는 주제
    contributing_ids: list[str]

BUNDLE_MIN_UNITS = 3
SIM_GROUP_THRESHOLD = 0.80       # 이 이상 유사하면 같은 그룹

def should_synthesize(unit_count: int, freshness: float,
                      *, min_units=BUNDLE_MIN_UNITS,
                      freshness_floor=0.3) -> bool:
    return unit_count >= min_units and freshness >= freshness_floor

def plan_synthesis(units: list[UnitView],
                   similarity: Callable[[str,str],float]) -> SynthesisPlan:
    # 임베딩 유사도로 단위를 그룹핑(재조합), 태그 합집합(bridge), 기여 추적.
    # 순수: similarity 함수는 주입. LLM 없이 "무엇을 어떻게 묶을지" 결정.

def fallback_summary(plan, units) -> tuple[str, str]:
    # 통합기(LLM) 없을 때 결정적 요약 + reasoning_trace 생성(템플릿).
```

**변수 의존성**:
- `SIM_GROUP_THRESHOLD` ↑ → 더 엄격히 묶음(그룹 많아짐, 각 그룹 응집↑). embedding 품질 의존.
- `BUNDLE_MIN_UNITS` ↑ → 통합 빈도↓(더 큰 풀만). `freshness_floor` ↑ → 오래된 풀 제외.

### 2-2. 통합기 프로토콜 `ai/knowledge/synthesizer.py`

```python
class Synthesizer(Protocol):
    async def synthesize(self, *, topic: str, units: list[UnitView],
                         plan: SynthesisPlan, language: str
                         ) -> tuple[str, str]: ...   # (summary, reasoning_trace)

class StubSynthesizer:   # 결정적: plan + fallback_summary 사용, LLM 0
class LlmSynthesizer:    # vLLM chat/completions; 재조합·추론 프롬프트
def get_synthesizer() -> Synthesizer   # config synthesis_provider
```

**프롬프트(LLM)**: "다음 생각들을 재조합하고, 공통점·긴장·함의를 추론해, 요약과 추론 과정을 분리해 출력하라. 결론을 단정하지 말고 관점을 제시하라." → 결론 강제 방지.

### 2-3. 모델 `db/models/insight_bundle.py` (신규, 마이그레이션 0015)

| 필드 | 의미 |
|---|---|
| id, pool_id(FK), topic | 어느 풀/주제 |
| summary, reasoning_trace | 통합 결과 + 추론 흔적 |
| contributing_unit_ids (Text, CSV) | 기여 단위 추적 |
| language | 원 언어 |
| visibility | 입력 단위 동질 visibility 상속 |
| status (draft/approved/blocked) | 백혈구 검사 결과 |
| integrity_sig | 기술자 서명 |
| created_at |

(번들 번역은 1차에선 on-demand `get_synthesizer`로 충분; 별도 테이블 보류.)

### 2-4. 서비스 확장 `knowledge_service.synthesize_bundle`

```
synthesize_bundle(db, pool_id):
  pool 로드 → PoolUnit→KnowledgeUnit 단위 수집
  visibility 동질성 확인 (혼재 시 PUBLIC만 선택)
  should_synthesize? 아니면 None(통합 안 함)
  plan_synthesis(units, cosine유사도)
  get_synthesizer().synthesize(...) → (summary, reasoning_trace)
  ── 트리거 ──
  백혈구 screen_response(summary): blocked면 status=blocked + audit, 미제공
  기술자 _sign_unit(summary) → integrity_sig
  InsightBundle(status=approved) 저장 + audit
```

### 2-5. tick + fetch_context 통합

- `knowledge_tick`: 중앙관리자가 "통합할 가치 있는 풀"(size≥min, freshness≥floor, 최근 번들 없음) 1~N개 골라 `synthesize_bundle` 호출. → **상시 통합**(트리거 모드).
- `fetch_context(..., include_insights=True)`: 해당 주제의 approved InsightBundle summary를 참고자료에 1개 추가. 기본 False(옵션).

### 2-6. 라우트
- `GET /v1/personas/{id}/insights?topic=` — 주제의 통합 인사이트(승인된 것, 수신자 언어)
- `POST /v1/admin/knowledge/synthesize/{pool_id}` — 수동 통합 트리거(admin)

---

## 3. 검증 계획 (목적 부합)

순수(이 환경): should_synthesize 경계, plan_synthesis 그룹핑·기여추적, fallback_summary 결정성, visibility 동질성 강제, 통합기 stub, 서비스 시그니처, 프롬프트에 "단정 금지" 반영. DB 통합(CI): synthesize_bundle 전체 흐름, 비공개 누출 차단, 번들 status 전이.

## 4. 1차 범위 (이번 작업)
순수 코어(synthesis+synthesizer) → 모델+마이그레이션 0015 → synthesize_bundle + tick 통합 + fetch_context 플래그 → 라우트 → 테스트. (번들 전용 번역 테이블은 보류; on-demand.)
