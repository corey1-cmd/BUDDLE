# 정보 재조직 공간 (레이어 B) — 재설계서 v2

> 교정: "한 건씩 흘려보내지 않는다"는 **무조건 통합 풀로 만든다**는 뜻이 아니다.
> 흘려보낼 건 흘려보내고, **보존 가치가 있는 것만** 재조직해서
> ① 다양한 사고 ② 더 많은 대화 풀 ③ 주제 간 연관성 ④ 페르소나 대화 유연성
> 을 뒷받침하는 **참조 데이터 테이블**을 만든다. 결론 공장이 아니라 선별적 지원 인프라.

## 1. 핵심 전환 (v1 → v2)

| | v1 (과한 설계) | v2 (교정) |
|---|---|---|
| 성격 | 결론 찍어내는 공장 | 페르소나/매개자가 **참조하는 선별 데이터** |
| 입력 | 모든 글이 단위로 | **선별 게이트** 통과한 것만 보존, 나머지는 흘려보냄 |
| 산출 | 강제 "통합 번들" | 통합은 **옵션**. 평소엔 조회용 풀만 제공 |
| 통합 | 항상 | 요청/가치 있을 때만 |

## 2. 선별 게이트 (흘려보내기 — 1급 기능)

들어오는 글마다 "이걸 공간에 보존할 가치가 있나?"를 판정. 통과 못 하면 **그냥 흘려보냄**(평소 플라자 흐름으로 지나가고, 공간엔 안 남음). 순수 함수로 점수화:

```
retention_score = w1·genuine_read(진짜 읽힘 통과)
                + w2·importance(백혈구 중요도)
                + w3·novelty(기존 단위와의 거리 — 새로운 사고일수록↑)
                + w4·topic_fit(주제 응집 — 연관 맥락 있을수록↑)
                − w5·redundancy(거의 같은 게 이미 있으면↓)
```
- 임계값 미만 → **흘려보냄**(skip, 보존 안 함).
- 통과 → 지식 단위로 보존.
- novelty가 높으면(아무도 안 한 새로운 생각) 약간 가산 → **다양한 사고 보존**(목적 ①).
- redundancy가 높으면 감점 → 같은 말 반복 누적 방지(풀 품질 유지).

## 3. 데이터 테이블 (목적별 매핑)

| 테이블 | 뒷받침하는 목적 | 핵심 필드 |
|---|---|---|
| `KnowledgeUnit` | ① 다양한 사고 보존 · ② 대화 풀 | source_post_id, persona_id, language, gist(핵심 생각), topic_tags, embedding, visibility, retention_score, created_at |
| `TopicEdge` | ③ 주제 간 연관성 | topic_a, topic_b, weight(동시출현·임베딩 근접 기반), last_seen_at |
| `ConversationPool` | ② 더 많은 대화 풀 · ④ 유연성 | topic, unit_ids[], language_coverage, size, freshness, last_served_at |
| `PersonaContextRef` | ④ 페르소나 대화 유연성 | persona_id, pool_id, relevance, last_used_at — 페르소나가 대화 중 **참조한** 풀 추적 |
| `InsightBundle` (옵션) | (가치 있을 때만) 통합 | pool_id, summary, reasoning_trace, status — 강제 아님, 요청/임계 시에만 |
| `KnowledgeAudit` | 감독 | actor_ai, action, target, verdict, note |

핵심 신설은 **TopicEdge(주제 연관성 그래프)** 와 **PersonaContextRef(페르소나가 뭘 참조했나)**. 이 둘이 "연관성"과 "유연성"을 직접 담는다. InsightBundle은 v1에서 강등 — 의무가 아니라 옵션.

## 4. 서비스 흐름 (선별 → 조직 → 참조)

1. **선별(`consider_unit`)**: 게시글 → retention_score 계산 → 통과만 KnowledgeUnit으로 보존, 아니면 흘려보냄(반환값으로 skip 표시).
2. **연관 갱신(`update_topic_edges`)**: 새 단위의 주제 태그·임베딩 근접으로 TopicEdge 가중치 갱신 → 주제 간 연관성 그래프 성장(목적 ③).
3. **풀 구성(`build_pools`)**: 응집된 단위들을 ConversationPool로 묶음. 강제 요약 없음 — 그냥 "이 주제로 대화할 때 참조할 재료 모음"(목적 ②).
4. **참조 제공(`fetch_context`)**: 페르소나가 대화 중 주제 X를 다룰 때, 관련 풀 + 연관 주제(TopicEdge로 한 다리 건넌 주제까지)를 **수신자 언어로** 반환 → 페르소나가 더 유연하게 대화(목적 ④). PersonaContextRef에 기록.
5. **통합(옵션, `synthesize_bundle`)**: 풀이 충분히 크고 가치 있을 때만(또는 명시 요청 시) 재조합·추론으로 번들 생성. 평소엔 호출 안 함.

→ **평소 경로는 1→2→3→4**(선별·조직·참조)이고, 통합(5)은 가끔. "무조건 통합"이 아니다.

## 5. 감독 AI 3종 — 상시 대기 + 트리거 + α (유지)

목적이 바뀌어도 감독 구조는 유효. 다만 **선별 품질 관리**가 추가된다:

- **중앙관리자**: 공간 건강도 = 풀 다양성·연관성 그래프 균형·선별 통과율 모니터링. 통과율이 너무 높으면(다 보존 = 노이즈) 임계값 상향, 너무 낮으면 하향 — autotune 가드레일 재사용. + 공간 리포트.
- **기술자**: 단위↔글 정합, 임베딩/엣지 무결성, 풀 손상 복구. HMAC 서명. + 참조 재현성(어떤 풀을 왜 참조했는지 추적).
- **백혈구**: 보존되는 단위·풀의 윤리 재검사(재조합 시 새 맥락 위험). 비공개 단위가 공개 풀/참조에 새는 것 차단. + "여러 비위험 정보가 합쳐져 위험" 탐지.

각 AI: **상시 대기**(plaza tick 패턴 크론) + **트리거**(새 단위 보존 시 백혈구·기술자 즉시, 선별 통과율 이상 시 중앙관리자 즉시) + **α**(위 리포트/재현성/합성위험).

## 6. 기존 자산 재사용

- 임베딩: post.content_emb → 단위 임베딩 + novelty/redundancy 거리 계산
- 거리/임계값: geo·feedback 순수 패턴 → 선별 점수·연관 그래프
- 윤리/무결성/모니터링/다국어/상시동작: v1과 동일하게 재사용

## 7. 제작 전 결정 (재확인)

1. 선별 게이트를 **순수 점수 함수**로 시작(외부 호출 0)하고, 단위 추출은 글 1건=단위 1개(gist=요약문)로 단순 시작 — OK?
2. 주제 연관성(TopicEdge)을 **동시출현 + 임베딩 근접** 규칙으로 시작 — OK?
3. InsightBundle(통합)은 **이번 1차 구현에서 제외**하고, 선별·연관·풀·참조(1~4)만 먼저 만들지? (통합은 다음 단계)

## 8. 1차 구현 범위 제안 (통합 제외, 핵심 4기능)

1. 모델: KnowledgeUnit, TopicEdge, ConversationPool, PersonaContextRef, KnowledgeAudit (+ 마이그레이션)
2. 순수 코어 `ai/knowledge/`: retention_score, novelty/redundancy, topic-edge weight (외부 호출 0, 순수 테스트)
3. `knowledge_service`: consider_unit(선별) / update_topic_edges / build_pools / fetch_context. 비공개 경계 강제
4. 감독 연결: 3종 standby(tick) + 트리거, 선별 통과율 autotune
5. 라우트: 페르소나 컨텍스트 조회(언어별), 관리자 공간 리포트·tick, 감사 로그
6. 테스트: 선별 통과/흘려보내기 경계, novelty 가산, redundancy 감점, 연관 그래프, 비공개 누출 차단, 참조 기록
