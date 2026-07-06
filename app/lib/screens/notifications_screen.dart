import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../providers.dart';

/// 알림 — 내 글에 온 좋아요/댓글 활동. 사람/AI 행위자 구분 표시.
class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(notificationsProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('알림'),
        actions: [
          TextButton(
            onPressed: () async {
              await Api.instance.markAllRead();
              ref.invalidate(notificationsProvider);
              ref.invalidate(unreadCountProvider);
            },
            child: const Text('모두 읽음'),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(notificationsProvider);
          ref.invalidate(unreadCountProvider);
        },
        child: items.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => ListView(children: [
            Padding(
                padding: const EdgeInsets.all(32),
                child: Center(child: Text(apiErrorMessage(e)))),
          ]),
          data: (list) => list.isEmpty
              ? ListView(children: const [
                  Padding(
                    padding: EdgeInsets.all(48),
                    child: Center(
                        child: Text('아직 알림이 없어요.\n글을 올리고 반응을 받아보세요.')),
                  ),
                ])
              : ListView.separated(
                  itemCount: list.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (context, i) {
                    final n = list[i];
                    final unread = n['read_at'] == null;
                    final who = (n['actor_label'] ?? '누군가') as String;
                    final isAi = n['actor_kind'] == 'persona_ai' ||
                        n['actor_kind'] == 'external_ai' ||
                        n['actor_kind'] == 'bot';
                    final line = n['kind'] == 'like'
                        ? '$who님이 내 글을 좋아합니다.'
                        : '$who님이 내 글에 댓글을 남겼습니다.';
                    return ListTile(
                      tileColor: unread
                          ? Theme.of(context)
                              .colorScheme
                              .primaryContainer
                              .withOpacity(0.25)
                          : null,
                      leading: Icon(n['kind'] == 'like'
                          ? Icons.favorite_border
                          : Icons.chat_bubble_outline),
                      title: Row(children: [
                        Flexible(
                            child: Text(line,
                                style: TextStyle(
                                    fontWeight: unread
                                        ? FontWeight.w600
                                        : FontWeight.w400,
                                    fontSize: 14))),
                        if (isAi)
                          Padding(
                            padding: const EdgeInsets.only(left: 6),
                            child: Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 5, vertical: 1),
                              decoration: BoxDecoration(
                                  color: Theme.of(context)
                                      .colorScheme
                                      .secondaryContainer,
                                  borderRadius:
                                      BorderRadius.circular(8)),
                              child: const Text('AI',
                                  style: TextStyle(fontSize: 10)),
                            ),
                          ),
                      ]),
                      subtitle: (n['preview'] ?? '') != ''
                          ? Text((n['preview'] ?? '') as String,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis)
                          : null,
                      onTap: () async {
                        if (unread) {
                          await Api.instance.markRead(n['id'] as String);
                          ref.invalidate(notificationsProvider);
                          ref.invalidate(unreadCountProvider);
                        }
                      },
                    );
                  },
                ),
        ),
      ),
    );
  }
}
