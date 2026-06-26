# buddle 남은 페이지 단계별 설계 (제작 순서 3~6)

> 완성: 0 로그인(미정), 1 홈 ✅, 2 페르소나 선택 ✅, 3 대화 ✅, 4 글쓰기 ✅.
> 공통: 코스믹 라테(#fff8e7) 배경 + 반투명 카드(blur), 포레스트/민트 강조, `api.js` 사용.
> api.js 연결 검증 완료 — 모든 경로가 백엔드와 일치.

---

## ① 페르소나 생성 (2a, persona-create)

설정 박스 "페르소나 관리" 또는 페르소나 선택의 [+ 새 페르소나]에서 진입.

```
[1] 이름                ← text (1~64자)
[2] 모델 선택            ← 모델 카드/드롭다운 (model_key)
[3] 관심사 태그(선택)     ← 칩 멀티선택 (interest_tag_ids[])
[4] 위치 기반 대화        ← 토글(기본 ON) + 켜면 [현재 위치 사용] 버튼
       │  · navigator.geolocation → lat/lon
       │  · 정확 위치 저장, 노출은 일반화(백엔드 coarsen)
[5] 만들기              ← POST /v1/personas
       └─ 성공 → 대화 화면(그 페르소나)으로
```
요소: 단계 라벨(글쓰기와 동일 패턴), 이름 input, 모델 카드, 태그 칩, 위치 토글+버튼, 만들기 버튼.
API: `buddle.personas.create({name, modelKey, interestTagIds, locationSharing, lat, lon})`.
변수: 위치 토글 ON + 좌표 없으면 만들기 비활성(백엔드도 검증).

## ② 페르소나 상세/수정 (2b, persona-detail)

```
[헤더] 아바타 + 이름 + 모델
[섹션] 활동 요약 (글 수, 대화 세션 수) ← GET /v1/personas/{id}
[수정 폼] 이름 / 모델 / 관심사 / 위치 — 인라인 편집
[저장]  ← PATCH /v1/personas/{id}
[위험] 페르소나 삭제 (확인 후) ← DELETE /v1/personas/{id}
```
API: `personas.get(id)`, `personas.update(id, patch)`, `personas.remove(id)`.

---

## ③ 피드 / 글 상세 (5, feed-detail)

홈의 핫 주제·대화 순위 또는 하단 네비 "피드"에서 진입.

### 3a. 주제별 글 목록 (topic-feed)
```
[상단] 주제 칩 (홈에서 넘어온 주제 강조)
[목록] 글 카드들 ← GET /v1/feed (커서 페이지네이션)
       각 카드: 페르소나 아바타+이름 / 글 미리보기 / 언어 뱃지(한·영) / 좋아요·읽음 수
[무한 스크롤] next_cursor
```
### 3b. 글 상세 + 댓글 (post-detail)
```
[글 본문] content_transformed (수신자 언어 우선) ← GET /v1/posts/{id}
[언어 전환] 한국어 / English (post_translations)
[액션] 좋아요(PUT/DELETE .../like) / 신고
[댓글] 목록 ← GET /v1/plaza/posts/{id}/comments
       작성 ← POST /v1/plaza/posts/{id}/comments
```
API: `feed.list(cursor)`, `posts.get(id)`, `posts.like/unlike(id)`. 댓글은 api.js에 `comments` 추가 필요(아래 보강).

---

## ④ 인박스 (6, inbox)

매개자가 전달한 글(매칭 수신). 하단 네비 또는 알림에서.

```
[목록] 전달받은 글 ← GET /v1/inbox
       각 항목: 보낸 페르소나 / 글 미리보기(내 언어) / 도착 시간 / 안읽음 표시
[탭하면] 글 상세(3b)로 + 읽음 처리 ← POST /v1/inbox/{id}/seen
```
API: `inbox.list()`, `inbox.seen(id)`.

---

## ⑤ 로그인 / 온보딩 (0, login)

앱 진입점. 미인증 시 첫 화면.

```
[로고 + 한 줄 소개]  "생각을 적으면, 언어를 넘어 닿습니다"
[탭 전환] 로그인 / 회원가입
  로그인:   이메일 + 비밀번호           ← POST /v1/auth/login
  회원가입: 이메일 + 비밀번호 + 확인      ← POST /v1/auth/signup → 자동 로그인
[성공] 토큰 저장(메모리) → 홈으로
```
API: `auth.login(email, pw)`, `auth.signup(email, pw, pwConfirm)`. 비밀번호 복잡도 안내(백엔드 규칙).

---

## ⑥ 근처 사람 매칭 (2c, nearby)

페르소나 선택/대화에서 "근처 보기". 위치 공유 ON일 때만.

```
[안내] 위치 기반 매칭 설명 + 공유 OFF면 켜기 유도
[목록] 가까운 페르소나 ← GET /v1/proximity/personas/{id}/nearby
       각 항목: 페르소나 / 근접도(동심원 링 점수) / 대략 거리(coarsened) / 공통 주제
[탭하면] 그 상대와 주제 대화 세션 열기 → 대화(3)
```
API: `proximity.nearby(personaId)`, `proximity.setLocation(...)`.

---

## api.js 보강 필요 (댓글)

피드/글상세에서 댓글이 필요하므로 api.js에 추가:
```js
const comments = {
  list(postId) { return request("GET", `/v1/plaza/posts/${postId}/comments`); },
  create(postId, content) { return request("POST", `/v1/plaza/posts/${postId}/comments`, { content }); },
};
```
(글 작성자=사람일 때 댓글 스키마는 CommentCreateRequest: { content }.)

---

## 제작 순서 (이어서)

1. **로그인(⑤)** — 진입점. 가장 먼저 있어야 나머지가 인증됨.
2. **페르소나 생성/상세(①②)** — 설정 박스 "페르소나 관리" 연결.
3. **피드/글상세(③)** + api.js 댓글 보강.
4. **인박스(④)**.
5. **근처 매칭(⑥)** → 대화 세션 열기 연결.

각 화면: 단일 HTML + `api.js` import, 코스믹 라테 + 반투명, 단계 라벨 패턴(글쓰기와 통일).

## 연결 상태 (현재)
- api.js: 26개 호출 전부 백엔드 라우트와 일치 (검증 완료).
- 런타임 전 흐름(회원가입→게시→대화)은 Postgres 필요 → Docker 환경에서 E2E 확인.
- 인증 보호(401), /health(200) 런타임 확인됨.
