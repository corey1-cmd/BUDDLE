import 'package:flutter/material.dart';

import '../core/api.dart';
import 'argument_chat_screen.dart';
import 'debate_screen.dart';

/// ⑦ 게시글 상세 + 댓글 토론 — 좋아요/저장, "이 글 이해하기(AI)" 진입.
class PostDetailScreen extends StatefulWidget {
  const PostDetailScreen({super.key, required this.post});
  final Map<String, dynamic> post;

  @override
  State<PostDetailScreen> createState() => _PostDetailScreenState();
}

class _PostDetailScreenState extends State<PostDetailScreen> {
  List<Map<String, dynamic>> _comments = const [];
  bool _liked = false;
  bool _saved = false;
  String _kind = 'inform';
  final _comment = TextEditingController();

  String get _postId => widget.post['id'] as String;

  @override
  void initState() {
    super.initState();
    _loadComments();
  }

  Future<void> _loadComments() async {
    try {
      final c = await Api.instance.comments(_postId);
      if (mounted) setState(() => _comments = c);
    } catch (_) {/* 오프라인 등 — 빈 목록 유지 */}
  }

  Future<void> _send() async {
    final text = _comment.text.trim();
    if (text.isEmpty) return;
    _comment.clear();
    try {
      final saved = await Api.instance.addComment(_postId, text, _kind);
      setState(() => _comments = [..._comments, saved]);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final persona =
        (widget.post['source_persona']?['name'] ?? '익명') as String;
    final tags = ((widget.post['tags'] ?? const []) as List)
        .whereType<Map<String, dynamic>>()
        .toList();
    const kindLabels = {'inform': '정보', 'empathize': '공감', 'question': '질문'};

    return Scaffold(
      appBar: AppBar(title: const Text('글')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(children: [
            CircleAvatar(child: Text(persona.characters.first)),
            const SizedBox(width: 10),
            Text(persona,
                style: const TextStyle(
                    fontWeight: FontWeight.w600, fontSize: 16)),
          ]),
          const SizedBox(height: 14),
          Text((widget.post['content_transformed'] ?? '') as String,
              style: const TextStyle(fontSize: 16, height: 1.65)),
          const SizedBox(height: 16),
          Row(children: [
            IconButton(
              icon: Icon(_liked ? Icons.favorite : Icons.favorite_border,
                  color: _liked ? Colors.redAccent : null),
              onPressed: () async {
                setState(() => _liked = !_liked);
                try {
                  _liked
                      ? await Api.instance.like(_postId)
                      : await Api.instance.unlike(_postId);
                } catch (_) {}
              },
            ),
            IconButton(
              icon: Icon(_saved ? Icons.bookmark : Icons.bookmark_border),
              onPressed: () async {
                setState(() => _saved = !_saved);
                try {
                  _saved
                      ? await Api.instance.bookmark(_postId)
                      : await Api.instance.unbookmark(_postId);
                } catch (_) {}
              },
            ),
          ]),
          const Divider(),
          // ④ 게시글 이해 AI — "이 글 무슨 말이지?"
          Wrap(spacing: 8, runSpacing: 8, children: [
            FilledButton.tonalIcon(
              icon: const Icon(Icons.psychology_alt_outlined, size: 18),
              label: const Text('이 글의 주장과 대화'),
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => ArgumentChatScreen(
                      postId: _postId, mode: 'claim', title: '게시글 이해 AI'))),
            ),
            FilledButton.tonalIcon(
              icon: const Icon(Icons.person_search_outlined, size: 18),
              label: const Text('이 사람의 생각과 대화'),
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => ArgumentChatScreen(
                      postId: _postId, mode: 'author', title: '작성자 생각 AI'))),
            ),
            // ⑤ 토론 흐름 요약 — 첫 태그의 화제 대시보드
            if (tags.isNotEmpty)
              OutlinedButton.icon(
                icon: const Icon(Icons.insights, size: 18),
                label: Text('#${tags.first['name']} 토론 요약'),
                onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => DebateScreen(
                        tagId: tags.first['id'] as String,
                        tagName: tags.first['name'] as String))),
              ),
          ]),
          const SizedBox(height: 12),
          Text('댓글 ${_comments.length}',
              style: const TextStyle(
                  fontWeight: FontWeight.w600, fontSize: 15)),
          const SizedBox(height: 6),
          for (final c in _comments)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: CircleAvatar(
                  radius: 14,
                  child: Text(
                      ((c['author_label'] ?? '익') as String)
                          .characters
                          .first,
                      style: const TextStyle(fontSize: 12))),
              title: Row(children: [
                Text((c['author_label'] ?? '익명') as String,
                    style: const TextStyle(
                        fontSize: 13, fontWeight: FontWeight.w600)),
                const SizedBox(width: 6),
                if (kindLabels[c['kind']] != null)
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 6, vertical: 1),
                    decoration: BoxDecoration(
                        color: Theme.of(context)
                            .colorScheme
                            .primaryContainer,
                        borderRadius: BorderRadius.circular(8)),
                    child: Text(kindLabels[c['kind']]!,
                        style: const TextStyle(fontSize: 10)),
                  ),
              ]),
              subtitle: Text((c['content'] ?? '') as String),
            ),
        ],
      ),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: EdgeInsets.only(
              left: 12,
              right: 12,
              bottom: MediaQuery.of(context).viewInsets.bottom + 8,
              top: 6),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Row(children: [
              for (final k in kindLabels.entries)
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: ChoiceChip(
                    label: Text(k.value,
                        style: const TextStyle(fontSize: 12)),
                    selected: _kind == k.key,
                    onSelected: (_) => setState(() => _kind = k.key),
                  ),
                ),
            ]),
            Row(children: [
              Expanded(
                child: TextField(
                  controller: _comment,
                  decoration: const InputDecoration(
                      hintText: '댓글을 남겨보세요…', isDense: true),
                ),
              ),
              IconButton(
                  icon: const Icon(Icons.send), onPressed: _send),
            ]),
          ]),
        ),
      ),
    );
  }
}
