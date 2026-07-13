# Google Play 클로즈드 베타 출시 체크리스트 (Phase 4)

베타 스펙 §4 Phase 4를 실제 제출까지 이어가기 위한 실행 체크리스트.
백엔드 배포(Phase 1)와 앱 빌드(Phase 3)가 끝난 뒤 진행한다.

## 0. 선행 (Phase 1·3 완료 확인)
- [ ] 백엔드가 `https://<BUDDLE_DOMAIN>`에서 동작 (`/health` 200) — [DEPLOY_ORACLE.md](DEPLOY_ORACLE.md)
- [ ] `개인정보처리방침`이 공개 URL로 접근됨: `https://<BUDDLE_DOMAIN>/privacy.html`
      (백엔드가 web/를 정적 서빙하므로 배포되면 자동 노출)
- [ ] 앱이 배포 서버를 가리킴: `flutter run --dart-define=API_BASE=https://<BUDDLE_DOMAIN>`

## 1. Play Console 계정·앱
- [ ] Google Play 개발자 계정 등록 (**일회성 $25**)
- [ ] 앱 생성 → 앱 이름 "buddle", 기본 언어 한국어
- [ ] **클로즈드 테스트 트랙** 생성, 테스터 이메일 목록 등록 → 초대 링크 공유

## 2. 앱 서명 + AAB 빌드
- [ ] 업로드 키스토어 생성:
      `keytool -genkey -v -keystore upload.jks -keyalg RSA -keysize 2048 -validity 10000 -alias upload`
- [ ] `app/android/key.properties` 작성(커밋 금지) + `app/android/app/build.gradle`에 서명 설정 연결
- [ ] **Play 앱 서명** 사용(권장) — 업로드 키로 서명한 AAB를 올리면 Google이 배포 서명 관리
- [ ] 릴리스 빌드:
      `flutter build appbundle --release --dart-define=API_BASE=https://<BUDDLE_DOMAIN>`
- [ ] 산출물 `build/app/outputs/bundle/release/app-release.aab` 업로드

## 3. 스토어 등록정보(클로즈드도 필수 최소)
- [ ] 앱 아이콘(512×512), 피처 그래픽(1024×500)
- [ ] 스크린샷(폰 최소 2장) — 피드·대화형 글쓰기 화면 권장
- [ ] 짧은 설명 / 자세한 설명 (핵심: "말 한마디를 AI가 객관적 주장으로 다듬고, 공식 출처 인용 추천")

## 4. 정책·데이터 안전 (제출 필수)
- [ ] **개인정보처리방침 URL** 입력: `https://<BUDDLE_DOMAIN>/privacy.html`
- [ ] **계정 삭제**: 인앱 경로(앱 → 계정 → 계정 삭제, 구현됨: `DELETE /v1/users/me`) +
      웹 삭제 요청 경로(개인정보처리방침의 연락처) 둘 다 명시 — Google 필수 요건
- [ ] **데이터 안전(Data safety) 양식** — 아래 표 그대로 신고:

| 데이터 유형 | 수집 | 공유(제3자) | 목적 | 필수/선택 |
|---|---|---|---|---|
| 이메일 주소 | 예 | 아니오 | 계정 관리 | 필수 |
| 사용자 콘텐츠(글·댓글·대화) | 예 | 예(생성형 AI 처리) | 앱 기능 | 필수 |
| 대략적/정확한 위치 | 예 | 아니오 | 앱 기능(근처 매칭) | **선택(opt-in)** |
| 앱 활동·기기 로그 | 예 | 아니오 | 보안·분석 | 필수 |

- [ ] "데이터 전송 중 암호화됨" = 예 (TLS)
- [ ] "사용자가 데이터 삭제를 요청할 수 있음" = 예 (인앱 계정 삭제)
- [ ] **생성형 AI 고지**: 대화·글 텍스트가 외부 AI(예: Gemini)로 전송·처리될 수 있음을
      데이터 안전 및 개인정보처리방침(2항)에 명시 — 이미 반영됨

## 5. 콘텐츠 등급 · 대상 연령
- [ ] 콘텐츠 등급 설문 완료(소셜/사용자 생성 콘텐츠)
- [ ] 대상 연령: **만 14세 이상**(개인정보처리방침 6항과 일치)
- [ ] 광고 포함 여부: 아니오

## 6. 제출 → 검토 → 배포
- [ ] 클로즈드 트랙에 릴리스 생성 → 검토 제출
- [ ] 승인 후 테스터에게 옵트인 링크 안내 → 설치
- [ ] **검증(Phase 4 기준)**: 테스터가 Play에서 설치 → 로그인 → 대화형 글쓰기·게시 →
      피드/뉴스/토론 확인 → 계정 삭제 동작 확인

## 참고 — 구현 현황
- 계정 삭제 API: `DELETE /v1/users/me` (비밀번호 확인, 개인데이터 파기, 토큰 폐기) — 구현·테스트 완료
- 앱 인앱 삭제 UI: 계정 화면(`app/lib/screens/account_screen.dart`)
- 개인정보처리방침: `web/privacy.html` (백엔드 정적 서빙)
- 남은 수작업(사람만 가능): 개발자 계정 결제($25), 키스토어 생성·보관, 스크린샷/그래픽 준비
