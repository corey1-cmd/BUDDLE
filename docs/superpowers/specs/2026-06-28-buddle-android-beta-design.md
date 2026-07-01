# BUDDLE 안드로이드 클로즈드 베타 — 설계 스펙

- 작성일: 2026-06-28
- 상태: 설계(승인 대기)
- 접근: **수직 슬라이스(C)** — 핵심 흐름 하나를 배포까지 끝까지 관통 후 확장
- 관련 문서: [ARCHITECTURE.md](../../ARCHITECTURE.md), [README.md](../../../README.md)

---

## 1. 목표와 범위

**목표:** 기존 BUDDLE 백엔드(FastAPI, Supabase) 위에 **Flutter 안드로이드 앱**을 만들고,
**0원 인프라(Oracle Cloud Free Tier)** 에 백엔드를 공개 배포하여 **Google Play 클로즈드(비공개)
베타** 트랙에 올린다. 정식 출시가 아니라, "Play Store에서 실제로 도는 앱 + 테스터 피드백"이
목표다.

**핵심 원칙:** 백엔드 기능은 대부분 이미 구현되어 있다. 따라서 이 프로젝트의 일은
(1) 백엔드 **배포**, (2) 일부 **읽기 API/소스 추가**, (3) Flutter **앱 신규 개발**, (4) Play **출시
파이프라인**이다. 새 백엔드 도메인 로직은 최소화한다.

### 1.1 제품 컨셉 — "말하기 → 정리 → 글 → 이해 → 다시 정리"의 순환

AI는 **사용자를 대신하는 개인 비서(개인화 페르소나)가 아니라, 콘텐츠에 붙는 도구**다. 핵심 순환:

```
AI와 대화(생각을 '말하기') → AI가 주장·근거·논점 정리 → 초안 → 사용자 수정 → 게시
   → 다른 사람은 그 글의 '게시글 이해 AI'와 대화하며 이해
   → 자기 의견을 다시 AI와 정리해 작성 → (순환)
   (+ 화제별 '토론 흐름 요약 AI'로 찬성/반대/쟁점을 바로 파악)
```

**가치:** ① 생각을 먼저 *말하고* 글은 나중에(글쓰기 장벽↓) ② 즉흥 댓글 대신 *정리된 의견*(이성적
토론) ③ 게시글별 AI로 깊은 이해 ④ AI 반론 제시로 논리적 글 유도. **글을 안 써도 대화만으로
참여 가능**(원하면 게시).

### 1.2 베타 슬라이스 기능

| # | 기능 | 백엔드(재사용) | 비고 |
|---|---|---|---|
| 1 | 회원가입 / 로그인 | JWT, refresh 회전 | 토큰 secure storage |
| 2 | **화제·게시글 피드(인스타그램형)** | tags / posts / plaza | **홈 화면.** 사회·기술·정치·문화·일상 등 화제 탐색 |
| 3 | **대화형 글쓰기 (글쓰기 지원 AI)** | dialogue(WSS) + post + ai/argument + cognition | 대화만 모드 → 대화 분석(주장·근거·핵심논점·빠진부분·논리구조) → AI 초안 → 사용자 수정 → 게시. **반론 제시 + 의견 변화 기록** 포함 |
| 4 | **게시글 이해 AI** | argument_chat_ws.py (RAG) | 게시글마다: 핵심주장 요약·논리구조 설명·근거/결론 정리·개념 설명·질문 답변 ("이 글 무슨 말이지?") |
| 5 | **토론 흐름 요약 AI** | ai/argument, debate.py | 화제 토론 흐름 요약 + "찬성 측?/반대 측?/쟁점?" 즉답. 댓글 전쟁 대신 정보 탐색 |
| 6 | **권리 인지 뉴스(화제 소스)** | news pipeline + 권리엔진 | 화제 피드의 뉴스. 제목+링크+우리 사실요약(티저). 상세: [content-rights-engine](2026-06-28-content-rights-engine.md) |
| 7 | 게시글 댓글 토론 | plaza 댓글(정보/공감/질문) | 토론 substrate |

> **⚠️ 페르소나 개인화는 제거.** 사용자가 만드는 개인화 AI 대신 위 3·4·5의 **기능형 AI**가 콘텐츠에
> 붙는다. 백엔드 페르소나 대화 엔진은 이 AI들의 **구동 엔진으로 재사용**(개인화 UI 없음 / 기본
> 어시스턴트 자동 제공).
>
> **기능 3 (대화형 글쓰기) 흐름:** ① 화제 선택 → ② AI와 자유 대화(글 안 써도, 질문만도 OK) →
> ③ AI가 대화에서 주장·근거·핵심논점·빠진 부분·논리구조 추출(cognition+argument) → ④ AI 초안(LLM)
> → ⑤ 사용자 수정 → ⑥ 게시. 게시 전 AI가 **반론·약한 근거**를 제시(debias/argument). 대화 중
> **의견 변화**(처음 주장→질문→수정 주장)를 기록해 "생각이 발전하는 과정"을 콘텐츠화.
>
> **기능 4 (게시글 이해 AI):** 각 게시글에 붙는 RAG 대화 — 그 **사용자 글**(출판사 원문 아님,
> 저작권 무관)을 분석해 핵심주장·논리구조·개념을 설명하고 질문에 답한다.
>
> **기능 5 (토론 흐름 요약 AI):** 화제 단위로 **우리 플랫폼 토론 데이터**(글·댓글·주장) 기반 요약 +
> 찬반·쟁점 즉답. "화제 자체 설명"이 아니라 "토론의 흐름". 출판사 본문 미사용.
>
> **기능 6 정의(권리 인지 뉴스):** [콘텐츠 권리 엔진](2026-06-28-content-rights-engine.md) 적용.
> default-deny + 상업 기준 → 베타엔 **모든 매체 = 제목+링크+메타+우리 사실요약(티저)**. 수집·요약
> 4선: ① 입력=공식 RSS 스니펫(스크래핑❌) ② Gemini가 사실을 우리 말로 1~3줄(표현 복제❌)
> ③ 티저 길이(원문 읽기 대체❌)+링크·매체명 ④ 임베딩은 우리 텍스트로(본문 임베딩❌).

### 1.3 예정(연기) — 베타 이후

- 위치 기반 근접 매칭, 다국어 매개 UI, 푸시 알림(FCM)
- **원문 기반 요약·이해 LLM 대화** — 출판사 본문을 요약해 화제를 이해시키는 대화는 **B2B 라이선스 체결 후**에만(저작권). 베타는 토론 흐름 요약(기능 5, 우리 토론 데이터)으로 대체.
- iOS 앱
- GPU 확보 후 vLLM 자체 모델 전환 (베타는 Gemini 무료 API)

---

## 2. 목표 아키텍처

```
 [Flutter 앱 (Android)]
        │  HTTPS (REST) / WSS (대화)
        ▼
 [Caddy 리버스프록시 — Let's Encrypt 자동 TLS]
        │                                   ← Oracle Cloud A1 ARM VM (always-free, 0원)
        ▼
 [FastAPI 컨테이너] ──┬── [Redis 컨테이너]
        │            ├── Gemini 무료 API (페르소나/매개자 LLM)
        │            └── BGE-M3 임베딩 (sentence_transformers, CPU, in-process)
        ▼
 [Supabase Postgres + pgvector] (기존, 클라우드)
```

**구성 요소와 책임:**

- **Flutter 앱(Android):** UI + 상태관리. 백엔드와 REST/WSS로만 통신. 비즈니스 로직 없음(백엔드가 권위).
- **Caddy:** 80/443 단일 진입점, 자동 HTTPS. 업스트림 = FastAPI(127.0.0.1:8000).
- **FastAPI + Redis (docker compose):** 기존 앱 그대로. `SCHEDULER_ENABLED=true`로 뉴스/광장/지식 tick 자동 구동.
- **임베딩:** `EMBEDDING_PROVIDER=sentence_transformers`, `BAAI/bge-m3`(1024차원), `EMBEDDING_DEVICE=cpu`. 토론 흐름 요약·광장 군집·화제 묶기의 의미 품질 확보(우리 텍스트 대상). 0원(자체 CPU). **처리 전략 = §3.1 임베딩 3단계.**
- **LLM:** Gemini 무료 API(OpenAI 호환 엔드포인트, 기존 키). 429는 백오프, 불가 시 결정적 폴백(파이프라인 무중단).
- **DB:** 기존 Supabase(`<PROJECT_REF>`, pooler aws-1, `?ssl=require`). 마이그레이션 head 0022.

---

## 3. 기술 결정

| 항목 | 결정 | 이유 |
|---|---|---|
| 모바일 프레임워크 | **Flutter (Dart)** | 단일 코드베이스, UI 일관성·성능 |
| 백엔드 호스팅 | **Oracle Cloud Free Tier A1 ARM VM** (4 OCPU/24GB) | 0원, 임베딩 CPU 구동 가능 |
| 배포 방식 | **docker compose + Caddy** | 기존 Dockerfile 재사용, 자동 TLS |
| 도메인/TLS | sslip.io(IP 기반) 또는 무료 DDNS | 베타 0원 (커스텀 도메인은 선택) |
| LLM | Gemini 무료 API → (추후 vLLM) | 베타 0원, 사업계획서 방침 일치 |
| 임베딩 | sentence_transformers BGE-M3 CPU | 군집 품질 + 0원 + 데이터 주권 |
| 상태관리 | Riverpod | 검증된 솔로 친화 패턴 |
| HTTP/WS | dio + web_socket_channel | |
| 토큰 저장 | flutter_secure_storage | OS 보안 저장소 |
| 푸시 | **연기**(Phase 5, FCM) | 베타 핵심 아님 |
| 플랫폼 | **Android만** | iOS 범위 밖 |

### 3.1 임베딩 처리 파이프라인 (3단계 점진적 강등 + 자가복구)

대화 핫패스를 막지 않으면서 의미 품질을 지키기 위해, 2단계(즉시계산 ↔ stub)가 아니라 **3단계**로 고도화:

1. **Tier 1 — 캐시 / 사전계산:** 텍스트 해시 키로 임베딩 **캐시 조회**. 백그라운드 tick이 신규
   *우리 텍스트*(우리 요약·게시글·댓글·주장)를 미리 임베딩해 채워 둠. 히트 시 즉시 반환(계산 0).
2. **Tier 2 — 백프레셔 큐 + 배치:** 캐시 미스 시 동기 계산 대신 **유계 비동기 큐**에 적재 → CPU에서
   **배치**로 BGE-M3 임베딩(레이트 제한·코어 보호). 결과 저장. 핫패스는 큐잉만 하고 진행(블로킹 0).
3. **Tier 3 — stub 폴백 + 지연 재임베딩:** 큐 포화/타임아웃 등 임베딩이 즉시 꼭 필요한데 없으면
   **결정적 stub로 임시 처리**하고 그 항목을 **재임베딩 대기열**에 표시 → 여유가 생기면 tick이 실제
   BGE-M3로 교체(**자가복구**). 즉 품질 저하가 **영구적이지 않다.**

핵심 보장: ① 핫패스 블로킹 0, ② 과부하에도 실패 0(graceful degradation), ③ stub은 *마지막 수단·
일시적*이며 나중에 실제 임베딩으로 자동 치유. ④ 출판사 본문은 어떤 단계에서도 임베딩하지 않음
(우리 텍스트만 — 권리엔진 §9).

> 구현 시 기존 `ai/embeddings/`의 provider 추상화 위에 캐시·큐·재임베딩 레이어를 얹는다(코어 교체 X).

---

## 4. 단계별 로드맵

각 단계 끝에 **검증 기준**을 둔다. 슬라이스 원칙상 Phase 1~5로 한 번 끝까지 관통한 뒤,
게시글 이해 AI·토론 흐름 요약·뉴스 화면을 같은 클로즈드 트랙에 빠르게 얹는다.

### Phase 0 — 준비 (로컬/계정)
- Flutter SDK + Android Studio/SDK + 실기기 또는 에뮬레이터
- Google Play Console 개발자 계정 등록 (**$25 일회성**)
- **Oracle Cloud A1 ARM VM 프로비저닝 (사용자 수행 — Claude 단계별 가이드):** 계정 생성(카드 인증) → Always Free **A1.Flex** 인스턴스(Ubuntu LTS, aarch64, 목표 4 OCPU/24GB) + SSH 키. 'out of capacity' 시 재시도/리전 변경. **SSH 접속 확보되면 Phase 1부터 Claude가 배포 수행.**
- 무료 도메인 결정(sslip.io = VM IP 기반)
- **검증:** `flutter doctor` 통과, VM에 SSH 접속

### Phase 1 — 백엔드 공개 배포 (Oracle VM)
- VM에 Docker/Compose 설치, repo 클론, **prod `.env`** 작성(**APP_ENV=production** → dev 시크릿 거부·CORS '*' 금지 강제 / 강력한 distinct JWT·HMAC, Supabase/Gemini/Redis, `SCHEDULER_ENABLED=true`, `EMBEDDING_PROVIDER=sentence_transformers`). ※ production에선 `/docs`·`/redoc` 비활성(설계상)
- ARM(aarch64) 멀티아치 이미지 빌드 확인(베이스 이미지 arm64 지원)
- `docker-compose`에 Caddy 추가(자동 TLS), Oracle security list + ufw로 80/443만 개방
- CORS/`WS_ALLOWED_ORIGINS`를 앱 오리진/네이티브(Origin 없음 허용)로 설정
- **검증:** 공개 `https://<host>/health` 200, 회원가입→로그인(REST)→WSS 대화 성공(외부 네트워크/실기기에서). (/docs는 production 비활성이므로 검증에 쓰지 않음)

### Phase 2 — 뉴스: 소스 확장 + 사용자 읽기 API (백엔드 소폭)
- 뉴스 소스에 **Reuters·Guardian 등 공개 RSS** + **WSJ·Bloomberg 헤드라인 RSS** 등록(관리자 설정=Redis). 본문 미수집(공개 RSS 한정).
- 현재 admin 전용 브리핑을 **인증 사용자 읽기 엔드포인트**로 노출: 예) `GET /v1/news/briefings`(조합 브리핑), `GET /v1/news/briefings/{tag}`(태그별). 기존 `news_service` 재사용, 쓰기 없음.
- **검증:** 일반 사용자 토큰으로 뉴스 브리핑 조회, tick 후 신규 분석 반영

### Phase 3 — Flutter 앱: 슬라이스 화면
- 프로젝트 셋업, 환경설정(백엔드 base URL), dio+WSS 클라이언트, 토큰 보안저장/자동갱신, Riverpod
- 화면(우선순위 순): **① 로그인/가입 → ② 화제·게시글 피드(홈, 인스타형) → ③ 대화형 글쓰기(대화만 → AI 대화분석 → 초안 → 수정 → 게시; 반론·의견변화) → ④ 게시글 이해 AI 대화 → ⑤ 토론 흐름 요약 AI(찬반/쟁점) → ⑥ 뉴스(화제 소스) → ⑦ 댓글 토론**
- 각 화면은 라이브 백엔드에 연동
- **검증:** 실기기에서 ①~③(로그인→피드→대화형 글쓰기·게시) end-to-end(첫 베타 최소셋), 이어서 ④⑤⑥⑦

### Phase 4 — Play Store 클로즈드 베타
- Play Console 앱 생성, **클로즈드 테스트 트랙**, Play 앱 서명 설정
- `flutter build appbundle`(release, 서명) → AAB 업로드
- **개인정보처리방침(필수 URL)** + 데이터 안전(Data safety) 양식 + **외부 AI(Gemini)로 대화 전송 고지·동의**
- 테스터 이메일 등록 → 초대 링크
- **검증:** 테스터가 Play에서 설치 → 로그인 → 대화 → 뉴스/광장/토론 확인

### Phase 5 — 확장 (베타 이후)
- 위치 근접 매칭, 다국어 UI, 푸시(FCM)
- 게시글 이해/토론 흐름 AI(기능 4·5) 고도화: "주장·인물" 단위 RAG로 세분화(베타는 게시글/화제 단위)
- GPU 확보 시 `persona_endpoint`/`embedding_endpoint`를 vLLM/TEI로 전환(코드 변경 없이 .env 시드)

---

## 5. 백엔드 변경 목록 (최소)

신규 도메인 로직은 거의 없음. 변경/추가는 다음으로 한정:

1. **뉴스 읽기 엔드포인트**(사용자용) — `news_service`의 기존 조회를 `/v1/news/*`로 노출(읽기 전용). **권리엔진 적용**: 응답은 매체 권리 프로필에 따라 필드 필터(기본 제목+링크+메타+우리 한 줄).
2. **콘텐츠 권리 엔진** — `content_source` 권한 프로필 테이블 + 필드 필터링 강제 + 공식 RSS/API 수집. 매체별 권한·전수조사·보존/AI 단계는 [content-rights-engine](2026-06-28-content-rights-engine.md). 베타 기본 = 전 매체 default-deny(제목+링크+메타).
3. **배포 설정** — `docker-compose`에 Caddy 서비스 + prod `.env` + CORS/WS 오리진.
4. **대화형 글쓰기 파이프라인(기능 3)** — 기존 dialogue 위에: 대화에서 주장·근거·핵심논점·빠진부분·논리구조 추출(cognition+argument 재사용) → AI 초안(LLM) → 반론·약한 근거 제시(debias/argument). 글루 + 프롬프트 위주.
5. **(신규) 의견 변화 기록** — 대화형 글쓰기 중 처음 주장→질문→수정 주장의 변화를 저장(세션/메시지 기반 + 경량 모델). 베타 슬라이스 중 유일하게 "새 도메인 데이터"에 가까움 — 구현 단계에서 범위 확정.
6. **게시글 이해 AI(기능 4)** — `argument_chat_ws.py` RAG를 **게시글 스코프**로(그 사용자 글 대상). 토픽 스코프 변형으로 **토론 흐름 요약(기능 5)** 도 제공(우리 토론 데이터, 출판사 원문 미사용).

> 위 1·4·5·6은 구현 계획 단계에서 기존 코드 확인 후 정확한 작업으로 분해한다.

---

## 6. Flutter 앱 구조(초안)

```
lib/
  main.dart
  core/        env(baseUrl), dio client, ws client, secure token store, error
  auth/        login/signup 화면 + 상태(provider) + repository
  feed/        화제·게시글 피드(홈, 인스타형) + repository
  compose/     대화형 글쓰기: 대화만 모드(WSS) → AI 대화분석 → 초안 → 수정 → 게시
               + 반론 제시 + 의견 변화 기록 UI + repository
  understand/  게시글 이해 AI 대화(게시글별 RAG, WSS) + repository
  discuss/     토론 흐름 요약 AI(화제별 찬반/쟁점) + 댓글 토론 + repository
  news/        권리 인지 뉴스(화제 소스) 화면 + repository
  shared/      위젯·테마·모델(서버 스키마 대응)
```

- 각 feature 폴더 = 화면 + provider + repository(통신). 백엔드 스키마에 대응하는 DTO만 보유.
- 디자인: 베타는 기능 검증 우선의 단정한 기본 UI(추후 디자인 고도화는 frontend-design 단계).

---

## 7. 보안·프라이버시

- 토큰: secure storage, refresh 자동 갱신(기존 백엔드 회전 정책 사용).
- 전송: 전구간 HTTPS/WSS(Caddy TLS). 평문 없음.
- prod 시크릿: dev 기본값 금지(백엔드가 production에서 거부). JWT/HMAC는 배포용 신규 생성.
- **외부 AI 고지:** 대화 원문이 Gemini(국외)로 전송됨 — 온보딩/약관/데이터안전 양식에 명시·동의(개인정보 국외이전 고지). 클로즈드 테스터 한정.
- Play 요구사항: 개인정보처리방침 URL, 데이터 안전 양식.

---

## 8. 테스트 전략

- **백엔드:** 기존 pytest 유지(유닛 166 + testcontainers 통합). 뉴스 읽기 엔드포인트·토론 병합에 통합 테스트 추가.
- **Flutter:** 핵심 위젯 테스트 + repository 단위 테스트(모킹). 1개 end-to-end(로그인→대화) integration_test.
- **수동:** 실기기에서 슬라이스 흐름 + 테스터 1~2인 베타 검증.

---

## 9. 비용

| 항목 | 비용 |
|---|---|
| Google Play Console | **$25 (일회성, 필수)** |
| Oracle Free Tier VM | $0 (카드 인증 필요) |
| 도메인/TLS | $0 (sslip.io) · 커스텀 시 ~$10/년 |
| Gemini 무료 API | $0 (rate limit) |
| **합계** | **≈ $25** |

---

## 10. 리스크 & 대응

| 리스크 | 대응 |
|---|---|
| Oracle A1 ARM 용량 확보('out of capacity') | **사용자가 콘솔에서 프로비저닝**(Claude가 단계별 가이드 제공). 용량 실패 시 다른 가용 도메인/리전 재시도, 안 되면 소형 AMD 무료 또는 저가 VPS. SSH 확보 후 배포는 Claude 수행 |
| ARM 이미지 빌드 이슈 | 멀티아치 베이스 확인, VM에서 직접 빌드(arm64 네이티브) |
| CPU 임베딩 지연(BGE-M3) | **3단계 점진적 강등 + 자가복구**(§3.1): 캐시/사전계산 → 백프레셔 큐+배치 → stub 폴백+지연 재임베딩. 핫패스 블로킹 0, 실패 0, stub은 일시적 |
| Gemini 무료 rate limit | 백오프 + 결정적 폴백(기존). 테스터 소수라 영향 작음 |
| 유료 매체 페이월 | 공개 RSS/헤드라인만 분석(설계 확정) |
| Play 심사·정책(외부 AI/데이터) | 개인정보처리방침·데이터안전·고지 선반영 |

---

## 11. 성공 기준 (베타)

- 테스터가 Play(클로즈드)에서 앱을 설치하고 **로그인 → 화제 피드 → (대화만 모드로) AI와 대화 → AI 초안 → 수정 → 게시 → 다른 글에서 '게시글 이해 AI'와 대화 → 화제 '토론 흐름 요약'으로 찬반/쟁점 확인**을 한 기기에서 수행할 수 있다.
- 백엔드가 Oracle VM에서 HTTPS/WSS로 안정 동작하고, 뉴스 tick이 자동으로 공개 RSS를 분석해 화제 피드에 반영한다.
- 월 인프라 비용 $0(일회성 Play $25 제외).

---

## 12. 가정 (구현 단계에서 검증)

- 대화(WSS)·게시글·광장·argument/debate 백엔드 엔드포인트가 외부 클라이언트(앱)에서 그대로 사용 가능(웹 프로토타입이 이미 사용 중).
- 기능 3(대화 분석→초안)·4(게시글 RAG)·5(토론 흐름 요약)는 기존 cognition/argument/argument_chat 재사용 + 스코프/프롬프트 수준으로 가능(구현 단계에서 `ai/argument`·`argument_chat_ws.py`·cognition 확인).
- "의견 변화 기록"(기능 3)만 경량 신규 데이터 — 세션/메시지 위에 얹을 수 있는지 확인 필요.
- A1 ARM에서 BGE-M3 CPU 임베딩이 베타 트래픽 수준에서 허용 가능한 지연.
