# buddle 안드로이드 앱 (클로즈드 베타)

Flutter 앱 — 백엔드(FastAPI)와 REST/WSS로만 통신. 비즈니스 로직 없음(백엔드가 권위).

## 화면 (베타 슬라이스 7 + 위치)

| # | 화면 | 파일 | 백엔드 |
|---|---|---|---|
| ① | 로그인/가입 | `screens/login_screen.dart` | /v1/auth (JWT, 회전 refresh) |
| ② | 화제·게시글 피드 (검색·트렌딩 칩) | `screens/feed_screen.dart` | /v1/feed?q=&tag=, /v1/tags/trending |
| ③ | **대화형 글쓰기** — 말하기→AI 정리→초안→**AI 보정**→**공식 출처 인용 추천**→게시 | `screens/compose_screen.dart` | WSS /v1/ws/dialogue + /v1/posts + /v1/news/briefings(권리 배지) |
| ④ | 게시글 이해 AI ("이 글 무슨 말이지?") | `screens/argument_chat_screen.dart` | WSS /v1/ws/argument/{post}?mode=claim\|author |
| ⑤ | 토론 흐름 요약 (찬반·쟁점 즉답) | `screens/debate_screen.dart` | /v1/topics/{tag}/debate |
| ⑥ | 뉴스 화제 티저 (제목+링크+우리 요약, 공공누리 배지) | `screens/news_screen.dart` | /v1/news/briefings, /v1/news/digest |
| ⑦ | 댓글 토론 (정보/공감/질문) + 좋아요/저장 | `screens/post_detail_screen.dart` | /v1/plaza/... |
| + | 위치 매칭 (10단계 계층: 이웃→세계) | `screens/nearby_screen.dart` | /v1/proximity (tier + graded_affinity) |
| + | 알림 (사람/AI 행위자 구분) | `screens/notifications_screen.dart` | /v1/notifications |

핵심 설계:
- **토큰**: flutter_secure_storage(Keystore). 401 시 회전 refresh로 1회 자동 재발급(`core/api.dart`).
- **WSS 인증**: 첫 프레임 토큰(쿼리스트링 금지 — 백엔드 보안 설계와 동일)(`core/ws.dart`).
- **인용 추천**: 초안 키워드와 겹치는 브리핑 중 `rights=kogl_type1`(공공누리 1유형 — 출처표시 시
  인용·2차창작 가능)을 우선 정렬해 "인용/재구성 가능" 배지와 함께 제시. 탭 한 번으로 출처 줄 삽입.
- **위치**: opt-in(버튼을 눌렀을 때만 권한 요청·전송). 상대에겐 일반화 좌표만.

## 실행

```bash
# 에뮬레이터에서 로컬 백엔드로 (10.0.2.2 = 호스트 localhost)
flutter run --dart-define=API_BASE=http://10.0.2.2:8000

# 배포 서버로
flutter run --dart-define=API_BASE=https://<BUDDLE_DOMAIN>
```

## 검증 / 빌드

```bash
flutter analyze          # 정적 분석 (현재 0 issue)
flutter test             # 위젯 스모크 테스트

# Play 클로즈드 베타용 AAB (서명 설정 후)
flutter build appbundle --release --dart-define=API_BASE=https://<BUDDLE_DOMAIN>
```

서명·업로드는 베타 스펙 Phase 4 참고:
[docs/superpowers/specs/2026-06-28-buddle-android-beta-design.md](../docs/superpowers/specs/2026-06-28-buddle-android-beta-design.md)
