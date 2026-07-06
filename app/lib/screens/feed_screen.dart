import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../providers.dart';
import 'account_screen.dart';
import 'bookmarks_screen.dart';
import 'debate_screen.dart';
import 'post_detail_screen.dart';

/// ② 화제·게시글 피드 (홈) — 검색 + 트렌딩 화제 칩 + 카드.
class FeedScreen extends ConsumerStatefulWidget {
  const FeedScreen({super.key});

  @override
  ConsumerState<FeedScreen> createState() => _FeedScreenState();
}

class _FeedScreenState extends ConsumerState<FeedScreen> {
  final _search = TextEditingController();
  final _extra = <Map<String, dynamic>>[]; // "더 보기"로 이어붙인 페이지들
  String? _cursor;

  Future<void> _loadMore() async {
    if (_cursor == null) return;
    final page = await Api.instance.feed(
      cursor: _cursor,
      tag: ref.read(feedTagProvider),
      q: ref.read(feedQueryProvider),
    );
    setState(() {
      _extra.addAll((page['items'] as List).cast<Map<String, dynamic>>());
      _cursor = page['next_cursor'] as String?;
    });
  }

  @override
  Widget build(BuildContext context) {
    final feed = ref.watch(feedProvider);
    final trending = ref.watch(trendingProvider).valueOrNull ?? const [];
    final currentTag = ref.watch(feedTagProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('buddle 피드'),
        centerTitle: false,
        actions: [
          IconButton(
            icon: const Icon(Icons.bookmark_border),
            tooltip: '저장한 글',
            onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const BookmarksScreen())),
          ),
          IconButton(
            icon: const Icon(Icons.account_circle_outlined),
            tooltip: '계정',
            onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const AccountScreen())),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          setState(() {
            _extra.clear();
            _cursor = null;
          });
          ref.invalidate(feedProvider);
          ref.invalidate(trendingProvider);
        },
        child: ListView(
          padding: const EdgeInsets.all(12),
          children: [
            TextField(
              controller: _search,
              textInputAction: TextInputAction.search,
              onSubmitted: (v) {
                _extra.clear();
                _cursor = null;
                ref.read(feedQueryProvider.notifier).state = v.trim();
              },
              decoration: InputDecoration(
                hintText: '화제·글 내용 검색',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _search.text.isEmpty
                    ? null
                    : IconButton(
                        icon: const Icon(Icons.clear),
                        onPressed: () {
                          _search.clear();
                          ref.read(feedQueryProvider.notifier).state = '';
                        }),
                border:
                    OutlineInputBorder(borderRadius: BorderRadius.circular(24)),
                isDense: true,
              ),
            ),
            const SizedBox(height: 10),
            SizedBox(
              height: 40,
              child: ListView(
                scrollDirection: Axis.horizontal,
                children: [
                  for (final t in ['전체', ...trending.map((e) => e['name'] as String)])
                    Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ChoiceChip(
                        label: Text(t),
                        selected: t == currentTag,
                        onSelected: (_) {
                          _extra.clear();
                          _cursor = null;
                          ref.read(feedTagProvider.notifier).state = t;
                        },
                      ),
                    ),
                ],
              ),
            ),
            if (currentTag != '전체')
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  icon: const Icon(Icons.insights, size: 18),
                  label: Text('"$currentTag" 토론 흐름 요약 보기'),
                  onPressed: () => openDebateForTagName(context, currentTag),
                ),
              ),
            const SizedBox(height: 4),
            feed.when(
              loading: () => const Padding(
                  padding: EdgeInsets.all(40),
                  child: Center(child: CircularProgressIndicator())),
              error: (e, _) => _ErrorBox(message: apiErrorMessage(e)),
              data: (page) {
                final items = [
                  ...(page['items'] as List).cast<Map<String, dynamic>>(),
                  ..._extra,
                ];
                _cursor ??= page['next_cursor'] as String?;
                if (items.isEmpty) {
                  return const Padding(
                    padding: EdgeInsets.all(40),
                    child: Center(child: Text('아직 글이 없어요. 첫 글을 써볼까요?')),
                  );
                }
                return Column(
                  children: [
                    for (final it in items) _PostCard(item: it),
                    if (_cursor != null)
                      TextButton(
                          onPressed: _loadMore, child: const Text('더 보기')),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _PostCard extends StatelessWidget {
  const _PostCard({required this.item});
  final Map<String, dynamic> item;

  @override
  Widget build(BuildContext context) {
    final persona =
        (item['source_persona']?['name'] ?? '익명') as String;
    final tags = ((item['tags'] ?? const []) as List)
        .map((t) => t is Map ? (t['name'] ?? '') : '$t')
        .where((n) => '$n'.isNotEmpty)
        .toList();
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => PostDetailScreen(post: item))),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                CircleAvatar(
                    radius: 14,
                    child: Text(persona.characters.first,
                        style: const TextStyle(fontSize: 13))),
                const SizedBox(width: 8),
                Text(persona,
                    style: const TextStyle(fontWeight: FontWeight.w600)),
              ]),
              const SizedBox(height: 8),
              Text(
                (item['content_transformed'] ?? '') as String,
                maxLines: 4,
                overflow: TextOverflow.ellipsis,
              ),
              if (tags.isNotEmpty) ...[
                const SizedBox(height: 8),
                Wrap(
                  spacing: 6,
                  children: [
                    for (final t in tags.take(4))
                      Text('#$t',
                          style: TextStyle(
                              fontSize: 12,
                              color: Theme.of(context).colorScheme.primary)),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _ErrorBox extends StatelessWidget {
  const _ErrorBox({required this.message});
  final String message;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(32),
        child: Center(child: Text(message)),
      );
}
