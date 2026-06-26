# buddle 프론트엔드 보안 설계 (공격 경로 분석 + 방어)

> 디자인: 노을과 그림자(남색 그라데이션 + 노을빛 강조). 보안: 공격 경로를 예상해 차단.
> 구현: `web/security.js`(유틸) + `web/api.js`(연결 계층). 모든 화면이 로드 시 `sec.harden()`.

---

## 위협 모델

buddle 프론트는 **다른 사용자가 만든 데이터를 렌더**한다 — 페르소나 이름, 글(content_transformed), 주제, 댓글이 API를 통해 들어온다. 따라서 신뢰 경계는 "API 응답"이고, 그 데이터가 내 브라우저에서 코드로 실행되면 안 된다.

---

## 공격 경로별 분석 + 방어

### 1. 저장형 XSS (Stored XSS) — 최우선
**경로**: 공격자가 페르소나 이름을 `<img src=x onerror=alert(document.cookie)>`로 만들거나, 글에 스크립트를 심는다 → 그 페르소나/글이 다른 사용자 화면에 `innerHTML`로 삽입되면 실행.
**실제 발견**: chat의 페르소나 아바타, compose/home/persona-select의 이름·태그·주제가 escape 없이 `innerHTML` 삽입되고 있었음.
**방어**:
- `sec.esc()` — 모든 동적 텍스트를 HTML 엔티티로 이스케이프(`& < > " ' \``). 4개 화면의 모든 사용자/서버 데이터 삽입에 적용.
- `sec.el()` / `sec.setText()` — 가능한 곳은 `textContent`로(파싱 자체를 안 함). 세션 칩·미리보기 텍스트는 이미 textContent.
- 잔여 위험 패턴 0건 확인.

### 2. DOM 기반 XSS / javascript: URL
**경로**: 사용자 입력이 `href`, `src`, `location`에 들어가 `javascript:` 스킴으로 실행.
**방어**: `sec.safeUrl()` — `https:/mailto:/상대경로/앵커`만 허용, `javascript:`·`data:`·`vbscript:` 차단. 링크 생성 시 통과.

### 3. 토큰 탈취
**경로**: JWT가 localStorage에 있으면 XSS 한 번으로 탈취 → 계정 장악.
**방어**:
- 토큰은 **메모리에만**(`api.js` 클로저 변수). localStorage/sessionStorage/cookie 미사용.
- 토큰을 HTML/URL에 **절대 보간하지 않음**(Authorization 헤더로만).
- XSS를 1번에서 원천 차단하므로 메모리 토큰도 안전.
- 401 시 refresh 1회만 시도(무한 루프 방지).

### 4. 클릭재킹 (Clickjacking)
**경로**: 공격 사이트가 buddle을 투명 iframe으로 덮어 사용자가 모르게 클릭(좋아요·게시·삭제) 유도.
**방어**:
- `frame-ancestors 'self'` (CSP) — 외부 도메인 임베드 차단.
- `sec.preventFraming()` — 다른 오리진 프레임에 갇히면 top으로 탈출(프레임버스트). 동일 오리진 임베드는 허용.

### 5. 인젝션을 통한 CSP 우회 / 인라인 스크립트
**경로**: 어떻게든 마크업을 주입해 `<script>`나 인라인 핸들러 실행.
**방어**: CSP 메타 주입(`sec.applyCSP()`) — `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, `connect-src`를 self+ws로 제한. (운영에선 서버 헤더로도 중복 설정 권장 — 메타는 보조.)
- `sec.el()`은 `on*` 속성을 **문자열로 받지 않음**(함수만 addEventListener) → 핸들러 인젝션 차단.

### 6. 프로토타입 오염 (Prototype Pollution)
**경로**: API 응답/병합 객체에 `__proto__` 키가 섞여 전역 객체 오염.
**방어**: `sec.safeKeys()` — `__proto__`·`constructor`·`prototype` 키 제거. `sec` 객체는 `Object.freeze`.

### 7. 입력 검증 우회 / 과대 입력
**경로**: 비정상 입력(초장문, 잘못된 좌표, 약한 비밀번호)으로 서버 부하·오작동 유도.
**방어 (심층 방어)**: `sec.validate` — email/password(백엔드 복잡도 동일: 8자+대소문자+숫자)/personaName(≤64)/thought(≤8000)/lat·lon 범위/topic. **클라 검증은 UX용이고 서버가 최종 검증**(이미 Pydantic).

### 8. CSRF
**경로**: 쿠키 인증이면 교차 사이트 요청 위조 가능.
**방어**: 쿠키 미사용 + Bearer 토큰(헤더) → CSRF 비해당. `form-action 'self'`로 폼 탈취도 차단.

### 9. 오픈 리다이렉트 / 정보 노출
**방어**: 외부 링크는 `safeUrl()` 통과. 토큰·오류 상세를 콘솔/URL에 노출하지 않음(api.js는 메시지만 표면화).

---

## api.js 연결 보안

- 모든 경로가 백엔드 라우트와 일치(검증 완료, 26개).
- 401 → refresh 토큰으로 1회 자동 재시도 후 실패 시 토큰 클리어.
- 요청 바디는 백엔드 Pydantic 스키마와 정합(서버가 재검증).
- WebSocket: 첫 프레임으로 인증(쿼리스트링에 토큰 안 실음 → 로그 노출 방지).

---

## 운영 배포 시 추가 권장 (서버 측)

프론트 메타 CSP는 보조다. 운영에선 **서버 응답 헤더**로 중복 설정:
- `Content-Security-Policy`(메타와 동일 + `script-src`에서 `'unsafe-inline'` 제거하고 nonce 사용)
- `Strict-Transport-Security`(HTTPS 강제)
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: SAMEORIGIN`(구형 브라우저용, frame-ancestors 보조)
- `Referrer-Policy: strict-origin-when-cross-origin`
- 백엔드는 이미 security_headers 미들웨어 보유 → 이 항목들 정렬 확인.

---

## 적용 상태

| 방어 | 구현 | 적용 |
|---|---|---|
| XSS escape | sec.esc | 4개 화면 전체 동적 삽입 ✅ |
| 안전 DOM | sec.el/setText | 신규 화면 권장 |
| URL 검증 | sec.safeUrl | 링크 생성 시 |
| 토큰 메모리 | api.js 클로저 | ✅ |
| 클릭재킹 | CSP + framebust | sec.harden() ✅ |
| CSP | sec.applyCSP | sec.harden() ✅ |
| 프로토타입 오염 | sec.safeKeys | API 파싱 시 |
| 입력 검증 | sec.validate | 폼 화면(로그인·생성·글쓰기) |
| CSRF | Bearer 토큰 | 해당 없음(쿠키 미사용) |

모든 화면은 `<head>`에서 security.js→api.js 순 로드, 스크립트 진입에서 `sec.harden()` 호출.
