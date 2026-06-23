# buddle 설계 원리 정리 (Design Principles)

buddle의 코드 구조·기획·제작에 실제로 인용·적용된 원리, 법칙, 모델을 한곳에 모았다.
각 항목: **원리 — 무엇인지 / buddle 어디에 / 왜**.

---

## A. 외부 학문 법칙·모델 (이름 있는 원리)

### 1. 토블러 지리학 제1법칙 (Tobler's First Law of Geography)
- **무엇**: "가까운 것이 먼 것보다 더 관련 있다(near things are more related than distant things)."
- **어디에**: `ai/geo/proximity.py` — 위치 기반 매칭. 동심원 링({1~1000km})으로 가까울수록 더 많은 링이 중첩돼 점수↑.
- **왜**: 지리적으로 가까운 사람끼리 문화·관심사·대화 주제가 겹친다는 가정의 학문적 근거. 추천에 거리 차원을 정당화.

### 2. Engel–Kollat–Blackwell (EKB) 소비자 의사결정 모델
- **무엇**: 인지를 5단계로 본다 — 정보 노출→주의→이해→수용→보유(Exposure→Attention→Comprehension→Acceptance→Retention), 그리고 문제인식→탐색→평가→선택의 의사결정 과정.
- **어디에**: `ai/cognition/` 전체 — 페르소나가 사용자 메시지를 처리하는 인지 파이프라인. `information.py`(정보 5단계), `decision.py`(의사결정), `signals.py`(의도/전략).
- **왜**: 페르소나의 "이해하고 반응하는" 과정을 임의 설계가 아니라 검증된 인지 모델 위에 세움. 단, **편향 안전**을 위해 각 단계는 현재 메시지만 읽고 프로파일링은 안 함.

### 3. MLCommons AI 안전 13-위험 분류체계 (13-Hazard Taxonomy)
- **무엇**: AI 안전 표준의 13개 위험 카테고리(S1~S13). Meta Llama Guard 3와 동일 체계.
- **어디에**: `ai/ethics/taxonomy.py`, `stub.py`, `llama_guard.py` — 백혈구 AI의 윤리 판정.
- **왜**: 윤리 기준을 자체 발명하지 않고 업계 표준에 정렬 → 상호운용성(Llama Guard 어댑터 무변경 결합) + 신뢰성.

### 4. SRE 골든 시그널 (Google SRE Golden Signals)
- **무엇**: 시스템 모니터링의 4지표 — 트래픽, 에러, 지연, **포화도**(traffic, errors, latency, saturation).
- **어디에**: `ai/central/report.py` — 중앙관리자의 공간 건강 리포트(saturation_pct 등).
- **왜**: 모니터링 설계의 표준 렌즈. 무엇을 볼지 임의로 고르지 않음.

### 5. 컴퓨터 구조 — 메모리 / MMU 유추 (Memory & MMU analogy)
- **무엇**: CPU가 디스크를 직접 안 보고 MMU가 필요한 페이지만 메모리에 올려 가공. 작업기억(working memory)과도 통함.
- **어디에**: 레이어 B 정보 재조직 공간 전체(`ai/knowledge/`, `knowledge_service`). 단위=페이지, 선별=매핑, 풀/번들=작업기억.
- **왜**: "전체 글 DB를 매번 훑지 않고, 가치 있는 것만 올려 재조합·추론한다"는 구조의 멘탈 모델.

### 6. Haversine 공식 (Great-circle distance)
- **무엇**: 위경도 두 점의 구면 최단거리.
- **어디에**: `ai/geo/proximity.py` — 링 판정의 정확한 거리 계산.
- **왜**: 평면 근사가 아닌 지구 곡률 반영. 도시/지역 스케일에서 정확하고 저렴.

---

## B. 수학적 설계 패턴

### 7. tanh 포화 정규화 (Saturating normalization)
- **무엇**: `i_max·tanh(raw/kappa)` — 입력이 커져도 출력이 상한으로 부드럽게 수렴(폭주 방지).
- **어디에**: `ai/importance/function.py` — 백혈구 중요도 점수. `kappa`로 포화 속도 조절.
- **왜**: 점수가 무한정 커지지 않게. 극단값에 둔감한 안정적 신호.

### 8. 포화 카운트 매핑 (Saturating count → [0,1])
- **무엇**: `count / saturation` 클램프 — N개에서 1.0 포화.
- **어디에**: `ai/knowledge/selection.py` `redundancy_from_count` — 중복 단위가 많을수록 감점, 3개에서 최대.
- **왜**: 한 번 중복은 약하게, 여러 번 반복은 강하게 페널티. 비선형 직관 반영.

### 9. 가중치 재정규화 + 가드레일 (Renormalization + guardrails)
- **무엇**: 가중치 조정 후 합=1로 재정규화, 각 가중치 [W_MIN, W_MAX], 1회 변화 ≤ MAX_STEP.
- **어디에**: `ai/central/autotune.py` — 매개자 분배 가중치 자동조정. 선별 임계값 autotune도 동일 철학.
- **왜**: 자동조정이 발산/쏠림 없이 안정적으로 수렴. 피드백 루프의 안전장치.

### 10. 시간 감쇠 (Exponential decay)
- **무엇**: `weight · decay^ticks` — 오래된 것일수록 가중치 지수적 감소.
- **어디에**: `ai/knowledge/edges.py`(주제 연관 감쇠 0.98), `ai/mediator/feedback.py`(반응 신호).
- **왜**: 오래된 연관/반응은 자연히 잊혀야 함. 망각 속도 = tick주기 × decay.

### 11. 단일연결 그리디 군집화 (Single-linkage greedy clustering)
- **무엇**: 임계 이상 유사하면 같은 그룹으로 묶는 결정적 그리디.
- **어디에**: `ai/knowledge/synthesis.py` `plan_synthesis` — 통합 시 단위 재조합.
- **왜**: 외부 라이브러리 없이 결정적·저렴. 같은 입력 → 같은 그룹(테스트 가능).

### 12. 코사인 유사도 (Cosine similarity)
- **무엇**: 임베딩 벡터 간 각도 기반 유사도.
- **어디에**: novelty/redundancy(선별), 주제 근접(엣지), 통합 그룹핑. pgvector cosine_distance.
- **왜**: 의미 유사도의 표준 척도. "새로운 생각/중복/연관"을 수치화.

### 13. 단일 패스 최적화 (Single-pass computation)
- **무엇**: 같은 컬렉션을 여러 번 순회하지 않고 한 번에 여러 통계 계산.
- **어디에**: `knowledge_service._sim_stats` — max_sim과 near_dupes를 한 순회로(이전 2회→1회, norm 재계산 제거).
- **왜**: 동작 불변, 비용 절감. 무작위 1000회 비교로 옛 방식과 동일 증명.

---

## C. 시스템·보안 원리

### 14. 실패 시 닫힘 / 실패 시 열림 (Fail-closed / Fail-open)
- **무엇**: 보안 결정은 의심스러우면 거부(closed), 가용성 우선 보조 기능은 에러 시 통과(open).
- **어디에**: 인증·권한(`technician`, auth route)=**fail-closed**; 윤리 재검사·번역·지식 보존=**fail-open**(백엔드 에러가 정상 글을 막지 않음).
- **왜**: 보안은 안전을 우선, 부가기능은 가용성을 우선. 맥락별로 다르게.

### 15. 상수 시간 비교 (Constant-time comparison)
- **무엇**: 비밀 비교 시 일치 여부와 무관하게 동일 시간 소요(타이밍 공격 방어).
- **어디에**: `auth_service`(없는 사용자도 더미 argon2 검증), `technician/integrity.py`(해시 검증).
- **왜**: 응답 시간차로 비밀을 유추하지 못하게.

### 16. 해시 체인 / 추가 전용 (Hash chain / Append-only)
- **무엇**: 각 레코드가 이전 해시를 포함해 위변조 시 체인 깨짐. 로그는 추가만, 수정/삭제 없음.
- **어디에**: `technician/integrity.py`(HMAC 해시 체인), `KnowledgeAudit`(추가 전용 감사 로그).
- **왜**: 무결성·감사성. 누가 무엇을 했는지 변조 불가하게 기록.

### 17. 멱등성 (Idempotency)
- **무엇**: 같은 연산을 여러 번 해도 결과 동일(중복 무해).
- **어디에**: 좋아요(UNIQUE+IntegrityError 무시), 번역(post+language UNIQUE), 통합(최근 번들 있으면 skip).
- **왜**: 재시도·중복 호출에 안전. 데이터 일관성.

### 18. 최소 권한 / 비공개 경계 (Least privilege / Privacy boundary)
- **무엇**: 각 주체는 필요한 것만. 비공개 데이터는 경계 밖으로 안 나감.
- **어디에**: 5-AI 권한 분리(T1/T2), 레이어 B `fetch_context`(PUBLIC만 교차 제공, PRIVATE는 소유자만), 통합(visibility 동질성).
- **왜**: 정보 누출 방지. AI마다 권한 격리로 오작동 영향 최소화.

### 19. 정밀 저장 / 일반화 노출 (Precise store, coarse expose)
- **무엇**: 정확 좌표는 저장하되, 외부엔 일반화(반올림)된 값만 노출.
- **어디에**: `ai/geo/proximity.coarsen` + `proximity_service` — 거리 계산은 정확, 타인에겐 ~1km 격자.
- **왜**: 매칭 정확도와 프라이버시를 동시에. LBS 규제 대응.

---

## D. 아키텍처·코드 구조 원리

### 20. 어댑터 교체 패턴 (Protocol swap pattern)
- **무엇**: 같은 프로토콜 뒤에 stub(결정적·테스트용) ↔ 실모델(LLM/API)을 config로 교체.
- **어디에**: 윤리(EthicsClassifier), 번역(Translator), 통합(Synthesizer), 임베딩, 페르소나 백엔드.
- **왜**: 외부 의존 없이 전 파이프라인 테스트 + 운영 시 무변경 교체.

### 21. 순수 코어 / 부수효과 격리 (Pure core, effects at the edge)
- **무엇**: 계산 로직은 순수 함수(외부 호출·DB 0), I/O는 서비스 계층에서만.
- **어디에**: `ai/geo`, `ai/knowledge`(extraction/selection/edges/synthesis), `ai/importance`, `ai/central` 등 모든 `ai/`.
- **왜**: 순수 코어는 이 환경에서 완전 검증 가능. 결정적이라 테스트가 쉽고 재현됨.

### 22. 점진적 무중단 마이그레이션 (Additive backward-compatible migration)
- **무엇**: 기존 스키마를 바꾸지 않고 새 컬럼/테이블만 추가(nullable + default).
- **어디에**: 마이그레이션 0011~0015 모두(위치/세션/다국어/지식공간/통합). 위치 CRUD 통합도 별도 엔드포인트 유지.
- **왜**: 기존 데이터·동작 보존하며 기능 확장. 후방호환.

### 23. 상시 대기 + 트리거 (Standby loop + event trigger)
- **무엇**: 백그라운드 주기 점검(외부 크론 tick) + 이벤트 발생 시 즉시 동기 검사, 두 모드.
- **어디에**: 광장 tick, 레이어 B `knowledge_tick`(상시) + `consider_post` 내부 백혈구·기술자(트리거).
- **왜**: 정기 유지보수와 즉각 대응을 분리. 감독 AI 3종이 두 방식으로 공간 관리.

### 24. 참조 vs 지시 분리 (Reference, not instruction)
- **무엇**: 페르소나에 주는 지식은 "참고 자료"지 "따라야 할 명령"이 아님.
- **어디에**: `prompts.build_dialogue_messages` 지식 주입("그대로 따를 필요 없음"), 통합 요약("단정하지 않고 관점 제시").
- **왜**: 페르소나의 자율성·유연성 보존. 정보 풀이 사고를 강제하지 않게.

### 25. 흘려보내기를 1급으로 (Let-pass as first-class)
- **무엇**: 모든 입력을 저장하지 않고, 보존 가치 있는 것만 들이고 나머지는 흘려보냄.
- **어디에**: `ai/knowledge/selection.py` 선별 게이트(retention_score < 임계 → skip).
- **왜**: 공간을 결론 공장이 아니라 **선별된 참조 인프라**로. 노이즈·중복 누적 방지.

### 26. 중앙 설정 집중 (Centralized config over scattered markers)
- **무엇**: 억제·예외를 코드 곳곳 인라인 주석이 아니라 한 설정 파일에.
- **어디에**: bandit 억제를 `pyproject.toml`에 집중(인라인 noqa 금지), gitleaks allowlist 중앙화.
- **왜**: 코드에 약점 위치를 표시하지 않음(공격자 신호 제거) + 관리 일원화.

---

## 요약: buddle을 떠받치는 3개 큰 축

1. **검증된 모델 위에 짓는다** — Tobler(위치), EKB(인지), MLCommons(윤리), SRE(모니터링), MMU(정보공간). 임의 설계 최소화.
2. **안전을 구조로 보장한다** — fail-closed/open, 상수시간, 해시체인, 비공개 경계, 권한 분리, 정밀저장/일반화노출.
3. **교체·검증·확장이 쉽다** — 순수 코어 + 어댑터 교체 + 점진 마이그레이션 + 참조(지시 아님) + 흘려보내기.
