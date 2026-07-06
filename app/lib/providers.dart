import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/api.dart';
import 'core/token_store.dart';

/// 인증 상태 — 토큰 존재 여부. 로그인/로그아웃 시 무효화.
final authedProvider = StateProvider<bool>((ref) => TokenStore.instance.isAuthed);

/// 기본 페르소나(글쓰기·위치 매칭의 주체). 없으면 자동 생성.
final defaultPersonaProvider = FutureProvider<Map<String, dynamic>>((ref) {
  ref.watch(authedProvider);
  return Api.instance.ensureDefaultPersona();
});

/// 피드 필터 상태.
final feedTagProvider = StateProvider<String>((ref) => '전체');
final feedQueryProvider = StateProvider<String>((ref) => '');

/// 피드 첫 페이지 (검색·태그 반영). 더 보기는 화면에서 커서로 이어붙인다.
final feedProvider = FutureProvider<Map<String, dynamic>>((ref) {
  ref.watch(authedProvider);
  final tag = ref.watch(feedTagProvider);
  final q = ref.watch(feedQueryProvider);
  return Api.instance.feed(tag: tag, q: q);
});

final trendingProvider = FutureProvider<List<Map<String, dynamic>>>((ref) {
  ref.watch(authedProvider);
  return Api.instance.trendingTags();
});

final newsProvider = FutureProvider<List<Map<String, dynamic>>>((ref) {
  ref.watch(authedProvider);
  return Api.instance.newsBriefings();
});

final digestProvider = FutureProvider<Map<String, dynamic>>((ref) {
  ref.watch(authedProvider);
  return Api.instance.newsDigest();
});

final notificationsProvider =
    FutureProvider<List<Map<String, dynamic>>>((ref) {
  ref.watch(authedProvider);
  return Api.instance.notifications();
});

final unreadCountProvider = FutureProvider<int>((ref) {
  ref.watch(authedProvider);
  return Api.instance.unreadCount();
});
