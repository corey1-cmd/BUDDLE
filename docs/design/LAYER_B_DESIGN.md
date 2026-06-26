# 정보 재조직 공간 (레이어 B) — 설계서

> "정보를 재조직해 놓는 공간. 그 안에서 재조합·논리추론·분석이 진행. 메모리/MMU 같은 느낌."
> 중앙관리자·기술자·백혈구 AI가 모니터링·관리. 각 AI는 상시 대기 + 트리거 확인 두 기능 + α.

## 1. 목적과 위치

레이어 A(다국어 생각→글→게시→전달)로 흘러든 글들을, 한 건씩 흘려보내지 않고 **구조화된 공간에 모아 재조합·추론·분석**해서, 매칭되는 사람에게 "주제 하나"가 아니라 **여러 주제를 통합한 정보 풀**을 주는 계층.

비유(사용자 제시): **인간 작업기억 + MMU**. 어떤 정보를 메모리에 올리고(매핑), 재조합하고, 추론하는 관리 계층. CPU(페르소나/매개자)가 직접 디스크(전체 글 DB)를 안 보고, MMU(이 공간)가 필요한 페이지만 올려 가공해 건넨다.

```
레이어 A 산출물(게시글, 공개/비공개) 
        │
        ▼
 ┌──────────────────────────────────────┐
 │  레이어 B: 정보 재조직 공간 (KnowledgeSpace)  │
 │  ┌────────────┐  수집/정규화          │
 │  │ 지식 단위    │ ← 글에서 추출한 원자적 정보  │
 │  │ (KnowledgeUnit)                    │
 │  └────┬───────┘                        │
 │       │ 클러스터링(주제별 묶기)            │
 │  ┌────▼───────┐                        │
 │  │ 클러스터     │ 주제 단위 재조직          │
 │  └────┬───────┘                        │
 │       │ 재조합·논리추론·분석              │
 │  ┌────▼───────┐                        │
 │  │ 통합 산출물   │ → 정보 풀(InsightBundle) │
 │  └────────────┘                        │
 └──────────────────────────────────────┘
        │ 감독 AI 3종이 상시/트리거로 관리
        ▼
   매칭된 사람에게 다주제 통합 정보 풀 전달
```

## 2. 데이터 모델 (신규)

| 모델 | 역할 | 핵심 필드 |
|---|---|---|
| `KnowledgeUnit` | 글에서 추출한 원자적 정보 조각 (MMU의 "페이지") | source_post_id, persona_id, language, claim(핵심 주장), topic_tags, embedding, visibility(공개/비공개 상속), created_at |
| `KnowledgeCluster` | 주제별로 묶인 단위 집합 | centroid_embedding, label, topic, unit_count, last_rebuilt_at |
| `cluster_units` | 클러스터↔단위 다대다 | cluster_id, unit_id, membership_score |
| `InsightBundle` | 재조합·추론으로 만든 통합 산출물(정보 풀) | cluster_id(또는 다중), summary, reasoning_trace, contributing_unit_ids, language, status(draft/approved/blocked), created_at |
| `KnowledgeAudit` | 감독 AI의 모니터링/조치 로그 | actor_ai(central/technician/leukocyte), action, target_type, target_id, verdict, note, created_at |

전부 `visibility`를 글에서 상속 — 비공개 글에서 나온 단위/산출물은 비공개 경계 안에서만 재조합·전달.

## 3. 처리 파이프라인 (순수 코어 + 서비스)

1. **수집(ingest_unit)**: 게시글 → 지식 단위 추출(핵심 주장 + 주제 태그 + 임베딩). 이미 있는 임베딩(pgvector) 재사용.
2. **클러스터링(rebuild_clusters)**: 단위 임베딩으로 주제 클러스터 형성/갱신. 순수 코어는 거리 기반 그룹핑(기존 geo 패턴과 유사한 임계값 방식), 외부 LLM 불필요.
3. **재조합·추론(synthesize_bundle)**: 한 클러스터(또는 여러 클러스터)의 단위들을 통합 → 요약 + 논리추론 흔적(reasoning_trace) + 기여 단위 추적. LLM 사용 지점(프로토콜로 교체 가능).
4. **전달(serve_pool)**: 매칭된 사람에게 단일 주제가 아닌 **다주제 통합 번들**을 수신자 언어로 제공(레이어 A 번역 재사용).

## 4. 감독 AI 3종 — 상시 대기 + 트리거 확인 + α

각 AI는 동일한 **두 가지 작동 모드**를 갖는다(사용자 요구):

### (a) 상시 대기 (standby loop)
- 백그라운드 워커가 일정 주기로 공간 상태를 점검. 기존 plaza tick / feedback update 패턴 재사용(외부 크론이 `tick` 엔드포인트 호출 → DB 띄운 환경에서 동작).
- 각 AI의 standby 관심사:
  - **중앙관리자**: 공간 전체 건강도(클러스터 균형, 번들 적체, 비공개 누출 위험) 모니터링 + 정책(임계값) 조정.
  - **기술자**: 무결성(단위↔글 정합, 임베딩 누락, 클러스터 손상) 점검 + 복구. 기존 HMAC 해시체인·권한상태(authority) 재사용 → 번들에 무결성 서명.
  - **백혈구**: 재조합 산출물의 윤리 재검사(이미 통과한 글도, 재조합으로 새 맥락이 생기면 다시 검사). 기존 13-카테고리 + 응답측 게이트 재사용.

### (b) 트리거 확인 (event-driven)
- 특정 이벤트에서 즉시 발동(주기 대기와 별개):
  - 새 번들 생성 → 백혈구 즉시 검사(blocked면 전달 차단), 기술자 즉시 서명.
  - 클러스터 급팽창/이상 → 중앙관리자 즉시 점검.
  - 비공개 단위가 공개 번들에 섞이려는 시도 → 백혈구+중앙관리자 즉시 차단.

### (+α) 추가 능력
- **중앙관리자**: 공간 리포트(digest) 생성 — 어떤 주제가 성장 중인지, 어떤 번들이 승인/차단됐는지(기존 render_digest 확장).
- **기술자**: 번들 재현성 보장 — reasoning_trace + contributing_unit_ids로 "이 결론이 어느 단위에서 나왔는지" 추적 가능(감사성).
- **백혈구**: 재조합 특유 위험(여러 비위험 정보가 합쳐져 위험해지는 경우) 탐지.

## 5. 구현 단계 (제안 순서)

1. **모델 5종 + 마이그레이션** (KnowledgeUnit/Cluster/cluster_units/InsightBundle/KnowledgeAudit)
2. **수집·클러스터링 순수 코어** (`ai/knowledge/`) — 추출·거리 그룹핑·재조합 규칙. 외부 호출 0, 순수 테스트.
3. **knowledge_service** — ingest_unit / rebuild_clusters / synthesize_bundle / serve_pool. 비공개 경계 강제.
4. **감독 AI 연결** — 3종의 standby(tick) + 트리거 훅. 기존 central/technician/leukocyte 서비스 확장.
5. **라우트** — 번들 조회(수신자 언어), 관리자용 공간 리포트·tick, 감사 로그 조회.
6. **테스트** — 클러스터링 경계, 비공개 누출 차단, 번들 무결성 서명, 재조합 윤리 재검사, 추적성.

## 6. 기존 자산 재사용 (새로 안 만들어도 되는 것)

- **임베딩**: post.content_emb (pgvector 768d) 그대로 → 단위 임베딩.
- **거리 그룹핑**: geo 의 임계값 패턴과 유사한 순수 함수.
- **윤리**: 13-카테고리 분류기 + screen_response(응답측) → 번들 검사.
- **무결성**: technician HMAC 해시체인 + AuthorityState → 번들 서명.
- **모니터링/정책**: central compute_verdict / render_digest / autotune 가드레일 → 공간 건강도·정책.
- **상시 동작**: plaza tick / feedback update 의 외부 크론 패턴 → standby 루프.
- **다국어**: translation_service → 번들을 수신자 언어로.

→ 레이어 B는 "새 엔진"이 아니라, **이미 만든 5-AI·임베딩·윤리·무결성·다국어를 엮는 새 결합 계층**에 가깝다.

## 7. 결정 필요 사항 (제작 전 확인)

1. 지식 단위 추출을 **규칙 기반(stub)부터** 시작할지(글 1건=단위 1개, 태그/임베딩 그대로), 아니면 처음부터 LLM 다중 주장 추출까지 갈지.
2. 클러스터링을 **순수 거리 임계값**(외부 호출 0, 권장)으로 시작할지.
3. 감독 AI standby 주기 — plaza tick처럼 **외부 크론 1종에 통합**할지, AI별 분리할지.
