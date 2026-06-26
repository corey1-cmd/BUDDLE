# buddle AI 통합 설계서 (AI Integration Design & Roadmap)

> 목적: 업로드된 사업계획서(GLM-5.1 위주, self-hosted, API 미사용)를 buddle의 실제
> 5-AI 아키텍처 및 기존 코드베이스(FastAPI + SQLAlchemy 2.0 async + PostgreSQL16/pgvector
> + Redis, 319 테스트 통과)와 정합시켜 **구현 가능한 설계**로 보강한다.
> 모든 모델은 자체 서버(vLLM)에서 구동하며 외부 API를 호출하지 않는다.

검증 출처: GLM-5.1(Z.ai, 2026-04-07, MIT) / GLM-4.6(2025-09, MIT) / GLM-4.5-Air(106B) /
BGE-M3(BAAI, 1024-dim) / vLLM 문서 — 모두 2026-06 기준 웹 검증.

---

## 0. 한눈에 보기 — 계획서 ↔ buddle 코드베이스 정합

| 항목 | 업로드 계획서 | buddle 현재 코드 | **결정(설계)** |
|---|---|---|---|
| 주력 LLM | GLM-5.1 (754B, 코딩 1위) | vLLM 어댑터만 존재(스텁) | **역할별 티어링**(아래) |
| 페르소나 모델 | GLM-5 | — | **GLM-4.6**(한국어·소셜·창작 특화) |
| 벡터 DB | Qdrant | **pgvector**(이미 구축, 319테스트) | **pgvector 유지**, Qdrant는 확장기 옵션 |
| 임베딩 | BGE-M3 (1024) | Vector(**768**) 스키마 | **BGE-M3 + 768→1024 마이그레이션** |
| 위치 처리 | PostGIS | 순수 haversine 10링(구축됨) | **haversine 유지**, PostGIS는 확장기 |
| 성향 분석 | "GLM이 성향 JSON 추출" | 규칙기반 인지(LLM 0콜, 프로파일링 금지) | **편향-안전 계약 보존**(아래 §4) |

**핵심 통찰 3가지**
1. **모델은 작업에 맞춰야 한다.** GLM-5.1은 *코딩·에이전트* 1위지 *한국어 소셜 글쓰기* 1위가 아니다. 페르소나의 본질(따뜻한 한국어 대화)에는 GLM-4.6이 공식적으로 최적화돼 있다(한국어 번역 + 소셜미디어 + 소설/카피라이팅 감정표현).
2. **이미 있는 인프라를 두 번 만들지 말자.** pgvector·haversine은 작동·검증됐다. Qdrant·PostGIS는 스케일이 요구할 때 도입한다(창업 2개월차 운영부담 최소화).
3. **사용자를 프로파일링하지 않는다.** 매칭은 *사람의 성향*이 아니라 *콘텐츠 임베딩 유사도*로 한다 — 이게 buddle의 신성한 편향-안전 계약이자 동시에 계획서의 "데이터 보안" 강점이다.

---

## 1. 모델 티어링 (자체 서버, MIT/Apache 라이선스만)

작업 성격이 다르므로 한 모델로 다 쓰기보다 **2~3티어**로 나눈다. GPU 예산에 따라 단일화도 가능.

### Tier A — 페르소나 / 번역 / 종합 (상시·지연민감·한국어 창작)
- **모델: GLM-4.6 (MIT)** — 공식 문서상 한국어 번역·소셜미디어·소설/각본/카피라이팅 감정표현·대화 흐름 최적화. buddle 페르소나·번역·InsightBundle 종합에 정확히 부합.
- 대안(경량): **GLM-4.5-Air (106B/12B active, ~4×H100)** — 비용·지연 우선 시.
- 대안(Apache): **Qwen3-14B / Qwen3.6-27B** — 한국어 강함, Apache 2.0. GLM 한국어가 부족하면 페르소나만 Qwen으로 교체 가능(프로토콜 스왑).

### Tier B — 심층 추론 / 어려운 종합 (선택, 배치성)
- **모델: GLM-5.1 (754B/40B active, MIT)** — 프런티어급 추론·구조화 출력·장기 컨텍스트. NIPA GPU(H200/B200) 확보 시 InsightBundle 고난도 종합·복잡 분석에 사용.
- **주의**: 1.51TB·8×H200 필요. 상시 채팅 턴마다 쓰기엔 과하다. **배치/비동기 종합 작업에 한정** 권장. 미확보 시 Tier A(GLM-4.6)가 이 역할도 흡수.

### Tier C — 윤리 스크리닝 (백혈구 AI)
- **1차: 규칙기반(기존 MLCommons 13-hazard 키워드/구조)** — LLM 0콜, 빠름.
- **2차(경계 사례): GLM-4.6 구조화 판정** 또는 **Llama Guard 계열** — `ethics_provider`가 이미 `llama_guard` 옵션 보유. 콘텐츠(글)만 판정하고 사람을 판정하지 않는다.

### 임베딩 — 매칭/지식공간
- **모델: BGE-M3 (1024-dim, MIT, 100+ 언어, 하이브리드 dense+sparse)** — 한국어 자체호스팅 멀티링궐 SOTA급.
- **스키마 영향**: 기존 `Vector(768)` → **`Vector(1024)` 마이그레이션(0016)** 필요. BGE-M3는 Matryoshka 미지원이라 768 축소 불가.
- **무마이그레이션 대안**: 기존 `jhgan/ko-sroberta-multitask`(768) 유지 — 품질은 BGE-M3보다 낮지만 스키마 변경 0.

### 비-LLM (모델 없음)
- **기술자(Technician)**: HMAC-SHA256 무결성 — 암호 연산, 모델 불필요.
- **중앙관리자(Central)**: 헬스·오토튠 — 규칙기반 모니터링, 모델 불필요.
- **인지(EKB) 파이프라인**: 규칙기반, **LLM 0콜 (신성한 제약)**.

---

## 2. 5-AI ↔ 계획서 3기능 매핑

계획서의 대화/분석/매칭은 buddle 5-AI의 부분집합이다. 정합 매핑:

| 계획서 기능 | buddle 구성요소 | 구현 |
|---|---|---|
| ① 대화 | **페르소나 AI** (dialogue) | GLM-4.6 (vLLM, OpenAI 호환) |
| ② 분석 | **인지(규칙) + 임베딩** | 규칙기반 토픽/관심 신호 + BGE-M3 임베딩 (프로파일링 아님) |
| ③ 매칭 | **근접 + 벡터유사** | pgvector 코사인 + haversine 10링 (기존) |
| (추가) 게시·라우팅 | **매개자(Mediator)** | 태깅·재구성·배포 대상 선정 |
| (추가) 윤리·중요도 | **백혈구(Leukocyte)** | 규칙 1차 + GLM-4.6/LlamaGuard 2차 |
| (추가) 무결성 | **기술자(Technician)** | HMAC (모델 없음) |
| (추가) 총괄 | **중앙관리자(Central)** | 오토튠 (모델 없음) |
| (추가) 번역 | **lang/translator** | GLM-4.6 |
| (추가) 지식종합 | **knowledge/synthesizer** | GLM-4.6 (or GLM-5.1 배치) |

기존 코드 훅: 모든 LLM 어댑터는 `*/vllm_endpoint.py`로 이미 존재(OpenAI 호환, LoRA, 재시도, fail-open 폴백). **설계 = 스텁→실모델 배선 + 모델 선정 + 서빙 + 성능 + 검증**이지 새 어댑터 작성이 아니다.

---

## 3. 서빙 아키텍처 (vLLM, 자체 서버)

```
[사용자 앱(9화면)] → [FastAPI 게이트웨이]
                         ├─(OpenAI호환 HTTP)→ [vLLM: GLM-4.6]  ← 페르소나/번역/종합/윤리2차
                         ├─(OpenAI호환 HTTP)→ [vLLM: GLM-5.1]  ← (선택) 심층 종합/추론 배치
                         ├─(/v1/embeddings)→ [vLLM 또는 TEI: BGE-M3] ← 임베딩
                         ├→ [PostgreSQL 16 + pgvector] ← 대화/글/지식/벡터(1024)
                         └→ [Redis] ← 레이트리밋/세션/캐시
```

- **vLLM OpenAI 호환 엔드포인트**(`/v1/chat/completions`, `/v1/embeddings`) — 기존 어댑터가 그대로 호출.
- **GLM 전용 vLLM 플래그**: `--tool-call-parser glm45/glm47`, `--reasoning-parser glm45`, FP8 가중치.
- **임베딩**: vLLM pooling(`--convert embed`) 또는 HuggingFace TEI 별도 서버. BGE-M3 max-len 8192.
- **데이터는 전부 사설망 내부**(외부 API 0) — 계획서의 데이터 보안 주장과 일치.

---

## 4. 편향-안전 계약 보존 (가장 중요)

계획서의 "GLM이 성향(personality) JSON 추출"은 buddle의 **사용자 프로파일링 금지** 계약과 충돌한다. 화해 방식:

- **매칭 신호 = 콘텐츠 임베딩**(글/주제의 의미 벡터)이지 *사람에 대한 추론*이 아니다.
- 인지(EKB)는 **현재 메시지 텍스트만** 읽고 규칙으로 토픽 신호를 뽑는다. 과거 누적 프로파일·민감속성 추론 없음.
- LLM(GLM)이 하는 일: 페르소나 글쓰기, 번역, **콘텐츠** 윤리 판정, **콘텐츠** 종합. 사람을 점수화·라벨링하지 않는다.
- 결과: ① 윤리적 안전(편향·차별 위험↓) ② **프라이버시 = 제품 강점**(계획서 "데이터 외부 유출 없음"을 데이터 모델 수준에서 강화) ③ 규제(개인정보보호법) 부담↓.

> 이는 단순 제약이 아니라 차별화 포인트다: "AI가 당신을 분석/판정하지 않고, 당신의 *생각*을 언어 너머로 전달한다."

---

## 5. 성능 보강 (GitHub/vLLM·Microsoft 조사 반영)

자체 서버 비용은 고정이지만, 처리량·지연을 끌어올려 같은 GPU로 더 많은 동시 사용자를 받는다.

1. **FP8 양자화** — 가중치·KV캐시 FP8. GPU 수 절반(예: GLM-5.1 8×H200 기준). H100/H200은 FP8 네이티브.
2. **텐서 병렬(`--tensor-parallel-size`)** — 대형 모델을 다중 GPU로 분할.
3. **Speculative decoding (MTP/EAGLE)** — GLM은 MTP 레이어 내장. `--speculative-num-steps 3 --speculative-eagle-topk 1` 류로 토큰/초 대폭↑.
4. **Prefix caching** — 페르소나 시스템 프롬프트가 반복되므로 접두 캐시로 짧은 채팅 다수에서 TTFT 급감(핵심 최적화).
5. **Continuous batching / chunked prefill** — vLLM 기본. 동시 요청 throughput↑.
6. **구조화 출력(guided JSON decoding)** — 태그/윤리 판정 등 구조화가 필요한 곳에 `guided_json`(outlines/xgrammar)으로 **유효 JSON 보장**(파싱 실패 0). 단, 페르소나 자연어는 비구조화.
7. **DeepSeek Sparse Attention(DSA)** — GLM-5.1 내장, 장컨텍스트 비용↓.
8. **임베딩 배치** — consider_post에서 임베딩을 배치 호출, Redis로 동일 텍스트 캐시.
9. **CPU 폴백** — GPU 부재 환경은 ONNX Runtime(소형 모델)로 degrade. 운영은 GPU 우선.

벤치 참고(MS Foundry Local, A10 1장, 소형모델): 동시 8요청 시 ~200~340 tok/s 출력 — 동시성↑ throughput↑(배칭 효과)를 보여줌.

---

## 6. 인프라 / GPU 예산 (지원사업 정합)

| 모델 시나리오 | GPU 요구(추론) | 적합 지원사업 |
|---|---|---|
| GLM-4.6 단일(워크호스) | FP8 다중 GPU(중규모) | NIPA GPU + KISA 클라우드 |
| GLM-4.5-Air 단일(경량) | ~4×H100 | 더 현실적, 빠른 선정 가능 |
| GLM-5.1 포함(플래그십) | 8×H200(FP8) | NIPA H200/B200 프로그램과 정합 |

- **백엔드(VM 3대: FastAPI/Postgres/Redis)** = KISA 위치정보 클라우드 지원(2025-12-29~2026-09-30 접수중)으로 충당 — 기존 스택과 일치.
- **권장 전략**: 신청서는 GLM-5.1을 *플래그십*으로 제시(임팩트·MIT·벤치 1위로 GPU 요구 정당화)하되, **실서비스 1차는 GLM-4.6/Air로 가동**해 선정 전에도 베타가 돌게 한다. 선정 후 GLM-5.1을 심층 종합 티어로 추가.

---

## 7. 로드맵 (AI 실연동)

### Phase 0 — 설계 확정 (이 문서) ✅
- 모델 티어링·스키마·편향계약·성능전략 확정.

### Phase 1 — 로컬 가동 + 스키마 정합 (1주)
- [ ] 임베딩 차원 결정: BGE-M3(1024) 채택 → **migration 0016: Vector(768)→Vector(1024)** (또는 ko-sroberta 768 유지)
- [ ] `config.py` 기본값 갱신: `embedding_model_id=BAAI/bge-m3`, persona 기본 `model_key`/`backend_kind=vllm_endpoint`, translation/synthesis/ethics provider 배선 값
- [ ] `docker-compose.gpu.yml`: vLLM(GLM-4.6) + (옵션)vLLM(BGE-M3 임베딩) + Postgres16/pgvector + Redis
- [ ] 페르소나 모델 레지스트리 시드: GLM-4.6 템플릿 등록(backend_config endpoint/model)

### Phase 2 — 단일 경로 E2E (1~2주)
- [ ] 회원가입→페르소나 생성→생각 입력→**GLM-4.6 실제 다국어 글 생성**→게시 (런타임)
- [ ] 번역 경로(KO↔EN) 실모델, 임베딩 실모델로 매칭 동작
- [ ] Docker로 DB 통합테스트 62개 + 신규 모델 경로 테스트 통과
- [ ] WebSocket 대화: `finishReply()`를 실제 GLM 응답 프레임에 연결(프론트 데모 제거)

### Phase 3 — 5-AI 완전체 + 성능 (2주)
- [ ] 매개자 태깅/배포, 백혈구 2차(GLM-4.6/LlamaGuard), 종합(InsightBundle) 실모델
- [ ] 성능: FP8 + prefix caching + speculative + guided JSON 적용·계측(TTFT/throughput)
- [ ] knowledge_tick 스케줄러 런타임(APScheduler/cron) 결정·가동

### Phase 4 — (선택) GLM-5.1 심층 티어 + 평가 (NIPA 선정 후)
- [ ] GLM-5.1 vLLM(FP8, 8×H200) 심층 종합 배치 경로
- [ ] AI 품질 평가 하네스(한국어 자연스러움·번역 충실도·윤리 정확도), 비용/지연 대시보드

### 출시 전 필수(병행)
- [ ] 위치기반서비스사업 신고, 개인정보처리방침·이용약관
- [ ] 관측성(Sentry 연결됨 → 배선), TLS(+PQC 하이브리드)

---

## 8. 즉시 착수(이번 단계 산출물)
Phase 1의 첫 단계로 **config 기본값 + 임베딩 차원 마이그레이션 + docker-compose(vLLM)** 를 잡는다.
모델은 GLM-4.6(워크호스) 기준으로 배선하고, GLM-5.1은 심층 티어 설정값으로 예약한다.
