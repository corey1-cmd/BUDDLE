# buddle 프론트엔드–백엔드 블루프린트 (완벽한 기획 v1)

작성: 2026-06-12 · 근거: 사업계획서 기술통합본 v3.1, 투자제안서(2026.06), 현행 코드(마이그레이션 0001–0018, API v1 16개 라우터, web/ 10페이지)

> **"완벽한 기획"의 정의** — 이 문서에서 완벽함은 화려함이 아니라 **추적 가능성**이다:
> 모든 버튼이 ① 사업계획서의 어떤 약속을 ② 어떤 API로 ③ 어떤 테이블에 닿아 이행하는지
> 한 줄로 추적되고, 빈 화면·오류·데모(백엔드 부재) 상태가 전부 정의되어 있으며,
> 사용자 관점(마찰 제거)과 개발자 관점(상태·계약·보안)이 같은 표에서 만난다.

---

## 0. 제품이 하려는 것 — 기획의 헌법

사업계획서가 정의한 **4가지 마찰**(버들이 없애려는 것)과 **5가지 핵심 기능**이 모든 UI 결정의 심판이다.

| # | 마찰 (사용자 관점) | 대응 기능 | 화면 귀속 |
|---|---|---|---|
| F1 | "글 쓰기가 부담스럽다" — 잘 써야 한다는 압박 | 페르소나와 대화로 글 다듬기 | chat → compose |
| F2 | "올려도 닿지 않는다" — 팔로워 없으면 무의미 | 매개자 80/10/10 분배 | compose → (서버) → inbox/feed |
| F3 | "댓글·DM은 애매하다" — 직접 접촉의 부담 | 주장·인물 AI 대화 + 매개 전달 | feed → argument-chat(계획) |
| F4 | "토론이 어디로 흐르는지 모른다" | 토론 대시보드(Toulmin) | feed → debate-dashboard(계획) |

운영 철학(전 화면 공통 규약): **단정 아닌 추정**(프로파일·매칭 수치는 항상 '추정' 라벨), **연결 전용 프로파일링·배제 금지**, **주권 4권리 상시 노출**(열람·수정·삭제·거부), **백혈구 게이트 통과 콘텐츠만 표시**, **다국어 우선**(원문+번역 병기 자리).

---

## 1. 정보 구조(IA) — 페이지 맵

```
                         ┌─────────────┐
                         │ login.html  │ 가입/로그인 (auth)
                         └──────┬──────┘
                 첫 로그인 ▼ (계획: onboarding 3장 — 주권 고지·페르소나 소개·언어)
                         ┌──────┴──────────┐
   ┌───────────────────▶ │ home-dashboard  │ ◀──────────────────┐
   │                     └─┬───┬───┬───┬───┘                    │
   │      프로파일 아이콘 ──┘   │   │   │                        │
   │   ┌──────────────┐       │   │   └─────────┐               │
   │   │ profile.html │ ✅신규 │   │             │               │
   │   └──────────────┘       ▼   ▼             ▼               │
   │            ┌──────────────┐ ┌───────────┐ ┌────────────┐   │
   │            │persona-select│ │ feed.html │ │ inbox.html │   │
   │            └──────┬───────┘ └─────┬─────┘ └────────────┘   │
   │     ┌─────────────┤              │ 글카드 탭                │
   │     ▼             ▼              ├──────────► [debate-dashboard] 계획(0020)
   │ ┌──────────────┐ ┌───────────┐   └──────────► [argument-chat]    계획(0021)
   │ │persona-create│ │ chat.html │──"이 대화로 글쓰기"──► compose.html ─┐
   │ └──────────────┘ └───────────┘                                    │
   │                       ▲                                           │
   └── nearby.html (위치)  └────────────── 게시 완료 ◀─────────────────┘
```

원칙: **모든 화면은 3탭 이내 도달**(하단 nav 5 + 홈 헤더 아이콘), **뒤로가기는 항상 좌상단**, **하단 nav는 전 화면 동일 순서**(홈·관심주제·대화NOW·내 활동·글쓰기 — profile은 헤더 진입 + profile 화면에서만 6번째로 활성 표시).

---

## 2. 사용자 여정 3종 (마찰 제거의 동선 증명)

**여정 A — 외로운 1인가구 청년 "지수" (F1+F2)**
login → (onboarding: "버들은 당신을 추정하되 단정하지 않습니다" 주권 고지) → persona-create(이름 "초록", 모델 friend 기본, 관심태그 3개, 위치공유 OFF 기본) → chat("오늘 강가를 걸었는데 참 좋더라…") → 페르소나가 기억(0017)을 쌓고 EKB 인지로 응답 → [이 대화로 글쓰기] → compose(대화 발췌 자동 인입, 매개자 변환 미리보기: 원문은 절대 그대로 노출되지 않음 안내) → [게시] → 매개자 분배 → 상대 페르소나 inbox에 도착 → 지수의 inbox에 "회신 도착" → 연결.
*검증 포인트: 지수는 한 번도 '공개 글쓰기 압박'을 받지 않았고(F1), 팔로워 0명으로 닿았다(F2).*

**여정 B — 유학생 "Minh" (언어 장벽)**
feed에서 베트남어 UI(계획: 언어 토글) → 글 카드에 원문+자동 번역 병기 → chat은 모국어로, 매개자가 한국어 사용자의 페르소나에 변환 전달.

**여정 C — 토론 참여자 "현우" (F3+F4)**
feed → 화제 칩 "도시 재개발" 탭 → debate-dashboard(계획): 축 2~5개·입장 분포·근거 수·흐름 → 특정 주장 카드 [이 주장과 대화] → argument-chat(계획): "AI 재현, 본인 아님" 라벨 상시 → 대화 산출이 post_context_notes로 원글에 적재(F3의 '애매한 간극'이 안전한 대화로 대체).

---

## 3. 페이지별 명세 (현행 10 — 버튼·기본값·배선·테이블)

각 행: **버튼/요소 → 기본값·선택 조건 → API → 테이블 → 성공/실패·빈 상태**.

### 3-1. login.html
| 요소 | 기본값/조건 | API | 테이블 | 상태 |
|---|---|---|---|---|
| 이메일/비번 입력 | 자동완성 off, 비번 8자+ | — | — | 인라인 검증 |
| [로그인] | 양 필드 채워야 활성 | POST /v1/auth/login | users | 성공: 토큰→sessionStorage(buddle.auth.v1)→home. 401: "이메일 또는 비밀번호가 맞지 않아요" |
| [회원가입] | — | POST /v1/auth/register | users | 성공: 자동 로그인 → (계획) onboarding |
| 데모 배지 | 백엔드 부재 시 | — | — | 데모 모드로 전 화면 진입 허용(파일 단독 열람 보장) |

### 3-2. home-dashboard.html — "내 페르소나 시장" 메타포
| 요소 | 기본값/조건 | API | 테이블 | 상태 |
|---|---|---|---|---|
| 페르소나 카드 리스트 | 활동점수 내림차순 | GET /v1/personas | personas, distributions(점수 집계) | 빈: "첫 페르소나를 만들어보세요" → persona-create |
| 주목 주제 칩 | 지역별 상위 2 | GET /v1/tags/trending(계획) · 현재 데모 | tags, posts | 칩 탭 → feed?tag= |
| AI 데일리 브리핑 | 광장 가상 페르소나 요약 | GET /v1/plaza/briefing(계획) · 현재 데모 | knowledge_units | — |
| 프로파일 아이콘 ✅신규 | 헤더 우측 | → profile.html | user_profiles | — |
| 하단 nav 5 | 전 화면 공통 | — | — | — |

### 3-3. persona-create.html
| 요소 | 기본값/조건 | API | 테이블 | 상태 |
|---|---|---|---|---|
| 이름 | 필수 1–64자 | POST /v1/personas | personas | 중복 허용(사용자 내 구분만) |
| 모델 선택 | **기본 friend** (등록된 ACTIVE만 노출) | GET /v1/persona-models | persona_models | Z.ai 시드 시 backend=vllm_endpoint 자동 |
| 관심 태그 | 0–20개, 기본 0 | GET /v1/tags | tags, persona_tags | 태그는 매칭 콘텐츠 신호의 일부 |
| 위치 공유 토글 | **기본 OFF** (opt-in) | 같은 POST body | personas(lat/lon/sharing) | ON일 때만 lat/lon 입력 노출 + nearby 활성 |
| [만들기] | 이름+모델 시 활성 | POST /v1/personas | personas | 성공 → persona-select |

### 3-4. persona-select.html (대화NOW)
| 요소 | 기본값/조건 | API | 테이블 | 상태 |
|---|---|---|---|---|
| 페르소나 카드 | 최근 대화순 | GET /v1/personas | personas, conversation_sessions | 탭 → chat?persona= |
| 세션 이어가기 | 마지막 세션 자동 | GET /v1/sessions?persona= | conversation_sessions | "이어서" vs "새 대화" 선택 |

### 3-5. chat.html — 페르소나 대화 (LTM 0017 탑재)
| 요소 | 기본값/조건 | API | 테이블 | 상태 |
|---|---|---|---|---|
| WS 연결 | 토큰 필수 | WS /v1/ws/dialogue | messages, conversation_sessions | 끊김: 지수 백오프 재연결 + 배너 |
| 메시지 전송 | 1–2000자 | (WS frame) | messages → **persona_memories**(관찰) · **user_profiles**(특질 관찰) ✅ | 백혈구 차단 시 안내문 표시 |
| 페르소나 응답 | — | (WS frame) | persona_memories(회상→EKB Search) | 응답 메타에 회상 여부(개발 모드) |
| [이 대화로 글쓰기] | 메시지 1개+ 시 활성 | → compose.html?session= | — | 발췌 자동 인입 |
| 기억 표시 규약 | 회상은 자연스럽게만, 나열 금지(프롬프트 강제) | — | — | UI에 기억 목록을 직접 노출하지 않음(과시 금지 원칙의 UI 버전) — 열람은 (계획) 기억 관리 화면에서 |

### 3-6. compose.html — 글 다듬기·게시
| 요소 | 기본값/조건 | API | 테이블 | 상태 |
|---|---|---|---|---|
| 본문 | 세션 발췌 프리필 가능 | — | — | — |
| 공개 범위 | **기본 private(매개 분배)** / public(광장) | POST /v1/posts | posts | private이 기본 = "팔로워 광장이 아니라 매개 연결"이라는 제품 정체성의 기본값 |
| [게시] | 본문 1자+ | POST /v1/posts | posts → importance_scores, post_tags, distributions, **user_profiles.interests_emb** ✅ | 백혈구 suppress: "다듬어 다시 보내볼까요" 톤 안내. 성공: 분배 수 표시 |
| 변환 미리보기 | 매개자 변환 후 모습 | (응답 content_transformed) | posts | "원문은 그대로 노출되지 않습니다" 캡션 |

### 3-7. feed.html (관심주제)
| 요소 | 기본값/조건 | API | 테이블 | 상태 |
|---|---|---|---|---|
| 피드 리스트 | 커서 페이지네이션 | GET /v1/feed?cursor= | posts, tags | 빈: "관심 태그를 골라보세요" |
| 화제 칩 | 상위 태그 | GET /v1/tags | tags | 탭 → 필터. (0020 후) → debate-dashboard |
| 글 카드 | suppress 제외만 | — | posts | (0021 후) [주장과 대화] 버튼 자리 예약 |

### 3-8. inbox.html (내 활동)
| 요소 | 기본값/조건 | API | 테이블 | 상태 |
|---|---|---|---|---|
| 도착 글 | 내 페르소나가 받은 분배 | GET /v1/inbox | distributions, posts | 빈: "곧 결이 맞는 글이 도착해요" |
| 회신/반응 | — | POST /v1/inbox/{id}/… | comments, messages | — |

### 3-9. nearby.html
| 요소 | 기본값/조건 | API | 테이블 | 상태 |
|---|---|---|---|---|
| 주변 페르소나 | 위치공유 ON인 내 페르소나 필요 | GET /v1/proximity | personas(위치) | OFF: 설명 + persona-create로 유도. 링 점수만 표시(정확 좌표 비노출) |

### 3-10. profile.html ✅ 이번 구현 — 주권 4권리의 화면
| 요소 | 기본값/조건 | API | 테이블 | 상태 |
|---|---|---|---|---|
| OCEAN 막대 5 | 중립 0.5 시작, '추정값' 배지 | GET /v1/me/profile | user_profiles | 행 없음 → 중립값 200(열람권은 무조건) |
| [수정하기→저장] | 슬라이더 0–1, step .05 | PATCH /v1/me/profile | user_profiles(is_user_edited=t, confidence=1) | 저장 후 배지 '내가 설정함' + "자동 추정 멈춤" 안내 |
| 신뢰도 미터 | 1−e^(−n/30), 100% 도달 불가 | (GET 응답) | user_profiles | n=0이면 설계 설명 문구 |
| 관심 분야 | has_interests만 (임베딩 원값 비노출) | (GET 응답) | user_profiles.interests_emb | "방향만 저장, 매칭 10%로만" 고지 |
| 거부 토글 | **기본 OFF** | PATCH {profile_opt_out} | user_profiles | ON: "콘텐츠·위치만으로 재계산" — 0019 매칭이 이 플래그로 재정규화 |
| [프로파일 삭제] | confirm 필수 | DELETE /v1/me/profile | user_profiles(행 삭제) | 204 → 중립 리셋. 멱등 |
| 데모 폴백 | 토큰 없음/백엔드 부재 | — | — | '데모 모드' 배지 + 탭 내 반영만 |

---

## 4. 계획 페이지 4종 (백엔드 단계와 잠금)

| 페이지 | 해금 조건 | 핵심 요소 | API(신설) | 테이블(신설) |
|---|---|---|---|---|
| onboarding(3장) | 즉시 가능 | 주권 고지·페르소나 개념·언어 선택 (각 장 [다음], 마지막 [시작하기]) | — | users.preferred_language |
| debate-dashboard | **0020** | 축(군집) 카드 ≤5 · 입장 도넛(pro/con/neutral) · 근거 수 · 7일 흐름 스파크라인 · [이 주장과 대화] | GET /v1/topics/{tag}/debate | argument_units |
| argument-chat | **0021** | 상단 고정 라벨 "공개 글로 구성한 AI 재현 — 본인 아님" · WS 대화 · [원글에 맥락 저장] | WS /v1/ws/argument/{post} | post_context_notes + personas.argument_ai_opt_out |
| memory-manage(기억 열람) | 0017 후속 | 페르소나별 기억 목록·개별 삭제 (주권을 기억에도) | GET/DELETE /v1/personas/{id}/memories | persona_memories(기존) |

---

## 5. 테이블 ↔ 페이지 매트릭스 (읽기 R / 쓰기 W)

| 테이블 | login | home | p-create | p-select | chat | compose | feed | inbox | nearby | profile | 계획(4·5단계) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| users | W | R | — | — | — | — | — | — | — | — | — |
| personas | — | R | W | R | R | — | — | — | R | — | R |
| persona_models | — | — | R | — | R | — | — | — | — | — | — |
| conversation_sessions | — | — | — | R | W | R | — | — | — | — | — |
| messages | — | — | — | — | W | — | — | — | — | — | — |
| **persona_memories** ✅0017 | — | — | — | — | **W(관찰)·R(회상)** | — | — | — | — | — | R(열람 화면) |
| **user_profiles** ✅0018 | — | — | — | — | **W(특질)** | **W(관심)** | — | — | — | **R/W/D** | R(0019 매칭) |
| posts | — | — | — | — | — | W | R | R | — | — | R |
| tags / post_tags | — | R | R | — | — | W | R | — | — | — | R |
| distributions | — | R | — | — | — | W(서버) | — | R | — | — | — |
| mediator_policies | — | — | — | — | — | R(서버) | — | — | — | — | R/W(0019 가중치) |
| argument_units (0020) | — | — | — | — | — | W(서버) | — | — | — | — | R |
| post_context_notes (0021) | — | — | — | — | — | — | — | — | — | — | W |

*규약: 프론트는 절대 테이블을 직접 알지 못한다 — 전부 API 경유. 위 매트릭스는 영향 추적용.*

---

## 6. 개발자 규약 (전 화면 공통 계약)

1. **인증** — sessionStorage `buddle.auth.v1` = `{a, r}`. Authorization: Bearer. 401 → 토큰 폐기 후 login으로. (탭 종료=세션 종료는 의도된 보안 선택 — SECURITY_FRONTEND.md)
2. **데모 폴백** — `토큰 없음 ∨ fetch 실패 → 데모 모드 배지 + 결정적 더미`. 파일 단독으로 열어도 모든 화면이 시연 가능해야 한다(투자 데모 요건).
3. **XSS 불변식** — API 텍스트는 `textContent`/DOM API로만. innerHTML에 사용자 유래 문자열 금지(security.js 규약).
4. **상태 4종 의무** — 모든 데이터 영역은 로딩/성공/빈/오류 4상태를 정의한다. 빈 상태는 항상 "다음 행동" 버튼을 동반(빈 inbox → 글쓰기 유도).
5. **추정 라벨 불변식** — user_profiles 유래 수치는 '추정' 또는 '내가 설정함' 배지 없이 표시 금지.
6. **기본값 철학** — 위치 공유 OFF, 게시 범위 private, 프로파일 관찰 ON(거부 토글 상시 노출), 모델 friend. *기본값이 곧 제품의 가치 선언이다.*
7. **API 베이스** — `window.BUDDLE_API_BASE` 오버라이드(개발: localhost, 운영: 동일 출처). 신규 화면은 api.js 사본 동기화 대신 필요한 최소 부분집합만 인라인(profile.html 방식) — 사본 드리프트 리스크 축소.

---

## 7. 구현 로드맵 매핑 (이 문서의 잠금 해제 순서)

| 단계 | 백엔드 | 프론트 |
|---|---|---|
| ✅ 0017 | 페르소나 LTM | chat에 자동 반영(회상·관찰), 기억 관리 화면은 후속 |
| ✅ 0018 | OCEAN 프로파일 + 주권 API | **profile.html + 홈 진입점 (완료)** |
| 0019 | 80/10/10 + MMR | profile의 거부 토글이 실제 재정규화로 작동 · compose 분배 결과에 "왜 닿았나"(콘텐츠/프로파일/위치 기여 막대) |
| 0020 | Toulmin argument_units + 집계 API | debate-dashboard 신설, feed 칩 연결 |
| 0021 | 주장·인물 AI WS + 노트 | argument-chat 신설, feed 카드 버튼 활성 |
| 운영 전환 | Z.ai → 자체 vLLM (시드 교체) | 변경 없음(프론트는 모델 위치를 모른다 — 올바른 추상화의 증명) |
