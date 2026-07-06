import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api.dart';
import '../providers.dart';

/// ⑥ 뉴스(화제 소스) — 권리 인지 티저: 제목+링크+매체명+우리 요약.
/// 본문은 원 출처에서 읽는다(링크 아웃). 공공누리 출처는 개방 배지 표시.
class NewsScreen extends ConsumerWidget {
  const NewsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final news = ref.watch(newsProvider);
    final digest = ref.watch(digestProvider).valueOrNull;

    return Scaffold(
      appBar: AppBar(title: const Text('무슨 일이 벌어지고 있나')),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(newsProvider);
          ref.invalidate(digestProvider);
        },
        child: news.when(
          loading: () =>
              const Center(child: CircularProgressIndicator()),
          error: (e, _) => ListView(children: [
            Padding(
                padding: const EdgeInsets.all(32),
                child: Center(child: Text(apiErrorMessage(e)))),
          ]),
          data: (items) => ListView(
            padding: const EdgeInsets.all(12),
            children: [
              if (digest != null &&
                  ((digest['text'] ?? '') as String).isNotEmpty)
                Card(
                  color:
                      Theme.of(context).colorScheme.secondaryContainer,
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('오늘의 종합 브리핑',
                            style: TextStyle(
                                fontWeight: FontWeight.w700)),
                        const SizedBox(height: 6),
                        Text((digest['text'] ?? '') as String,
                            style: const TextStyle(height: 1.5)),
                      ],
                    ),
                  ),
                ),
              const SizedBox(height: 8),
              if (items.isEmpty)
                const Padding(
                  padding: EdgeInsets.all(40),
                  child: Center(
                      child: Text(
                          '아직 수집된 화제가 없어요.\n(수집은 1시간 주기로 자동 실행됩니다)')),
                ),
              for (final b in items) _BriefingCard(briefing: b),
            ],
          ),
        ),
      ),
    );
  }
}

class _BriefingCard extends StatelessWidget {
  const _BriefingCard({required this.briefing});
  final Map<String, dynamic> briefing;

  @override
  Widget build(BuildContext context) {
    final isOpen = briefing['rights'] == 'kogl_type1';
    final tags = (briefing['tags'] as List? ?? const []).cast<dynamic>();
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () async {
          final url = Uri.tryParse((briefing['url'] ?? '') as String);
          if (url != null) {
            await launchUrl(url, mode: LaunchMode.externalApplication);
          }
        },
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text((briefing['title'] ?? '') as String,
                  style: const TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 6),
              Text((briefing['gist_ko'] ?? '') as String,
                  style: const TextStyle(fontSize: 13.5, height: 1.5)),
              const SizedBox(height: 8),
              Row(children: [
                Text((briefing['source'] ?? '') as String,
                    style: TextStyle(
                        fontSize: 12,
                        color: Theme.of(context).colorScheme.primary)),
                const SizedBox(width: 8),
                if (isOpen)
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 6, vertical: 1),
                    decoration: BoxDecoration(
                        color: const Color(0x1F4FC98F),
                        borderRadius: BorderRadius.circular(8)),
                    child: const Text('공공누리 · 인용/재구성 가능',
                        style: TextStyle(
                            fontSize: 10, color: Color(0xFF6FD9A6))),
                  ),
                const Spacer(),
                const Icon(Icons.open_in_new, size: 14),
              ]),
              if (tags.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Wrap(spacing: 6, children: [
                    for (final t in tags.take(4))
                      Text('#$t', style: const TextStyle(fontSize: 11)),
                  ]),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
