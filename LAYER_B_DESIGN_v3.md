# 정보 재조직 공간 (레이어 B) — 구체 구현 설계서 v3

> 확정 결정: ① 선별 게이트 = 순수 점수 함수(외부 호출 0), 단위 = 글당 1~5개
> ② TopicEdge = 동시출현 + 임베딩 근접 ③ 통합(InsightBundle)은 1차 제외.
> 본 문서는 각 부분의 **코드 구조 + 전체 코드와의 상호작용 + 연결 지점 + 변수 의존성**까지 분석한다.

---

## 0. 시스템 맥락 — 어디에 끼어드는가

```
사용자 생각 입력
   │
   ▼
post_service.create_post()
   │  ① 페르소나 변환(PersonaAI.respond) → content_transformed
   │  ② Post 저장 + ImportanceScore 0-init
   │  ③ _ingest_post(): leukocyte.assess_post + mediator.tag_and_restructure
   │       → content_emb(임베딩) 세팅, EthicsAssessment, 분배
   │  ④ translation_service.translate_post()  ← 레이어 A
   │  ⑤ ★ knowledge_service.consider_post()  ← 레이어 B 진입점 (신규)
   ▼
[레이어 B 공간]
   consider_post → 단위 추출(1~5) → 선별 게이트 → (통과)보존 / (탈락)흘려보냄
       │ 보존 시
       ├─ update_topic_edges()   주제 연관 그래프 갱신
       └─ build/refresh pool      대화 풀 갱신
   ▼
페르소나 대화 (dialogue WS)
   prompts.build_dialogue_messages(topic_offsets=…, ★context=…)
       │  feedback_service.get_topic_offsets()  (기존)
       └─ ★ knowledge_service.fetch_context()   (신규) — 참조 데이터 주입
   ▼
감독 AI (standby tick + 트리거)
   central / technician / leukocyte
```

레이어 B는 **두 지점에서만 본체와 연결**된다:
- **쓰기 연결**: `create_post()` 끝 ⑤ — 게시 직후 `consider_post()` (best-effort, 실패해도 게시는 성공)
- **읽기 연결**: `build_dialogue_messages()` — 페르소나가 대화할 때 `fetch_context()` 로 참조 데이터 주입

→ 본체 코드 수정은 **두 함수에 각 1줄**. 나머지는 전부 신규 모듈. 결합도 최소.

---

## 1. 순수 코어 `ai/knowledge/` (외부 호출 0)

### 1-1. `extraction.py` — 단위 추출 (글당 1~5개)

```python
@dataclass(frozen=True, slots=True)
class RawUnit:
    gist: str            # 핵심 생각 한 토막
    span: tuple[int,int] # 원문 내 위치(추적성)

def extract_units(text: str, *, max_units: int = 5) -> list[RawUnit]:
    # 규칙 기반: 문장/줄 분할 → 의미 있는 토막 1~5개.
    # 짧은 글=1개, 여러 생각이 담긴 글=최대 5개.
```

**변수 의존성**:
- `max_units` (기본 5) — 글당 단위 상한. ↑면 더 잘게 쪼갬(풀 다양성↑, 노이즈·중복↑). config `knowledge_max_units_per_post`.
- 입력 `text` = `Post.content_transformed` (페르소나 변환문). 원문(`content_raw`)이 아니라 **변환문**을 쓰는 이유: 사용자의 거친 생각이 아니라 페르소나가 정제한 표현이 재조직 대상이라서.

### 1-2. `selection.py` — 선별 게이트 (핵심)

```python
@dataclass(frozen=True, slots=True)
class SelectionSignals:
    genuine_read: bool      # plaza cadence.is_genuine_read 결과
    importance: float       # ImportanceScore.normalized [-1,1]
    novelty: float          # [0,1] 기존 단위와의 거리(멀수록↑)
    topic_fit: float        # [0,1] 기존 주제와의 응집(맞을수록↑)
    redundancy: float       # [0,1] 거의 같은 단위 존재(높을수록↓)

# 가중치 (config + central autotune 대상)
W_READ, W_IMP, W_NOV, W_FIT, W_RED = 0.20, 0.25, 0.30, 0.15, 0.40
RETENTION_THRESHOLD = 0.45   # 이 미만이면 흘려보냄

def retention_score(s: SelectionSignals) -> float:
    base = (W_READ*(1.0 if s.genuine_read else 0.0)
            + W_IMP*max(0.0, s.importance)
            + W_NOV*s.novelty
            + W_FIT*s.topic_fit)
    return max(0.0, base - W_RED*s.redundancy)

def should_retain(s: SelectionSignals, threshold=RETENTION_THRESHOLD) -> bool:
    return retention_score(s) >= threshold
```

**변수 의존성 (무엇이 변하면 결과가 달라지나)**:
| 변수 | 출처 | ↑ 일 때 효과 |
|---|---|---|
| `genuine_read` | `ai/plaza/cadence.is_genuine_read(dwell, len)` | 진짜 읽힌 글만 보존 → 노이즈 차단 |
| `importance` | `ImportanceScore.normalized` (leukocyte가 갱신) | 중요한 글 보존↑ |
| `novelty` | 신규 단위 임베딩 vs 기존 단위 최소 코사인거리 | 새로운 사고 보존↑ (목적①) |
| `topic_fit` | 기존 TopicEdge/클러스터와의 근접 | 맥락 있는 글 보존↑ |
| `redundancy` | 기존 단위와 임베딩 ≥ 임계 유사 개수 | 중복 글 탈락↑ |
| `RETENTION_THRESHOLD` | config | ↑면 적게 보존(엄격), ↓면 많이 보존(노이즈↑) — **central이 통과율 보고 autotune** |

novelty·topic_fit·redundancy는 **임베딩 거리**에서 나오므로, `EmbeddingProvider` 품질이 바뀌면 이 값들이 전부 달라진다. (embedding_provider stub→실모델 교체가 선별 품질에 직접 영향.)

### 1-3. `edges.py` — 주제 연관성 (동시출현 + 임베딩 근접)

```python
CO_OCCUR_WEIGHT = 1.0     # 한 글에 두 주제 동시 등장
EMB_PROX_WEIGHT = 0.5     # 두 주제 단위 임베딩이 근접
DECAY = 0.98              # 시간 경과 가중치 감쇠

def edge_delta(co_occurred: bool, emb_proximity: float) -> float:
    # emb_proximity ∈ [0,1] = 1 - cosine_distance
    return (CO_OCCUR_WEIGHT if co_occurred else 0.0) + EMB_PROX_WEIGHT*emb_proximity

def decayed(weight: float, ticks: int) -> float:
    return weight * (DECAY ** ticks)
```

**변수 의존성**:
- `co_occurred`: 같은 Post에서 추출된 두 단위의 태그가 다르면 동시출현. 태그 출처 = `mediator.tag_and_restructure` 결과(`PostTag`).
- `emb_proximity`: 단위 임베딩 코사인. embedding_provider 의존.
- `DECAY`: standby tick마다 적용. ↑(1에 가까움)면 오래된 연관 유지, ↓면 빨리 잊음. tick 주기와 곱해져 실제 망각 속도 결정.

---

## 2. 데이터 모델 (신규 5종) + 마이그레이션 0014

| 모델 | PK/제약 | FK | 변하는 값 / 무엇이 바꾸나 |
|---|---|---|---|
| `KnowledgeUnit` | id | post_id→posts, persona_id→personas | `embedding`(추출 시 1회), `retention_score`(보존 시점 고정), `visibility`(post에서 상속) |
| `TopicEdge` | (topic_a, topic_b) UNIQUE | — | `weight`(consider/standby마다 갱신·감쇠), `last_seen_at` |
| `ConversationPool` | id | — | `unit_ids`/`size`(build 시), `freshness`(tick 감쇠), `last_served_at`(fetch 시) |
| `PersonaContextRef` | id | persona_id, pool_id | `relevance`, `last_used_at`(fetch_context 호출마다) |
| `KnowledgeAudit` | id | — | append-only. 감독 AI가 행동할 때만 insert |

전부 `visibility` 상속 — `Post.visibility == PRIVATE`면 그 단위/풀은 비공개 경계 내에서만. (fetch_context는 요청 페르소나의 권한 안에서만 반환.)

**기존 테이블 영향**: 신규 테이블만 추가, 기존 스키마 **변경 없음**(post_translations처럼 가산). 마이그레이션 0014 = create_table ×5 + 인덱스. 0013에 의존.

---

## 3. 서비스 `knowledge_service.py`

### 3-1. `consider_post(db, post_id)` — 쓰기 진입점

```
post 로드 → extract_units(content_transformed, max_units=5)
 → 각 단위: embed_one(gist)  [EmbeddingProvider]
 → SelectionSignals 조립:
     genuine_read = (post.read_count 기반 또는 cadence)
     importance   = ImportanceScore.normalized (SELECT)
     novelty      = 1 - max_cosine(신규 emb, 최근 KnowledgeUnit emb들)
     topic_fit    = 기존 TopicEdge/태그 근접
     redundancy   = (cosine ≥ REDUNDANCY_SIM 인 기존 단위 수) 정규화
 → should_retain? 
     예 → KnowledgeUnit insert + update_topic_edges + pool refresh + audit
     아니오 → skip (아무것도 안 남김, 반환값에 skipped 표시)
```

**상호작용**:
- 입력은 `create_post()`가 이미 만든 `Post`(+content_emb, +ImportanceScore). **레이어 B는 읽기만** 하고 본체 상태를 안 바꿈 → 게시 트랜잭션과 분리(별도 commit), 실패해도 게시 영향 0.
- `EmbeddingProvider`: 글 임베딩(`post.content_emb`)은 글 전체 1개. 단위는 1~5개라 **단위별 임베딩을 새로 계산**(embed_one ×N). N≤5라 비용 제한적.

**변수 의존성**:
- `REDUNDANCY_SIM` (기본 0.92): 이 이상 유사하면 중복 1개로 카운트. ↑면 중복 판정 느슨(더 보존), ↓면 엄격.
- `novelty 비교 대상 범위`: "최근 N개 단위" — N(window) ↑면 더 넓게 비교(novelty 엄격), 비용↑.

### 3-2. `fetch_context(db, persona_id, topic, language)` — 읽기 진입점

```
주제 topic의 ConversationPool 조회
 → TopicEdge로 한 다리 건넌 연관 주제의 풀도 일부 포함 (목적③)
 → 각 풀의 단위를 수신자 language로 (translation_service.get_post_in_language 재사용)
 → 권한/visibility 필터 (비공개 누출 차단)
 → PersonaContextRef 기록(relevance, last_used_at)
 → ContextBundle 반환 (요약 아님 — 참조 재료 목록)
```

**상호작용 (핵심 연결)**:
- `prompts.build_dialogue_messages()` 에 이미 `topic_offsets`(feedback)가 주입되는 자리 옆에 **`context`(knowledge)도 주입**. 즉 페르소나 프롬프트는 (a)인지 분석 (b)feedback 성향 (c)★knowledge 참조 3층.
- `fetch_context`는 동기 LLM 호출 없음(조회+번역만). 번역은 이미 저장된 post_translations 사용.

**변수 의존성**:
- `topic` = 현재 대화에서 추출된 주제(인지 파이프라인 `info.topics`). 대화 내용이 바뀌면 fetch 대상 풀이 바뀜.
- `language` = `persona.preferred_language` 또는 수신자 설정. 바뀌면 반환 언어 버전이 바뀜.
- `EDGE_HOP_LIMIT`(기본 1): 연관 주제 몇 다리까지. ↑면 더 폭넓은 참조(유연성↑, 산만↑).
- `POOL_SERVE_LIMIT`: 한 번에 주는 단위 수. 프롬프트 길이와 직결.

---

## 4. 감독 AI 3종 — standby + 트리거 + α

### 연결: 기존 서비스 확장 (신규 AI 아님)

| AI | standby (tick) | 트리거 | +α | 재사용 자산 |
|---|---|---|---|---|
| **중앙관리자** | 공간 건강도(풀 다양성·엣지 균형·**선별 통과율**) 점검 → 통과율 보고 `RETENTION_THRESHOLD` autotune | 통과율 이상 급변 시 즉시 | 공간 리포트(digest) | `central.compute_verdict`/`render_digest`/`autotune`(W_MIN/W_MAX/MAX_STEP 가드레일) |
| **기술자** | 단위↔post 정합, 임베딩/엣지 무결성, 풀 손상 점검·복구 | 새 단위 보존 시 즉시 서명 | 참조 재현성(어느 풀을 왜 줬는지) | HMAC 해시체인, `AuthorityState` |
| **백혈구** | 보존 단위/풀 윤리 재검사 | 새 단위 보존 시 즉시, 비공개 누출 시도 시 즉시 차단 | 합성 위험(비위험×비위험→위험) 탐지 | 13-카테고리 `assess`, `screen_response`, `_category_block` |

### standby 구현 — 기존 tick 패턴 재사용

`plaza_service.tick(db)` 와 동일 패턴: 외부 크론이 `POST /v1/admin/knowledge/tick` 호출 → 한 번의 bounded 점검 실행. **CI(Docker)에서 동작**, 순수 환경에선 호출 안 됨.

```
knowledge_tick(db):
  central:    통과율 집계 → autotune(threshold)  + digest 갱신
  technician: 무결성 스캔 → 손상 복구 + 서명
  leukocyte:  최근 보존 단위 N개 재검사 → 위험 시 suppress + audit
  edges:      decay 적용 (DECAY ** 1)
```

**변수 의존성**:
- tick **주기**(외부 크론) × `DECAY` = 실제 망각 속도. 크론 1종 통합(결정③).
- `통과율` = retain된 수 / consider된 수. 이게 목표대(예: 0.3~0.5) 벗어나면 중앙관리자가 threshold 조정 → 다음부터 선별 결과 달라짐. **피드백 루프**(autotune 가드레일로 발산 방지).

### 트리거 구현

`consider_post` 내부에서 단위 보존 직후 동기 호출:
- `leukocyte.screen_unit()` (차단 시 보존 취소)
- `technician.sign_unit()` (서명 부여)
표준 fail-open: 트리거 검사 자체가 에러나면 보존은 유지하되 audit에 기록.

---

## 5. 라우트 (신규)

| 라우트 | 용도 | 권한 |
|---|---|---|
| `GET /v1/personas/{id}/context?topic=&lang=` | 페르소나 참조 데이터 조회 | 소유자 |
| `POST /v1/admin/knowledge/tick` | standby 1회 실행 | admin |
| `GET /v1/admin/knowledge/report` | 공간 리포트(digest) | admin |
| `GET /v1/admin/knowledge/audit` | 감사 로그 | admin |

dialogue WS는 내부적으로 `fetch_context`를 직접 호출(라우트 경유 아님).

---

## 6. 변수 의존성 전체 지도 (무엇→무엇)

```
embedding_provider 품질 ──┬─→ novelty ──┐
                          ├─→ redundancy ┼─→ retention_score ─→ should_retain ─→ 보존율
                          └─→ topic_fit ─┘                              │
ImportanceScore.normalized ───────────────→ retention_score            │
plaza cadence.is_genuine_read ────────────→ retention_score            │
RETENTION_THRESHOLD ──────────────────────────────────────────────────┤
   ▲                                                                   │
   └── central autotune ←── 선별 통과율 ←──────────────────────────────┘  (피드백 루프)

mediator 태그(PostTag) ─→ co_occurred ─┐
embedding 근접 ─────────→ emb_proximity ┼─→ edge_delta ─→ TopicEdge.weight ─→ fetch_context 연관범위
tick 주기 × DECAY ──────────────────────────────────→ TopicEdge.weight 감쇠

대화 내용 → info.topics → fetch_context(topic) ─→ 참조 풀 선택
persona.preferred_language → fetch_context(lang) ─→ 반환 언어(post_translations)
EDGE_HOP_LIMIT / POOL_SERVE_LIMIT → 참조 폭·프롬프트 길이
```

---

## 7. 1차 구현 순서 (통합 제외)

1. 순수 코어 `ai/knowledge/` (extraction/selection/edges) + 순수 테스트 — **DB 불필요, 먼저 검증**
2. 모델 5종 + 마이그레이션 0014
3. `knowledge_service`: consider_post / update_topic_edges / build_pools / fetch_context
4. 감독 연결: knowledge_tick(central/technician/leukocyte) + consider 내부 트리거
5. 본체 연결 2줄: `create_post` 끝 + `build_dialogue_messages`
6. 라우트 4종
7. 테스트: 선별 통과/흘려보내기 경계, novelty 가산, redundancy 감점, 엣지 가중치, 비공개 누출 차단, 참조 기록, tick autotune

**1단계(순수 코어)는 외부 호출·DB 0이라 이 환경에서 완전 검증 가능.** 2~6은 코드+정적검증(ruff/mypy)+순수 테스트, DB 통합은 CI.
