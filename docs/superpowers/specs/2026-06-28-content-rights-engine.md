# BUDDLE 콘텐츠 권리/라이선스 엔진 — 설계 + 매체 권한 DB

- 작성일: 2026-06-28
- 상태: 설계 + 전수조사 진행 중
- 상위 스펙: [2026-06-28-buddle-android-beta-design.md](2026-06-28-buddle-android-beta-design.md)

> ⚠️ **법적 고지:** 본 문서는 엔지니어링 설계이며 **법률 자문이 아니다.** 목적은 저작권·부정사용
> 리스크를 *구조적으로 줄이는* 것이지 면책이 아니다. 본문/요약을 다루는 공개·상업 서비스 출시
> 전에 **반드시 변호사 검토**를 받는다. 각 매체 정책은 수시로 바뀌므로 `last_checked`와 증거 URL을
> 항상 기록하고 주기적으로 재검증한다.

---

## 1. 설계 원칙

1. **Default-deny (보수적 기본값):** 미조사 매체·미확인 필드는 **무조건 최저 권한**
   = `title + url + metadata`만 허용, 나머지(본문·요약·인용·임베딩·재배포·상업·학습) 전부 금지.
   → 전수조사 미완 상태에서도, 매체가 정책을 바꿔도 안전. "한 곳도 빠뜨리면 리스크"를 구조로 차단.
2. **상업 기준(commercial-first):** BUDDLE은 유료 티어가 있는 상업 제품. 따라서 권한 판정의
   기준 맥락은 **상업 이용**이다. 비상업(CC-NC) 전용 콘텐츠는 본문·요약·재배포 **불가** →
   제목+링크+메타데이터로 강등.
3. **권한 수준(per-field)으로 관리, 매체로 관리하지 않음:** A/B/C 등급이 아니라 매체마다
   **권한 플래그 집합(permission profile)** 을 부여. 정책이 바뀌면 그 매체의 프로필만 조정.
4. **출처 표시 의무화:** 모든 노출에 매체명 + 원문 링크(canonical) 표기.
5. **robots.txt / AI-크롤러 정책 존중:** AI 봇(GPTBot, CCBot, Google-Extended, anthropic-ai,
   ClaudeBot 등) 차단 매체는 자동 수집·임베딩 대상에서 제외(공식 RSS/API만 사용).
6. **증거 보존:** 각 매체 행에 판정 근거 URL(robots.txt, ToU, copyright, AI policy)과
   `last_checked`, `confidence` 기록.

---

## 2. 권한 플래그 (per-source, 상업 맥락)

각 매체는 다음 불리언 플래그 집합을 가진다. **기본값 = 아래 표의 "기본"열(default-deny).**

| 플래그 | 의미 | 기본 |
|---|---|---|
| `title` | 제목 표시 | ✅ |
| `url` | 원문 링크 | ✅ |
| `metadata` | 발행일·저자·매체명·섹션·이미지 썸네일(허용 시) | ✅ |
| `our_descriptor` | **우리가 직접 쓴** 중립적 한 줄 설명(원문 복제 아님) | ✅ |
| `abstract` | **AI/직접 작성** 짧은 요약(3줄) 표시 | ❌ |
| `quotation` | 짧은 직접 인용(페어유즈 범위) | ❌ |
| `full_text` | 본문 저장/표시 | ❌ |
| `embedding` | 본문 임베딩(검색/군집 DB) | ❌ |
| `redistribution` | 2차 제작물로 재배포 | ❌ |
| `commercial` | 상업적 이용 | ❌ |
| `ai_training` | 모델 학습(파인튜닝) 사용 | ❌ |

> `title/url/metadata/our_descriptor`는 사실·링크·자작 설명이라 기본 허용. 단 매체 robots/ToU가
> 제목·메타까지 제한하면 그 매체만 더 낮춤.

### 2.1 AI 사용 단계 (`ai_use_level`, 최대 허용치)
`none`(금지) → `inference_only`(일시 추론, 저장X) → `store_summary`(요약 저장) →
`embedding`(임베딩 저장) → `finetune`(학습). 기본 = `none`(제목/메타만 다루므로).

### 2.2 보존 정책 (`retention`)
- `title/url/metadata`: 영구 저장 가능(사실·링크).
- `full_text`: 기본 **저장 0**. 허용 매체라도 본문 캐시는 **최대 24h**(처리용)·이후 파기.
- `abstract/embedding`: 해당 플래그가 켜진 매체만, 라이선스 범위 내 저장.

---

## 3. DB 구조

```sql
-- 매체(소스) 권한 프로필
content_source(
  id, name, homepage, country, kind,            -- kind: news|magazine|blog|security|tech|gaming
  rss_url, has_public_api, syndication_api_url,
  robots_general,                                -- allow|partial|disallow|unknown
  robots_ai,                                     -- allowed|blocked|partial|unspecified (+ blocked_bots[])
  license_type,                                  -- proprietary|cc-by|cc-by-nc|cc-by-nc-nd|public-domain|mixed|unknown
  -- 권한 플래그 (상업 맥락)
  allow_title, allow_url, allow_metadata, allow_our_descriptor,
  allow_abstract, allow_quotation, allow_full_text,
  allow_embedding, allow_redistribution, allow_commercial, allow_ai_training,
  ai_use_level,                                  -- none|inference_only|store_summary|embedding|finetune
  body_cache_hours,                             -- 0 기본
  evidence_urls jsonb,                          -- {robots, tou, copyright, ai_policy, rss}
  last_checked date, confidence,                -- high|med|low
  notes
)

-- 기사: 소스 프로필을 상속, 기사별 예외만 override
content_item(
  id, source_id -> content_source,
  title, url, published_at, author, section, lang,
  our_descriptor,                               -- 자작 한 줄
  abstract,                                     -- 허용 소스만 채움(아니면 null)
  body_cache, body_cache_expires_at,            -- 허용+24h 한정, 만료 시 파기
  effective_perms jsonb,                        -- 소스 상속 + override 결과(런타임 강제용)
  ...
)
```

**권한 강제(runtime):** 모든 노출/저장 코드는 `content_source` 프로필을 단일 진실원으로 참조.
미등록 소스의 기사는 **거부**(default-deny). 정책 변경 시 `content_source` 한 행만 수정하면
전 기사에 즉시 반영.

### 3.1 자동 판정 로직(개요)
1. robots.txt 파싱 → `robots_general`, `robots_ai`(차단 봇 목록).
2. AI 차단 매체 → 자동 수집·임베딩 제외, 공식 RSS/API만.
3. license_type 판정(CC 표기 탐지 / 명시적 재배포 허가 / 그 외 proprietary).
4. 상업 맥락 적용: CC-NC·proprietary → `abstract/full_text/embedding/redistribution/commercial=❌`.
5. 명시적 상업 재배포 허가(또는 CC-BY 등 상업 허용) 매체만 상향.
6. 미확인·접근불가 → default-deny + `confidence=low` + 수동/법무 확인 플래그.

---

## 4. 사용자 노출 형태 (뉴스 피드 = 권한 인지 렌더)

- **항상:** 제목 + 원문 링크 + 매체명·발행일(metadata) + 우리가 쓴 중립적 한 줄(`our_descriptor`).
- **허용 매체만:** 3줄 요약(`abstract`).
- 본문·전문은 표시하지 않음(허용 매체 한정·라이선스 범위 내에서만).
- 그 다음 단계의 "이해"는 **원문 요약이 아니라 우리 플랫폼의 토론 흐름 설명**(기능 7, 우리 자산).

---

## 5. 전수조사 매체 DB (50개)

> 상태 범례: `미조사` = 기본 최저권한(제목+링크+메타) 적용 중. 조사 완료 시 플래그·증거·날짜 갱신.
> **현 시점 모든 매체는 보수적 기본값으로 시작**하며, 아래에 조사 결과를 누적한다.

| # | 매체 | RSS | robots(일반/AI) | license | 상업 재배포 | 적용 권한(요약) | last_checked | conf | 근거 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Bloomberg | 미조사 | 미조사 | proprietary(추정) | ❌(기본) | title+url+meta | — | low | — |
| 2 | Wall Street Journal | 미조사 | 미조사 | proprietary(추정) | ❌ | title+url+meta | — | low | — |
| 3 | Wired | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 4 | New York Times | 미조사 | 미조사 | proprietary(추정) | ❌ | title+url+meta | — | low | — |
| 5 | Reuters | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 6 | Financial Times | 미조사 | 미조사 | proprietary(추정) | ❌ | title+url+meta | — | low | — |
| 7 | The Verge | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 8 | TechCrunch | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 9 | CNBC | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 10 | The Information | 미조사 | 미조사 | proprietary(추정) | ❌ | title+url+meta | — | low | — |
| 11 | Axios | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 12 | 404 Media | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 13 | Washington Post | 미조사 | 미조사 | proprietary(추정) | ❌ | title+url+meta | — | low | — |
| 14 | The Guardian | 미조사 | 미조사 | 미조사(공식 Open Platform API 존재 추정) | ❌ | title+url+meta | — | low | — |
| 15 | Ars Technica | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 16 | Politico | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 17 | Forbes | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 18 | BleepingComputer | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 19 | BBC | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 20 | Simon Willison's Weblog | 미조사 | 미조사 | CC 추정(개인블로그) | ❌ | title+url+meta | — | low | — |
| 21 | Business Insider | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 22 | Krebs on Security | 미조사 | 미조사 | CC-BY 추정 | ❌ | title+url+meta | — | low | — |
| 23 | The Atlantic | 미조사 | 미조사 | proprietary(추정) | ❌ | title+url+meta | — | low | — |
| 24 | Tom's Hardware | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 25 | 9to5Google | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 26 | IGN | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 27 | 9to5Mac | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 28 | On my Om (Om Malik) | 미조사 | 미조사 | CC 추정(개인블로그) | ❌ | title+url+meta | — | low | — |
| 29 | ProPublica | 미조사 | 미조사 | CC-BY-NC-ND 추정 | ❌(NC라 상업 불가) | title+url+meta | — | low | — |
| 30 | Reclaim The Net | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 31 | Windows Central | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 32 | Android Police | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 33 | NBC News | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 34 | Variety | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 35 | Harvard Business Review | 미조사 | 미조사 | proprietary(추정) | ❌ | title+url+meta | — | low | — |
| 36 | The Decoder | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 37 | MacRumors | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 38 | Nikkei Asia | 미조사 | 미조사 | proprietary(추정) | ❌ | title+url+meta | — | low | — |
| 39 | GameSpot | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 40 | The Register | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 41 | Fortune | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 42 | VentureBeat | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 43 | The San Francisco Standard | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 44 | Platformer | 미조사 | 미조사 | 미조사(Ghost 뉴스레터) | ❌ | title+url+meta | — | low | — |
| 45 | Game File | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 46 | MIT Technology Review | 미조사 | 미조사 | proprietary(추정) | ❌ | title+url+meta | — | low | — |
| 47 | New Yorker | 미조사 | 미조사 | proprietary(추정) | ❌ | title+url+meta | — | low | — |
| 48 | iFixit News | 미조사 | 미조사 | CC 추정 | ❌ | title+url+meta | — | low | — |
| 49 | Ed Zitron's Where's Your Ed At | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |
| 50 | sn scratchpad | 미조사 | 미조사 | 미조사 | ❌ | title+url+meta | — | low | — |

> "추정"은 미검증 가정이며 조사 전까지 효력 없음(전부 default-deny 적용). 조사 시 사실로 대체.

---

## 6. 전수조사 방법론 (배치)

각 매체에 대해 순서대로 확인하고 위 표를 갱신:
1. `/{도메인}/robots.txt` — 일반 크롤 규칙 + AI 봇(GPTBot/CCBot/Google-Extended/anthropic-ai/ClaudeBot/Bytespider) Disallow 여부.
2. RSS 피드 URL 존재 확인(공식). 있으면 제목·링크·메타 합법 수집 경로 확보.
3. Terms of Use / Copyright / AI policy 페이지 — 재배포·인용·상업·AI 사용 명시 조항.
4. Syndication/Licensing API(예: Guardian Open Platform, NYT API) 유무.
5. license_type 판정 + 상업 맥락 적용 + 증거 URL·last_checked·confidence 기록.
6. 접근 불가/불명확 → default-deny 유지 + 수동·법무 확인 플래그.

진행은 배치(약 6~10개씩)로 누적한다.

---

## 7. 조사 로그 & 핵심 결론 (2026-06-28)

### 7.1 자동 조사의 한계 (중요)
- 대형 매체 다수가 자동 접근(WebFetch)을 **차단**: WSJ·NYT·Reuters·FT·Wired·The Guardian·
  Ars Technica·Krebs(캡차) 등 robots.txt조차 자동으로 못 읽음 → **조사불가 → default-deny 유지
  + 수동·법무 확인 플래그**. (차단 자체가 폐쇄적 정책 신호이기도 하다.)
- 따라서 **50곳 전부를 자동 도구로 정확히 법적 분류하는 것은 불가능**하며, 부정확한 분류는
  오히려 법적 리스크다. → **default-deny가 유일하게 안전한 기본**이고, 상향은 신뢰 증거가 있을 때만.

### 7.2 상업 제약이 결과를 결정한다 (핵심)
BUDDLE은 상업 제품이므로 **비상업(CC-NC) 라이선스 콘텐츠는 본문·요약·재배포 불가**.
"콘텐츠 활용에 관대한 곳"의 상당수가 실제로는 NC다(예: ProPublica = CC-BY-NC-ND,
iFixit = CC-BY-NC-SA). 결론:

> **무료 기준으로는 50개 매체 거의 전부가 "제목 + 링크 + 메타데이터(+ 우리가 쓴 한 줄)"만
> 가능하다.** 본문·요약·임베딩·재배포로 올리려면 **유료 신디케이션 / 공식 라이선싱 API(B2B 계약)**
> 가 필요하다. (사업계획서/요구사항 step 3의 "B2B 계약" 방향과 일치.)

### 7.3 1차 배치 결과
| 매체 | robots/AI | RSS·API | 라이선스 | 상업 적용 권한 | last_checked |
|---|---|---|---|---|---|
| Bloomberg | 일반 크롤·AI봇 대부분 차단(GPTBot/CCBot/Google-Extended/ClaudeBot/cohere/Diffbot/ByteSpider) | 사이트맵만, RSS 미확인 | proprietary | **title+url+meta** (자동수집·임베딩 금지) | 2026-06-28 |
| ProPublica | robots 개방, AI봇 차단 없음 | sitemap | **CC-BY-NC-ND** | **title+url+meta** (NC→상업 재배포 불가) | 2026-06-28 |
| iFixit | Google-Extended 차단 | sitemap | **CC-BY-NC-SA** | **title+url+meta** (NC→상업 불가) | 2026-06-28 |
| Simon Willison | robots 개방(ChatGPT-User만 명시) | sitemap | 미확인 | **title+url+meta** (증거 없어 default) | 2026-06-28 |
| WSJ·NYT·Reuters·FT·Wired·Guardian·Ars·Krebs | **자동 조사 불가(차단/캡차)** | — | 미확인 | **title+url+meta** + 수동·법무 확인 | 2026-06-28 |
| (나머지 #11~50 미조사) | — | — | — | **title+url+meta** (default-deny) | — |

### 7.4 권고 (실행 경로)
1. **베타·무료 단계:** 전 매체 **title+url+metadata + 우리가 쓴 한 줄** 만. 본문·요약·재배포 없음.
   "이해"는 원문 요약이 아니라 **우리 플랫폼의 토론 흐름 설명**(우리 자산)으로 제공.
2. **수집 경로:** 각 매체 **공식 RSS / 공식 API**(예: Guardian Open Platform, NYT API)만 사용.
   robots에서 막힌 곳은 스크래핑하지 않음(약관·CFAA 등 리스크).
3. **상향이 필요하면:** 해당 매체와 **유료 신디케이션/라이선스(B2B)** 체결 후, 계약 범위를
   `content_source` 프로필에 반영(등급 상향). 계약서가 단일 진실원.
4. **출시 전 법률 검토** 필수(특히 인용·메타데이터 범위, 썸네일 이미지, 핫뉴스 독트린 등).
5. 미확인·차단 매체는 **영구 default-deny** 유지(증거 없이는 절대 상향 금지).

---

## 8. 상업성 판단 & 비즈니스 모델 (중요한 구분)

> ⚠️ 법률 자문 아님. 보수적(리스크 회피) 해석 기준.

**질문:** "화제 제시·토론을 가능하게 하는 게 상업인가? 수익은 지자체·기업에게 *화제 광역 노출*로
받는데, 그럼 비상업 전용(NC) 콘텐츠도 쓸 수 있지 않나?"

### 8.1 저작권/NC가 막는 것 vs 안 막는 것
저작권은 **표현(expression)** 을 보호하지, **사실·아이디어**는 보호하지 않는다.

| 저작권/NC가 **막는** 것 (영리 플랫폼은 위험) | **안 막는** 것 (자유롭게 사업화 가능) |
|---|---|
| 출판사 **본문** 저장·표시 | **화제·주제·아이디어**(사실) |
| 창작적 **요약**(본문 파생) | **매우 짧은 헤드라인**(대개 보호 약함*) + **링크** |
| 사진·도표 등 자산 | 발행일·매체명 등 **메타데이터(사실)** |
| 본문 **임베딩**·재배포 | **우리가 직접 쓴** 설명·분석 |
| | **우리 플랫폼의 토론**(사용자 글·댓글·주장) = 우리 자산 |

(* 헤드라인은 일부 관할/판례에서 보호될 수 있음 — Meltwater(영국), 미국 "hot news" 독트린. 그래서
제목은 최소화하고 **링크 + 우리가 쓴 한 줄**을 핵심으로.)

### 8.2 "비상업(NC)" 판단은 콘텐츠 단위가 아니라 **사업 맥락**으로 본다
Creative Commons의 NonCommercial은 "주로 상업적 이득·금전 보상을 향한 것이 아닐 것"이다.
**영리 회사·유료 플랫폼 안에서의 이용은, 그 콘텐츠가 직접 과금 대상이 아니어도, 상업으로 보는
것이 안전한 해석**이다. 더구나 **지자체·기업에게 화제 광역 노출로 과금**하는 모델은 상업성을
오히려 **강화**한다(직접적 금전 보상 + 노출 거래). → NC 본문을 영리 플랫폼에서 쓰는 것은 위험.

### 8.3 결정적 포인트: 당신의 수익모델은 출판사 본문이 **필요 없다**
"화제 광역 노출(B2B 스포트라이트) + 토론"은 **화제·사실·링크·우리 토론**만으로 굴러간다 —
이건 위 표의 **'안 막는' 열**이다. 즉:

> **default-deny 모델(제목+링크+메타+우리 한 줄 + 우리 토론)이 당신의 B2B 사업을 막지 않는다.**
> NC가 막는 것(본문·창작적 요약·재배포)은 애초에 이 사업에 불필요하다.

### 8.4 결론 (설계 반영)
- `commercial` 플래그는 **본문·창작요약·인용·임베딩·재배포에만** 적용. 사실·링크·메타·우리 글·
  우리 토론에는 적용되지 않는다(저작권 비대상).
- 보수 모델 유지. NC/유료 매체의 **본문**을 굳이 쓰려면 → 변호사 검토 + **서면 허락/라이선스**.
  자가 판단("이건 비상업이야")에 의존하지 말 것.
- B2B 화제 노출 상품은 비제한 영역(화제·링크·우리 토론)에서 자유롭게 설계·과금 가능.

---

## 9. 데이터 확보 & 요약 정책 (현실 반영 — "설명을 쓰려면 데이터가 필요")

설명·토론 시드를 만들려면 기사에 대한 **입력 데이터**가 있어야 한다. 핵심은 *무엇을 입력으로
쓰고, 무엇을 출력·저장하느냐*다. 위험도 순:

| 경로 | 입력 | 위험 | 채택 |
|---|---|---|---|
| **A. 공식 RSS 스니펫** | 출판사가 **스스로 피드에 넣은** title + description(1~2문장) + link | 낮음(신디케이션 목적 공개) | ✅ 기본 입력 |
| **B. 우리가 쓴 사실 요약** | A를 입력으로, **사실만** 우리 말로 재서술(표현 복제 X) | 낮음(사실은 비저작) | ✅ 출력·표시 |
| **C. 본문 스크래핑 후 AI 요약** | 전체 본문 | 높음(파생물 + 접근약관/CFAA) | ❌ 안 함 |

### 9.1 채택 파이프라인
1. **입력은 공식 RSS/API만.** 출판사가 피드로 공개한 title + description(스니펫) + link + 메타. 본문
   페이지 **스크래핑 금지**(특히 robots 차단·페이월). 막힌 매체는 title+link만.
2. **출력은 "우리가 쓴 사실 프레이밍".** RSS 스니펫·제목을 입력으로 Gemini가 **사실을 우리 말로**
   1줄/최대 3줄로 재서술(원문 표현·구조 복제 금지). 이게 `our_descriptor`/`our_summary`.
3. **표시:** 우리 프레이밍(주) + 원문 링크(필수) + 매체명. 출판사 스니펫 **원문 그대로 표시**는
   매체별 `rss_snippet_display` 플래그가 켜진 곳만(공식 피드 + 약관 허용 시, 출처 병기).
4. **시장 대체 금지(페어유즈 핵심):** 우리 요약이 원문 **읽기를 대체하면 안 됨** → 티저 길이 유지,
   "더 보기=원문 링크". 대체적·전문 재현은 금지.
5. **임베딩 범위:** 군집·검색 임베딩은 **우리 텍스트(우리 요약·제목·우리 토론)** 로 한다. 출판사
   **본문 임베딩은 금지**. (토론 대시보드 군집은 이걸로 충분히 동작.)

### 9.2 플래그 정밀화 (§2 보완)
- `abstract` → 두 개로 구분:
  - `rss_snippet_display` = 출판사 피드 스니펫 **원문 그대로** 표시 (기본 ❌; 공식 피드+약관 허용 시 ✅, 출처 병기)
  - `our_summary` = **우리가 쓴** 사실 요약(1~3줄) (기본 ✅ — 사실 재서술, 표현 복제 금지)
- `embedding` = **출판사 본문** 임베딩 (기본 ❌). 우리 텍스트·제목 임베딩은 제한 없음(저작권 비대상).
- `full_text` = 기본 ❌, 스크래핑 안 함.

> ⚠️ 잔여 리스크: 대량 AI 요약은 의도치 않게 표현을 재현할 수 있다. → 짧게·사실 중심·우리 말·
> 항상 링크·티저 길이. 출시 전 법률 검토로 요약 길이/형식의 안전선 확정.

