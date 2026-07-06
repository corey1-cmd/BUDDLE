import 'package:dio/dio.dart';

import 'config.dart';
import 'token_store.dart';

/// buddle 백엔드 API 클라이언트 — 프런트·백 계약의 단일 소스.
///
/// 401이면 refresh 토큰으로 1회 자동 재발급 후 원 요청을 재시도한다
/// (백엔드는 회전형 refresh: 재발급마다 새 쌍이 내려온다).
class Api {
  Api._() {
    _dio = Dio(BaseOptions(
      baseUrl: AppConfig.apiBase,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 30),
      headers: {'Content-Type': 'application/json'},
    ));
    _dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) {
        final t = TokenStore.instance.access;
        if (t != null && options.headers['Authorization'] == null) {
          options.headers['Authorization'] = 'Bearer $t';
        }
        handler.next(options);
      },
      onError: (e, handler) async {
        final isAuthPath =
            e.requestOptions.path.startsWith('/v1/auth/');
        if (e.response?.statusCode == 401 &&
            !isAuthPath &&
            e.requestOptions.extra['retried'] != true &&
            TokenStore.instance.refresh != null) {
          final ok = await _tryRefresh();
          if (ok) {
            final opts = e.requestOptions;
            opts.extra['retried'] = true;
            opts.headers['Authorization'] =
                'Bearer ${TokenStore.instance.access}';
            try {
              final res = await _dio.fetch<dynamic>(opts);
              return handler.resolve(res);
            } on DioException catch (e2) {
              return handler.next(e2);
            }
          }
        }
        handler.next(e);
      },
    ));
  }

  static final Api instance = Api._();
  late final Dio _dio;

  Future<bool> _tryRefresh() async {
    try {
      final res = await _dio.post<Map<String, dynamic>>(
        '/v1/auth/refresh',
        data: {'refresh_token': TokenStore.instance.refresh},
        options: Options(headers: {'Authorization': null}),
      );
      final d = res.data!;
      await TokenStore.instance
          .save(d['access_token'] as String, d['refresh_token'] as String);
      return true;
    } catch (_) {
      await TokenStore.instance.clear();
      return false;
    }
  }

  // ── Auth ────────────────────────────────────────────────
  Future<void> signup(String email, String password) async {
    await _dio.post<dynamic>('/v1/auth/signup', data: {
      'email': email,
      'password': password,
      'password_confirm': password,
    });
  }

  Future<void> login(String email, String password) async {
    final res = await _dio.post<Map<String, dynamic>>('/v1/auth/login',
        data: {'email': email, 'password': password});
    final d = res.data!;
    await TokenStore.instance
        .save(d['access_token'] as String, d['refresh_token'] as String);
  }

  Future<void> logout() async {
    try {
      await _dio.post<dynamic>('/v1/auth/logout',
          data: {'refresh_token': TokenStore.instance.refresh});
    } catch (_) {/* best-effort revoke */}
    await TokenStore.instance.clear();
  }

  /// 계정 영구 삭제 (Google Play 필수 — 인앱 경로). 비밀번호 확인.
  Future<void> deleteAccount(String password) async {
    await _dio.delete<dynamic>('/v1/users/me', data: {'password': password});
    await TokenStore.instance.clear();
  }

  // ── Personas (기본 어시스턴트 자동 확보 — 개인화 UI 없음) ──
  Future<Map<String, dynamic>> ensureDefaultPersona() async {
    final list = await _getList('/v1/personas');
    if (list.isNotEmpty) return list.first;
    final models = await _getList('/v1/persona-models');
    final key = models.isNotEmpty
        ? (models.first['template_key'] ?? models.first['model_key'] ?? 'poet')
        : 'poet';
    final res = await _dio.post<Map<String, dynamic>>('/v1/personas',
        data: {'name': '나의 비서', 'model_key': key});
    return res.data!;
  }

  // ── Feed / Posts ────────────────────────────────────────
  Future<Map<String, dynamic>> feed(
      {String? cursor, String? tag, String? q}) async {
    final res = await _dio.get<Map<String, dynamic>>('/v1/feed',
        queryParameters: {
          if (cursor != null) 'cursor': cursor,
          if (tag != null && tag != '전체') 'tag': tag,
          if (q != null && q.isNotEmpty) 'q': q,
        });
    return res.data!;
  }

  Future<List<Map<String, dynamic>>> trendingTags(
          {int days = 7, int limit = 8}) =>
      _getList('/v1/tags/trending',
          query: {'days': '$days', 'limit': '$limit'});

  Future<Map<String, dynamic>> createPost(
      {required String personaId,
      required String content,
      String visibility = 'public'}) async {
    final res = await _dio.post<Map<String, dynamic>>('/v1/posts', data: {
      'persona_id': personaId,
      'content_raw': content,
      'visibility': visibility,
    });
    return res.data!;
  }

  Future<void> like(String postId) =>
      _dio.put<dynamic>('/v1/plaza/posts/$postId/like');
  Future<void> unlike(String postId) =>
      _dio.delete<dynamic>('/v1/plaza/posts/$postId/like');
  Future<void> bookmark(String postId) =>
      _dio.put<dynamic>('/v1/plaza/posts/$postId/bookmark');
  Future<void> unbookmark(String postId) =>
      _dio.delete<dynamic>('/v1/plaza/posts/$postId/bookmark');
  Future<List<Map<String, dynamic>>> bookmarks() => _getList('/v1/bookmarks');

  Future<List<Map<String, dynamic>>> comments(String postId) =>
      _getList('/v1/plaza/posts/$postId/comments');

  Future<Map<String, dynamic>> addComment(
      String postId, String content, String kind) async {
    final res = await _dio.post<Map<String, dynamic>>(
        '/v1/plaza/posts/$postId/comments',
        data: {'content': content, 'kind': kind});
    return res.data!;
  }

  // ── 알림 ─────────────────────────────────────────────────
  Future<List<Map<String, dynamic>>> notifications({int limit = 50}) =>
      _getList('/v1/notifications', query: {'limit': '$limit'});

  Future<int> unreadCount() async {
    final res =
        await _dio.get<Map<String, dynamic>>('/v1/notifications/unread-count');
    return (res.data!['count'] as num).toInt();
  }

  Future<void> markRead(String id) =>
      _dio.post<dynamic>('/v1/notifications/$id/read');
  Future<void> markAllRead() =>
      _dio.post<dynamic>('/v1/notifications/read-all');

  // ── 뉴스 (권리엔진 필터된 티저) ───────────────────────────
  Future<List<Map<String, dynamic>>> newsBriefings(
          {String? tag, int limit = 30}) =>
      _getList('/v1/news/briefings', query: {
        'limit': '$limit',
        if (tag != null && tag.isNotEmpty) 'tag': tag,
      });

  Future<Map<String, dynamic>> newsDigest() async {
    final res = await _dio.get<Map<String, dynamic>>('/v1/news/digest');
    return res.data!;
  }

  // ── 토론 흐름 요약 ────────────────────────────────────────
  Future<List<Map<String, dynamic>>> searchTags(String q) =>
      _getList('/v1/tags', query: {'q': q, 'limit': '10'});

  Future<Map<String, dynamic>> debateDashboard(String tagId) async {
    final res =
        await _dio.get<Map<String, dynamic>>('/v1/topics/$tagId/debate');
    return res.data!;
  }

  // ── 위치 매칭 (opt-in) ───────────────────────────────────
  Future<void> setLocation(String personaId,
      {double? lat, double? lon, required bool sharing}) async {
    await _dio.put<dynamic>('/v1/proximity/personas/$personaId/location',
        data: {'lat': lat, 'lon': lon, 'sharing': sharing});
  }

  Future<List<Map<String, dynamic>>> nearby(String personaId,
          {int limit = 30}) =>
      _getList('/v1/proximity/personas/$personaId/nearby',
          query: {'limit': '$limit'});

  // ── helpers ─────────────────────────────────────────────
  Future<List<Map<String, dynamic>>> _getList(String path,
      {Map<String, String>? query}) async {
    final res = await _dio.get<List<dynamic>>(path, queryParameters: query);
    return (res.data ?? const [])
        .whereType<Map<String, dynamic>>()
        .toList(growable: false);
  }
}

/// 사용자에게 보여줄 짧은 오류 문구 (서버 detail 우선).
String apiErrorMessage(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map) {
      final err = data['error'];
      if (err is Map && err['message'] is String) {
        return err['message'] as String;
      }
      if (data['detail'] is String) return data['detail'] as String;
    }
    if (e.type == DioExceptionType.connectionTimeout ||
        e.type == DioExceptionType.connectionError) {
      return '서버에 연결할 수 없습니다.';
    }
    return '요청이 실패했습니다 (${e.response?.statusCode ?? '네트워크'}).';
  }
  return '알 수 없는 오류가 발생했습니다.';
}
