# 버들 화제 엔진(BTE, Buddle Topic Engine) 기술 설계서

**API 없는 RSS 기반 화제 발굴·설계 엔진 — 정보검색(IR)·데이터마이닝·그래프 마이닝 관점의 구현 설계**

| | |
|---|---|
| 상태 | 설계 확정본 v1 (구현 우선순위 §14 참조) |
| 절대 조건 | 외부 AI API 호출 0회 (OpenAI/Claude/Gemini/Perplexity/HF Inference/Cohere 등 전부 금지) |
| 허용 수단 | 알고리즘·통계·그래프 분석·**로컬** 모델(프로세스 내 실행)·규칙 기반 |
| 기준선 | 현행 v0 = `src/buddle/ai/news/topics.py` + `news_service.py` (배포 중) |
| 목표 | 사람보다 빠르게 "무엇이 화제가 될 것인가"를 찾아 구조화한다 |

설계 전반의 원칙: **판단은 전부 계산이다.** "중요해 보인다"는 존재하지 않고,
중요도는 항상 식(式)이며, 식의 모든 항은 로그에서 검증 가능한 관측값이다.

---

## 1. 전체 시스템 아키텍처

```
                 ┌─────────────────────────────────────────────────────────┐
                 │                     스케줄러 (3계층 주기)                  │
                 │  증분 tick 2min │ 재군집 60min │ 자기개선 배치 24h        │
                 └──────┬──────────────────┬───────────────────┬────────────┘
                        ▼                  ▼                   ▼
┌──────────┐   ┌──────────────┐   ┌──────────────┐   ┌────────────────┐
│ M1 RSS   │──▶│ M2 Parser    │──▶│ M3 Tagging   │──▶│ M4 Tag Graph   │
│ Collector│   │ (정규화)      │   │ (의미 태깅)   │   │ (관계·가중치)   │
└──────────┘   └──────────────┘   └──────┬───────┘   └───────┬────────┘
                                          │                   │
     ┌────────────────────────────────────┘                   ▼
     │            ┌──────────────┐   ┌──────────────┐   ┌────────────────┐
     │            │ M7 Trend     │◀──│ M6 Scoring   │◀──│ M5 Topic       │
     │            │ (상승/유지/하락)│   │ (화제 점수)   │   │ Discovery      │
     │            └──────┬───────┘   └──────┬───────┘   │ (그래프 군집)    │
     │                   │                  │           └───────┬────────┘
     │                   ▼                  ▼                   │
     │            ┌──────────────────────────────┐              │
     │            │ M8 Evolution (분화·병합·소멸)  │◀─────────────┘
     │            └──────────────┬───────────────┘
     │                           ▼
     │            ┌──────────────────────────────┐
     └───────────▶│ M9 Content Planning (기획 데이터)│──▶ 화제 카드·화제 글·대화 주입
                  └──────────────┬───────────────┘
                                 ▼
                  ┌──────────────────────────────┐
                  │ M10 Self-Improving (피드백 루프)│◀── 클릭·조회·체류·공유·검색·수정
                  └──────────────────────────────┘

저장소:  PostgreSQL(정본: 기사·태그·그래프·화제·계보·이벤트)
         Redis(핫캐시: 최신 화제·seen-set·소스 레지스트리·서빙 스냅숏)
메모리:  분석 시점에만 그래프를 scipy.sparse CSR로 적재(§9)
```

**설계 결정 — 전용 그래프 DB를 쓰지 않는다.** 예상 규모(태그 10⁴~10⁵ 노드,
엣지 10⁵~10⁶)에서 Neo4j류는 운영 비용만 늘린다. PostgreSQL 인접 테이블 +
분석 시 인메모리 희소행렬이 같은 일을 1/10 비용으로 한다. 규모가 10⁷ 엣지를
넘으면 그때 분리한다(§15).

## 2. 데이터 흐름도 (주기별)

```
[2분 증분 tick]   RSS fetch → 정규화 → 신규 기사만: 태깅 → 태그 통계 갱신
                  → 엣지 증분 가산 → 활성 화제에 기사 편입(국소 재할당)
                  → 점수 재계산(활성 화제만) → Redis 서빙 스냅숏 교체
                  예산: p95 < 5s (네트워크 제외 < 500ms)

[60분 재군집]     전체 그래프 시간감쇠 → Leiden 재군집 → M8 매칭(분화/병합)
                  → 계보 기록 → 대표성/기획 데이터 재생성
                  예산: < 30s @ 10⁵ 엣지

[24시간 배치]     참여 로그 집계 → 점수 가중치 w 갱신 → 사전 확장 후보 제안
                  → 그래프 프루닝(약한 엣지 삭제) → 시계열 롤업
```

증분(2분)과 재군집(60분)의 분리가 이 설계의 핵심 리듬이다. 군집화는 비싸고
전역적이므로 자주 돌릴 수 없고, 편입·점수는 싸고 국소적이므로 실시간에 가깝게
돌린다. 두 경로가 같은 정본 테이블을 쓰므로 서빙 결과는 항상 일관된다.

---

## 3. 모듈 설계

각 모듈은 입력 / 출력 / 내부 알고리즘 / 복잡도 / 병목 / 개선 순으로 기술한다.
표기: N=윈도우 내 기사 수, S=소스 수, T=태그 수, E=엣지 수, C=화제 수.

### M1. RSS Collector

| | |
|---|---|
| 입력 | 소스 레지스트리(Redis `buddle:news:sources`: id, url, kind, limit, enabled, etag, last_modified, poll_state) |
| 출력 | `RawArticle[]` (title, url, source, summary, published_at, guid) |
| 현행 v0 | `fetcher.py` — asyncio 병렬 fetch, guid/URL 해시 dedup, SSRF 가드 |

**내부 알고리즘**

1. **조건부 GET(갱신 감지)**: 소스별 `ETag`/`Last-Modified`를 저장하고
   `If-None-Match`/`If-Modified-Since`로 요청한다. 304면 파싱 자체를 생략.
   2분 폴링에서 트래픽의 대부분은 "변화 없음"이므로 이것이 최대 절감 지점이다.
2. **적응형 폴링(AIMD)**: 소스별 `poll_interval`을 갱신 이력으로 조정.
   새 항목 발견 시 interval ← max(2min, interval/2), 연속 k회 무변화 시
   interval ← min(30min, interval+2min). 정부 보도자료(주간 리듬)와 통신사
   피드(분 단위)를 같은 주기로 두드리는 낭비를 없앤다. 전역 tick은 2분으로
   유지하되 due가 된 소스만 실제 fetch한다.
3. **URL 정규화 → 1차 중복 제거**: 스킴/호스트 소문자화, 기본 포트 제거,
   추적 파라미터 제거(`utm_*, fbclid, gclid, ref`), fragment 제거, 말미 `/`
   정리 → SHA-256 → Redis seen-set(48h TTL) 선필터 → **DB `news_items.guid
   UNIQUE + ON CONFLICT DO NOTHING`이 최종 보증**(현행 유지. Redis 소실 실측
   2회가 근거).
4. **준중복(재전송 기사) 탐지 — SimHash**: 제목+요약 토큰의 64-bit SimHash를
   저장하고 해밍거리 ≤ 3이면 준중복으로 접는다(같은 통신사 기사를 여러 매체가
   전재하는 한국 뉴스 생태계에서 필수). 비교는 4-밴드 LSH 버킷으로 O(1) 근사.
5. **시간 정렬·출처 관리**: published_at(RFC-822/ISO 파싱, 실패 시 수집 시각)
   으로 정렬. 출처별 신뢰 계수 r_s(§M3 confidence의 입력)를 레지스트리에 저장.

**복잡도** 시간 O(S + N_new), 공간 O(seen-set) = O(48h 기사 수).
SimHash LSH로 준중복 검사도 기사당 O(1) 기대.

**병목** 네트워크 왕복. → asyncio 동시 fetch(현행) + 조건부 GET + 호스트별
동시성 1 제한(politeness).

**개선 여지** WebSub(PubSubHubbub) 지원 피드는 푸시 구독으로 전환해 폴링 자체를
제거. 소스 수 수백 이상이면 fetch 워커 샤딩(소스 id 해시).

### M2. Document Parser

| | |
|---|---|
| 입력 | RSS `<item>`/`<entry>` 원문 블록 |
| 출력 | 정규화 문서 레코드: {title, summary, body?, published_at, category?, author?, link, source, lang} |
| 현행 v0 | 정규식 경량 파서 — title/link/description/pubDate, CDATA, 엔티티 해제 |

**내부 알고리즘**

1. **필드 추출**: RSS 2.0/Atom 겸용. `title, link(+href 속성형), description/
   summary/content, pubDate/published/updated, category*, dc:creator/author`.
2. **HTML 노이즈 제거 전략(계층형)**:
   - L1(현행): 태그 스트립 → `html.unescape` → 공백 접기.
   - L2: 블록 태그를 문장 경계로 치환(`<br>,<p>,<li>` → `. `)해 문장 분리 품질
     을 지킨다. `<script>/<style>` 내용물 통삭제.
   - L3(본문 수집을 켤 경우만): 텍스트 밀도 기반 보일러플레이트 제거 —
     DOM 블록별 (텍스트 길이 / 마크업 길이) 비율과 링크 밀도로 본문 블록 판별
     (Readability/JusText의 핵심 아이디어를 규칙으로 재구현).
     **단, 버들 기본값은 본문 미수집이다** — 권리 엔진 default-deny 정책상
     제목·링크·요약 스니펫까지만 저장한다. L3는 라이선스가 확인된 소스
     (공공누리 제1유형)에 한해 소스별 플래그로만 켠다.
3. **문장 분리(한국어)**: 종결 패턴 `(?<=[.!?다요])\s+`(현행) + 인용부호 내부
   보호. 발췌 요약(M9의 evidence)과 태깅 창(window) 산정의 기반.
4. **정규화**: NFC 유니코드 정규화, 전각→반각, 연속 문장부호 축약, 날짜는
   UTC epoch 초로 통일.

**복잡도** 기사당 O(L) (L=텍스트 길이). **병목** 없음(정규식 선형 스캔).
**개선** lxml 도입 시 파싱 견고성↑(외부 *AI* 아닌 로컬 라이브러리는 허용) —
다만 무의존 정규식 파서가 배포 단순성에서 이겨 v0 유지, 실패 로그가 쌓이는
피드에만 lxml 폴백.

### M3. Semantic Tagging Engine

| | |
|---|---|
| 입력 | 정규화 문서 |
| 출력 | `article_tags[]`: (article_id, tag_id, tag_type, weight) + 태그 사전 갱신 |
| 현행 v0 | 조사 스트리핑 토크나이저 + 스톱워드/활용어미 필터 + 카테고리·지역 렉시콘 |

**후보 추출 알고리즘 비교와 채택**

| 알고리즘 | 장점 | 단점 | 판정 |
|---|---|---|---|
| TF-IDF | 안정적, 구현 즉시 | 코퍼스 통계 필요, 신조어에 늦음, 짧은 텍스트 약함 | **배치 가중치로 채택**(72h 코퍼스 IDF를 일 1회 갱신, 흔한 단어 감점) |
| BM25 | 포화(saturation) 처리 우수 | 태깅용이라기보다 검색 랭킹용 | 태깅엔 미채택, **§12 검색에 채택** |
| TextRank | 비지도, 문서 내 그래프로 핵심어 추출 | 짧은 요약(1~3문장)에선 그래프가 빈약 | 문서 단위 미채택, **화제 단위(클러스터 합산 텍스트) 대표 구문 추출에 채택** |
| RAKE | 빠름, 구두점/불용어 경계 기반 | 영어 형태 전제가 강함(한국어 교착어에 부적합) | 미채택 |
| YAKE | 통계적·언어 중립·짧은 텍스트 강함, 코퍼스 불요 | 파라미터 민감 | **문서 단위 후보 추출 주력으로 채택**(전처리=조사 스트리핑 후 적용) |
| N-gram + C-value | 복합명사("전기차 보조금") 포착 | 후보 폭증 | **어절 bigram + C-value 필터로 채택** |
| PMI/NPMI | 연어 발견의 표준 | 저빈도 과대평가(PMI) | **NPMI ≥ 0.35 bigram 병합에 채택** |

채택 파이프라인: `토큰화(조사·활용어미·상투어 필터, 현행)` → `unigram+bigram
후보` → `NPMI 병합` → `YAKE 점수 × IDF 감점 × 위치 가중(제목 2.0/첫문장 1.5/
요약 1.0)` → 상위 k=12 태그.

**태그 유형(9종) 분류 — 전부 규칙·통계·사전으로**

| 유형 | 판별 방법 |
|---|---|
| Domain | 카테고리 렉시콘 투표(현행 6버킷: 환경·교육·경제·정치·기술·사회) — 확장: 버킷별 근거 히트 수를 confidence로 저장 |
| Topic | 기본형 — 위 파이프라인 통과 태그 |
| Entity | gazetteer(행정구역 현행 + 기관·기업·인물 사전) + 패턴(`…시/…구/…군/…부/…청/…법/…위원회`, 영문 대문자 연속, 따옴표 내 고유명) |
| Event | **상투어의 재활용**: v0가 스톱워드로 버리는 "발표·통과·개편·출시·체결"을 *태그명으로는 금지하되 이벤트 타입 신호로 승격*. `(Entity|Topic) 창(±5토큰) 내 이벤트 동사` → (tag, event_type, date) 튜플 |
| Problem | 신호 렉시콘: 급증·우려·논란·부족·지연·마비·피해·적자 … + 신호와 공기하는 명사구를 문제 태그로 |
| Solution | 신호 렉시콘: 대책·도입·지원·개편안·합의·타결 … + 동일 창 규칙 |
| Technology | 기술 렉시콘(현행 기술 버킷 어휘) + 영문 약어 패턴(`[A-Z]{2,5}`, `…AI/…GPT/…반도체`) |
| Trend | 태그 자체가 아니라 **파생 속성**: M7의 버스트 상태가 on인 태그에 플래그 |
| Hidden | **구조 발견**: (a) 저빈도·고NPMI 연결쌍 (b) 그래프 브리지 노드 — 커뮤니티 간 betweenness 상위인데 문서 빈도 하위 40%인 태그. "표면 빈도는 낮지만 구조적으로 중요한" 신호 |

**태그 레코드(사전) 스키마** — 요구 필드 전부 포함:

```sql
CREATE TABLE tags2 (            -- 기존 tags(글 해시태그)와 분리, 화제 엔진 전용
  id            BIGSERIAL PRIMARY KEY,
  name          TEXT UNIQUE NOT NULL,
  tag_type      TEXT NOT NULL,            -- domain|topic|entity|event|problem|solution|tech|hidden
  importance    REAL NOT NULL DEFAULT 0,  -- 전역 PageRank(주기 갱신)
  confidence    REAL NOT NULL DEFAULT 0,  -- 판별 근거 강도(사전 히트·패턴 매칭 수 정규화)
  freq          INTEGER NOT NULL DEFAULT 0,       -- 누적 출현
  article_count INTEGER NOT NULL DEFAULT 0,       -- 연결 기사 수(고유)
  first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_tags2_last_seen ON tags2(last_seen);
```

**복잡도** 기사당 O(L + k²)(NPMI 창 계산 포함). 10⁴ 기사/일에도 단일 코어로 초 단위.
**병목** gazetteer 조회 → Aho-Corasick 오토마톤으로 사전 전체를 O(L) 단일 스캔에 매칭.
**개선** Phase 3에서 로컬 NER(KoELECTRA-small, ONNX Runtime, 프로세스 내 실행 —
외부 API 아님)로 Entity 재현율 보강. 사전은 M10의 수정 이력으로 반자동 확장.

### M4. Relationship Graph

| | |
|---|---|
| 입력 | article_tags(신규 기사분) |
| 출력 | `tag_edges` 갱신 (src, dst, rel, weight, evidence_count) |

**관계 유형별 생성 규칙**

| 관계 | 생성 규칙 | 가중치 |
|---|---|---|
| related-to | 같은 기사 공기(co-occurrence) | NPMI(x,y) × log1p(공기 수) |
| is-a / part-of | 사전 계층(구⊂시⊂도⊂전국, 기술 분류 트리) + 패턴("X는 Y의 하나", 접미 포함 관계 "성남시"⊂"경기") | 규칙 신뢰도 고정(0.9) |
| causes | 인과 연결어 창(`…로 인해/탓에/영향으로/여파`) 내 공기 **+ 시차 상관**: x의 버스트가 y의 버스트를 τ 시간 선행하는 lag-상관 ≥ 0.4 (Granger 인과의 경량 근사) | 언어 근거 0.6 + 시차 근거 0.4 |
| affects | causes보다 약한 연결어(`…에 영향/…를 흔들`) | 0.5 |
| competes-with | 동일 Domain + Entity 쌍 + 같은 기사 공기율은 낮고(NPMI<0) 같은 화제 교차 언급은 높음 | 교차빈도 정규화 |
| supports | 긍정 연결어 창(`…를 지원/뒷받침/촉진`) | 0.5 |
| evolves-into | M8 계보 매칭 결과(분화·승계) | Jaccard 연속성 |

**시간 감쇠**: 60분 배치마다 `weight ← weight·exp(−Δt·ln2/τ)`, τ=7일.
evidence_count는 감쇠하지 않는다(누적 근거는 이력).

**저장/적재**: 정본은 PostgreSQL 인접 테이블, 분석 시 `scipy.sparse` CSR로
일괄 적재(10⁶ 엣지 ≈ 24MB, 적재 < 1s). 이 이원화가 "그래프 DB 없이 그래프
마이닝"을 성립시킨다.

```sql
CREATE TABLE tag_edges (
  src BIGINT REFERENCES tags2(id), dst BIGINT REFERENCES tags2(id),
  rel TEXT NOT NULL,                 -- related|isa|part|causes|affects|competes|supports|evolves
  weight REAL NOT NULL,
  evidence_count INTEGER NOT NULL DEFAULT 1,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (src, dst, rel)
);
```

**복잡도** 기사당 엣지 갱신 O(k²), k=12 → 66 upsert. 감쇠 배치 O(E).
**병목** upsert 폭주 → 기사 배치 단위로 메모리 집계 후 `ON CONFLICT DO UPDATE`
벌크 1회. **개선** 엣지 수 상한 초과 시 weight 하위 프루닝(§15).

### M5. Topic Discovery — 태그 그래프 군집이 화제다

| | |
|---|---|
| 입력 | 시간감쇠 적용된 related-to 서브그래프(최근 72h에 last_seen이 있는 태그 유도 부분그래프) |
| 출력 | `topics` + `topic_tags` + `topic_articles` |

**군집 알고리즘 비교와 채택**

| 알고리즘 | 장점 | 단점 | 판정 |
|---|---|---|---|
| Louvain | 빠름 O(E·logV) | 해상도 한계, **비연결 커뮤니티 생성 가능**, 비결정성 | 미채택 |
| **Leiden** | Louvain 결함 수정(연결성 보장), 품질·속도 우수, 증분 국소이동 지원 | 구현 복잡(라이브러리: igraph/leidenalg — 로컬 라이브러리, 허용) | **주 알고리즘 채택** |
| Label Propagation | 초고속 O(E) | 불안정(실행마다 상이) | 폴백(라이브러리 불가 환경)만 |
| K-Means | 단순 | k 사전 지정, 그래프 부적합 | 미채택 |
| DBSCAN | 밀도 기반 | ε 민감, 그래프엔 간접적 | 미채택 |
| **HDBSCAN** | ε 불요, 노이즈 라벨, 가변 밀도 | 임베딩 공간 필요 | Phase 3에서 **임베딩 군집 교차검증용** 채택 |
| v0 키워드-겹침 병합 | 의존성 0, 검증 완료 | 전이적 병합 한계(A~B, B~C인데 A≁C) | **Phase 1까지 유지, Leiden으로 대체** |

해상도 파라미터 γ는 "화제 수 8~30개/72h"를 목표로 이분 탐색 자동 조정
(운영 지표를 파라미터가 따라가게 한다 — 반대가 아니라).

**화제 레코드 구성**(요구 필드 전부):

- 대표 태그: 커뮤니티 유도 부분그래프의 **가중 PageRank 최상위**, 동률 시
  한국어 태그 우선(한국 전용 서비스 정책).
- 관련 태그: PageRank 내림차순 상위 10.
- 관련 기사: 커뮤니티 태그를 2개 이상 포함하는 기사(가중 겹침 점수순).
- 핵심 기업/인물(Entity), 핵심 기술(Technology), 핵심 문제(Problem):
  커뮤니티 내 해당 tag_type 상위 3개씩.
- 성장 속도: M7의 growth 항. 지속 기간: first_seen(커뮤니티 최초 관측)~now.

**증분 편입(2분 tick)**: 신규 기사의 태그 벡터와 활성 화제의 태그 집합 간
가중 Jaccard 최대 화제에 편입(임계 0.25 미만이면 미배정 풀 — 다음 재군집이
처리). 전체 재군집은 60분 주기만: 군집 경계의 정확성과 서빙 지연의 트레이드
오프를 주기 분리로 해소.

**복잡도** Leiden O(E·logV) ≈ 10⁶ 엣지에 수 초. 증분 편입 기사당 O(C·k̄).
**병목** 재군집 중 서빙 → 새 결과를 그림자 테이블에 쓰고 트랜잭션 스왑.
**개선** Phase 3: 문서 임베딩(로컬 ko-sbert ONNX) HDBSCAN 군집과 그래프
커뮤니티의 합의(consensus)로 경계 품질 상승.

### M6. Topic Scoring

요구된 9개 요소를 전부 항으로 명시한다. 모든 항은 [0,1] 정규화 후 가중 합산.

```
S(T) = w₁·volume + w₂·growth + w₃·diversity + w₄·centrality + w₅·cohesion
     + w₆·novelty + w₇·persistence + w₈·influence + w₉·engagement

volume      = log1p(A_T) / log1p(max_T' A_T')          A_T = 윈도우 내 기사 수
growth      = σ( ln( (A_recent/Δt₁) / (A_prior/Δt₂ + ε) ) )   최근6h 대 이전66h 비율의 로그를 시그모이드로
diversity   = H(source 분포) / ln(S_T)                  소스 엔트로피 정규화(1=완전 다양)
centrality  = Σ_{t∈T} PR(t) / Σ_전체 PR                 전역 PageRank 질량 점유율
cohesion    = 1 − conductance(T)                        내부 엣지 질량/경계 엣지 질량 — 잡탕 클러스터 감점
novelty     = exp(−age_first / 72h)                     처음 등장한 화제 가산
persistence = 활동 시간조각 수 / 윈도우 시간조각 수        띄엄띄엄이 아니라 꾸준한가
influence   = Σ 커뮤니티 외부로 나가는 causes/affects 가중치 (정규화)
engagement  = EWMA(클릭률·체류·댓글·공유 합성, §M10)      선택 항 — 로그 축적 전 0
```

**가중치 산정** — 두 단계:
1. 초기값(콜드스타트): w = (0.20, 0.20, 0.15, 0.10, 0.10, 0.10, 0.05, 0.05, 0.05).
   근거: v0 실측에서 volume·growth·diversity가 사람 판단과 가장 상관이 높았다
   (다양성 부스트 도입 후 오탐 감소 실측).
2. 온라인 학습(§M10): 노출-클릭 쌍으로 pairwise 학습. 화제 i가 j보다 위에
   노출되고 j만 클릭되면 (j≻i) 샘플 → Bradley-Terry-Luce 모형의 로지스틱
   SGD로 w 갱신(학습률 0.01, 일 1회, L2 정규화). **위치 편향 보정**: 노출
   순위 r의 클릭은 1/propensity(r)로 역가중(추정 propensity는 순위별 전역
   CTR).

### M7. Trend Prediction — 상승/유지/하락 확률

| 알고리즘 | 장점 | 단점 | 판정 |
|---|---|---|---|
| 단순 기울기 | 즉시 구현 | 소표본 노이즈에 취약 | 미채택 |
| **이중 EWMA 교차** | 빠름, O(1) 증분, 방향성 명확 | 확률 해석 없음 | **방향 신호로 채택** (fast τ=2h / slow τ=24h) |
| **Kleinberg burst detection** | 2-상태 자동자, 이론적 근거, 버스트 구간 경계 산출 | 오프라인 세그먼트 계산 | **버스트 판정으로 채택**(60분 배치에서 실행) |
| **포아송-감마 베이지안** | 소표본에서 건전한 확률, conjugate라 증분 O(1) | 정상성 가정 | **확률 산출로 채택** |
| ARIMA | 표준 시계열 | 짧고 비정상적인 화제 수명에 부적합, 화제별 적합 비용 | 미채택 |
| Prophet | 계절성 자동 | 의존성 무겁고 과잉 | 미채택 |

**결합 규칙**: 화제별 시간당 기사 수를 λ로 보고, 사전분포 Gamma(α₀,β₀)에
최근 6h 관측을 갱신한 사후분포에서 `P(λ_now > λ_base)`를 닫힌형으로 계산
(λ_base = 이전 66h 평균). 그 확률 p와 EWMA 방향 d, Kleinberg 버스트 상태 b로:

```
P(상승) = p·𝟙[d>0]·(1 + 0.5·b) 정규화
P(하락) = (1−p)·𝟙[d<0] 정규화
P(유지) = 1 − P(상승) − P(하락)
```

**복잡도** 화제당 O(1) 증분(카운트 갱신 + conjugate 갱신). Kleinberg는 배치
O(n log n)/화제. **병목** 없음. **개선** 예측 적중 로그를 M10에 회수 —
예측 후 6h 실측과 비교해 Brier score를 계기판에 노출.

### M8. Topic Evolution — 분화·병합·소멸 추적

**알고리즘**: 스냅숏 t와 t+1(60분 간격)의 커뮤니티 집합 간 **가중 Jaccard
유사도 행렬** J[i][j] = |Tᵢ∩T'ⱼ|_w / |Tᵢ∪T'ⱼ|_w (태그 PageRank 가중).

매칭 규칙(그리디, J 내림차순 소진):

```
J ≥ 0.6 인 1:1 최대 매칭            → 지속(same)   — topic_id 승계
행 i가 열 j₁,j₂,… 에 0.3≤J<0.6 다중 → 분화(split)  — 자식들 생성, evolves-into 엣지
열 j가 행 i₁,i₂,… 에서 다중 수신     → 병합(merge)
행 i가 무매칭 & 활동 0              → 소멸(dead)   — 3윈도우 유예 후 확정(재점화 대비)
열 j가 무매칭                       → 탄생(born)   — novelty 만점
```

계보는 DAG로 저장한다:

```sql
CREATE TABLE topic_lineage (
  parent_id BIGINT, child_id BIGINT, event TEXT,   -- same|split|merge|dead|born
  jaccard REAL, at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (parent_id, child_id)
);
```

**왜 헝가리안이 아닌 그리디인가**: C≤50 규모에서 최적 매칭과 그리디의 차이가
관측되지 않으며(J 행렬이 희소·대각 우세), 그리디는 O(C² log C)로 충분하고
설명 가능하다. C가 수백을 넘으면 헝가리안 O(C³) 교체를 §15에 예약.

### M9. Content Planning — 글이 아니라 설계 데이터를 생성한다

화제당 아래 JSON을 **전부 조회·규칙으로** 채운다(생성 없음 — 모든 값은
그래프/통계 질의 결과이므로 환각이 구조적으로 불가능):

```jsonc
{
  "topic_id": 1234,
  "core_questions":  // 이벤트·문제 타입별 질문 템플릿 (규칙표에서 선택)
    ["'전기차 보조금' 개편은 누구에게 영향을 주는가?",     // affects 엣지 대상
     "왜 지금 논의되는가?",                               // 버스트 시점 + causes 역추적
     "'소비자 문의 폭주'는 해소 가능한가?"],               // Problem 태그 존재 시
  "core_claims":     // 스탠스 축: 찬반 신호 렉시콘으로 기사 분포를 나눈 결과
    [{"axis": "보조금 축소", "pro_articles": 3, "con_articles": 2}],
  "evidence":        // 필수 근거 = 헤드라인 + 출처 + 시각 (rights-safe 표면만)
    [{"title": "...", "source": "...", "url": "...", "published_at": "..."}],
  "linked_topics":   // 그래프 이웃 커뮤니티 (related 엣지 질량 상위)
    [{"topic_id": 1201, "name": "배터리", "rel": "related-to", "w": 0.42}],
  "reader_questions",// 독자 궁금증: 검색 로그 co-query + 고centrality 미연결 이웃 태그
  "deep_dive_points",// 심층 포인트: Hidden 태그 상위 (구조적으로 중요, 표면 빈도 낮음)
  "comparisons",     // 비교 대상: competes-with 엣지
  "followups"        // 후속 아이디어: evolves-into 예측(M8) + P(상승) 상위 인접 화제
}
```

이 구조가 화제 글(광장 게시), 대화 AI 주입 블록, 토론장 시드의 공통 입력이
된다 — 소비처가 3곳이어도 생성은 1곳.

### M10. Self-Improving Engine

**수집(전부 구현 대상)** — 단일 이벤트 테이블로 통합:

```sql
CREATE TABLE engagement_events (
  id BIGSERIAL PRIMARY KEY,
  kind TEXT NOT NULL,        -- impression|click|view|dwell|share|search|tag_fix
  topic_id BIGINT NULL, tag_id BIGINT NULL,
  user_hash TEXT NULL,       -- 개인화용 해시(원 식별자 비저장)
  value REAL NULL,           -- dwell 초, 검색어 해시 빈도 등
  rank_at_impression INT NULL,   -- 위치 편향 보정용
  at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- 클릭률/조회수/공유: 화제 카드 노출·클릭·상세 조회·공유 버튼 이벤트.
- 체류시간: 상세 진입~이탈 dwell(글 길이로 정규화 — 스크롤 통과 배제, 기존
  read_count 신호와 동일 사상).
- 검색 로그: 검색어(해시)와 클릭 결과 화제 — co-query 통계는 M9
  reader_questions의 원천.
- 태그 수정 이력: admin의 태그/분류 수정 = **골드 라벨**. (오분류 원문,
  잘못 판정된 버킷, 올바른 버킷)을 축적.

**업데이트(전부 구현 대상)**

| 대상 | 알고리즘 | 주기 |
|---|---|---|
| 화제 점수 가중치 w | BTL pairwise 로지스틱 SGD + 위치편향 역가중(§M6) | 일 1회 |
| 태그 가중치/사전 | 골드 라벨로 버킷별 정밀도 산출 → 오분류 유발 어휘 자동 탐지(해당 어휘 제거/이동 시 정밀도 변화 시뮬레이션) → **후보를 제안 큐에 적재, admin 1클릭 승인**(사전 자동 변이는 감사 가능해야 하므로 human-in-the-loop) | 일 1회 |
| 관계 강도 | 헤비안 강화: 클릭된 화제의 내부 엣지 weight ×(1+η), 노출-무클릭 화제는 ×(1−η/4), η=0.02 — 감쇠(§M4)와 균형 | 일 1회 |
| 추천 정확도 | 사용자 해시별 (Domain, scope) 선호 EWMA → 화제 목록 개인화 재랭킹(§12) | 실시간 EWMA |
| 탐험 | ε-greedy(ε=0.1): 목록 하위 슬롯 1개는 신생(novelty 상위) 화제에 배정 — 피드백 루프의 부익부 고착 방지 | 상시 |

**병목/위험** 피드백 루프의 자기강화(인기가 인기를 부름) → 위치편향 보정 +
ε-탐험 + novelty 항이 3중 방어. 이벤트 테이블 성장 → 월 파티셔닝, 90일 롤업.

---

## 4. 데이터베이스 구조(전체 DDL 요약)

```
news_items        (현행 0024) 기사 정본: guid UNIQUE, title, url, summary,
                  category, scope, region, published_at, simhash BIGINT(추가)
tags2             §M3 — 태그 사전(유형·중요도·신뢰도·빈도·시점)
article_tags      (article_id, tag_id, weight, PRIMARY KEY(article_id, tag_id))
tag_edges         §M4 — 관계 그래프 인접 테이블
topics            (id, rep_tag_id, name, category, scope, region, score,
                   p_rise, p_hold, p_fall, first_seen, last_seen, status)
topic_tags        (topic_id, tag_id, pagerank REAL)
topic_articles    (topic_id, article_id, overlap REAL)
topic_series      (topic_id, bucket_ts, article_count)  -- 시간당 롤업
topic_lineage     §M8 — 계보 DAG
topic_plans       (topic_id, plan JSONB)                -- §M9 산출물
engagement_events §M10
scoring_weights   (version, w JSONB, trained_at)        -- w 이력(롤백 가능)
```

Redis(휘발/서빙): `buddle:news:topics`(서빙 스냅숏), `buddle:news:seen`,
`buddle:news:sources`(+etag/poll_state), `buddle:news:topicpost:*`(화제↔글 매핑).

## 5. 그래프 구조 / 6. 태그 구조

§M4·§M3에 DDL과 함께 명세. 핵심 불변식:
- 그래프의 정본은 SQL, 분석은 CSR 스냅숏 — 두 표현 사이 변환은 단방향(적재)뿐.
- 태그명은 표면형이 아니라 정규형(조사·활용 제거 후)만 허용. 표면형→정규형
  매핑은 태깅 시점에만 존재하고 저장하지 않는다(저장하면 드리프트).

## 7. 화제 생성 과정(종단 요약)

```
RSS(M1) → 정규화(M2) → 태깅(M3): 기사→태그 9종
→ 그래프 갱신(M4): 공기·인과·계층 엣지
→ [60분] Leiden 군집(M5) = 화제 / [2분] 신규 기사 국소 편입
→ 점수(M6)·추세(M7) → 계보(M8) → 기획 데이터(M9)
→ 서빙: 화제 카드(홈/관심주제) + 화제 글(광장, 좋아요·댓글·토론) + 대화 주입
→ 반응 수집(M10) → 가중치·사전·엣지 갱신 → (다시 M3~M6에 반영)
```

## 8. 화제 점수 계산식

§M6에 완전 명세(9항 가중합 + BTL 온라인 학습 + 위치편향 보정).

## 9. 성능 최적화 전략

1. **조건부 GET + AIMD 폴링**(M1): 2분 tick의 실제 fetch를 필요 소스로 축소.
2. **Aho-Corasick 사전 매칭**(M3): gazetteer 수만 항목도 기사당 선형 스캔 1회.
3. **벌크 upsert**(M4): 기사 배치 집계 후 1회 커밋 — 행 단위 커밋 금지.
4. **CSR 인메모리 분석**(M4/M5): PageRank·Leiden·conductance 전부 희소행렬
   연산으로 — 10⁶ 엣지에서 PageRank(멱반복 50회) < 2s.
5. **그림자 테이블 + 스왑**(M5): 재군집이 서빙을 절대 블록하지 않는다.
6. **화제별 O(1) 증분 통계**(M6/M7): 카운터·EWMA·conjugate 사후분포는 모두
   증분 갱신 가능 자료구조만 채택했다 — 이것이 알고리즘 선택 기준이었다.

## 10. 증분 업데이트 전략

- 신규 기사: 태깅 → 엣지 가산 → 화제 편입 → 해당 화제만 점수 재계산(O(1)).
- 신규 태그: 미배정 풀 → 다음 재군집에서 커뮤니티 획득.
- 엣지 감쇠·프루닝: 60분/24h 배치로만 — 증분 경로는 절대 전역 연산 금지.
- 서빙 스냅숏: 매 tick 끝에 Redis에 원자 교체(SETEX) — 부분 갱신 노출 없음.

## 11. 대용량 RSS 처리 전략 (수천~수만 건/일)

| 규모 | 전략 |
|---|---|
| ~10³/일 (현재) | 단일 프로세스 asyncio — 현행 구조 그대로 |
| ~10⁴/일 | fetch 워커 샤딩(소스 해시), 태깅 프로세스 풀(CPU 바운드 분리), Postgres COPY 벌크 적재 |
| ~10⁵/일 | 빈도 계수를 Count-Min Sketch로(정확 카운트는 상위 후보만), SimHash LSH 밴드 수 확대, 엣지 상한+주기 프루닝, topic_series 사전 롤업 |
| 그 이상 | 스트림 큐(Redis Streams) 도입, 시간 파티션 병렬 군집(파티션별 Leiden 후 메타 병합) |

## 12. 검색 및 추천 활용 방안

- **검색**: `news_items(title, summary)`에 PostgreSQL FTS(기본) + **BM25**
  재랭킹(k1=1.2, b=0.75; 짧은 문서라 b 하향 튜닝 여지). 검색 로그는 M10으로
  환류.
- **추천**: 사용자 (Domain, scope) 선호 EWMA(M10) × 화제 점수 S(T)의 곱
  재랭킹 + ε-탐험 슬롯. 위치 필터(우리 동네/시/도)는 **자동 매칭이 아니라
  사용자 선택 필터**(서비스 원칙 유지).
- **대화 AI 주입**: M9의 evidence + core_questions 블록을 그대로 주입 —
  대화 모델이 화제를 "아는 것처럼" 말하는 근거가 전부 검증 가능 표면 데이터.

## 13. 확장 가능한 플러그인 구조

```python
class SourcePlugin(Protocol):      # M1 — rss|hackernews|devto|websub|api...
    async def fetch(self, cfg: SourceCfg) -> list[RawArticle]: ...

class TaggerPlugin(Protocol):      # M3 — yake|gazetteer|ner_onnx|...
    def tag(self, doc: Document) -> list[TagHit]: ...

class ScorerTerm(Protocol):        # M6 — 항 단위 플러그인 (이름, [0,1] 값)
    def value(self, topic: TopicStats) -> float: ...

class Predictor(Protocol):         # M7
    def probabilities(self, series: Series) -> tuple[float, float, float]: ...
```

레지스트리에 이름으로 등록, 소스/파이프라인 설정에서 조합. 신규 알고리즘은
플러그인 추가일 뿐 파이프라인 코드 수정이 아니다. (현행 `_ALLOWED_KINDS`
dispatch가 SourcePlugin의 초기형.)

## 14. 구현 우선순위 (MVP → 고도화)

| Phase | 내용 | 의존성 | 상태 |
|---|---|---|---|
| **P0** | v0 파이프라인: 수집·파싱·DB dedup·키워드 군집·범위/주제 분류·발췌·다이제스트·필터 API | 없음 | **배포 완료** |
| **P1** | 태그 사전(tags2)+article_tags, 공기 그래프(related-to만), PageRank 대표성, 이중 EWMA+포아송-감마 추세, SimHash 준중복, 조건부 GET, 서빙에 P(상승) 노출 | 순수 파이썬+Postgres, 외부 의존 0 | 다음 구현 |
| **P2** | Leiden 군집(igraph), 관계 유형 확장(causes/competes/isa), M8 계보, M9 기획 데이터, Kleinberg 버스트 | igraph(로컬 lib) | |
| **P3** | 로컬 임베딩(ko-sbert ONNX) + HDBSCAN 교차검증, ANN(HNSW/pgvector 재활용), NER 보강 | onnxruntime | |
| **P4** | M10 전체(이벤트 수집→BTL 학습→사전 제안 큐→개인화 재랭킹→ε-탐험) | P1~P3 로그 축적 | |

각 Phase는 독립 배포 가능하고, 이전 Phase의 서빙 계약(`GET /v1/news/topics`
스키마)을 깨지 않는다.

## 15. 예상 병목과 해결 방안

| 병목 | 증상 | 해결 |
|---|---|---|
| RSS 폴링 낭비 | 2분마다 전 소스 fetch, 대부분 무변화 | 조건부 GET + AIMD(§M1) — 실측 90%+ 절감 예상 |
| 통신사 전재 중복 | 같은 기사가 여러 소스로 유입, 화제 부풀림 | SimHash LSH(§M1) |
| 상투어 오클러스터 | v0 실측('개편' 병합 사건) | 스톱워드(완료) + P1 공기 그래프에서 NPMI가 구조적으로 재차단 |
| 엣지 테이블 비대 | E > 10⁶에서 감쇠 배치 지연 | weight 하위 프루닝 + updated_at 파티셔닝 |
| 재군집 지연 | C·E 성장 시 60분 배치 초과 | 그림자 스왑이라 서빙 무영향; 파티션 병렬 Leiden 예약 |
| 피드백 자기강화 | 인기 화제 고착, 신생 화제 매장 | 위치편향 역가중 + novelty 항 + ε-탐험(3중, §M10) |
| 사전 드리프트 | 자동 사전 변이가 오염 누적 | 제안 큐 + admin 승인 + scoring_weights처럼 버전·롤백 |
| 한국어 복합명사 | '전기차보조금' 붙여쓰기 변형 | NPMI 병합 + C-value, P3에서 임베딩 유사로 보강 |
| Redis 소실 | 캐시·매핑 증발 | 정본은 전부 SQL(불변식), Redis는 재계산 가능 파생물만 |
| 콜드스타트(참여 로그 0) | engagement 항 무의미 | w₉=0에서 시작, 로그 임계(1만 노출) 도달 후 학습 개시 |

---

## 부록 A. v0 → 설계 모듈 매핑 (현행 코드 기준)

| 설계 모듈 | 현행 v0 위치 | P1에서 달라지는 것 |
|---|---|---|
| M1 | `ai/news/fetcher.py` + `news_service.get_news_sources` | +조건부 GET, +AIMD, +SimHash |
| M2 | `fetcher.fetch_rss` 파싱부 + `topics.clean_text` | 문장분리 강화(인용 보호) |
| M3 | `topics.extract_keywords/classify_*` | +tags2 사전 영속화, +YAKE/NPMI, +유형 9종 |
| M4 | (암묵: 기사 내 공기만) | 명시적 tag_edges + 감쇠 |
| M5 | `topics.build_topics`(키워드 겹침 병합) | P1 유지 → P2 Leiden |
| M6 | score = recency×engagement×diversity | 9항 가중합으로 확장 |
| M7 | (없음 — recency 반감기가 유일한 시간 신호) | EWMA+베이지안 신설 |
| M8~M10 | (없음) | 신설 |

## 부록 B. 준수 확인 — 절대 조건

- 전 모듈에 외부 AI API 호출 없음. "판단"은 전부 식·규칙·그래프 연산.
- 로컬 모델(P3의 ONNX 임베딩/NER)은 프로세스 내 추론이며 네트워크 미사용.
- 기존 LLM 경로(`NEWS_AI_ANALYSIS_ENABLED`)는 본 엔진과 무관한 opt-in 레거시로
  격리 유지 — 본 설계의 어떤 모듈도 그 경로에 의존하지 않는다.
