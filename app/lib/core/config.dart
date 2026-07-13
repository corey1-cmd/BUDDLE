/// 앱 전역 설정 — 백엔드 주소는 빌드타임 주입.
///
/// 배포 서버:  flutter build apk --dart-define=API_BASE=https://<도메인>
/// 로컬 개발:  flutter run --dart-define=API_BASE=http://10.0.2.2:8000
///             (10.0.2.2 = Android 에뮬레이터에서 호스트 PC의 localhost)
library;

class AppConfig {
  static const String apiBase = String.fromEnvironment(
    'API_BASE',
    defaultValue: 'http://10.0.2.2:8000',
  );

  /// ws(s):// 형태의 WebSocket 베이스 (http→ws, https→wss).
  static String get wsBase =>
      apiBase.replaceFirst(RegExp(r'^http'), 'ws');
}
