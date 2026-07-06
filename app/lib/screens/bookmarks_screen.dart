import 'package:flutter/material.dart';

import '../core/api.dart';
import 'post_detail_screen.dart';

/// 저장한 글 — 비공개 읽기 목록 (피드 카드와 같은 형태).
class BookmarksScreen extends StatefulWidget {
  const BookmarksScreen({super.key});

  @override
  State<BookmarksScreen> createState() => _BookmarksScreenState();
}

class _BookmarksScreenState extends State<BookmarksScreen> {
  List<Map<String, dynamic>>? _items;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final items = await Api.instance.bookmarks();
      if (mounted) setState(() => _items = items);
    } catch (e) {
      if (mounted) setState(() => _error = apiErrorMessage(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('저장한 글')),
      body: _error != null
          ? Center(child: Text(_error!))
          : _items == null
              ? const Center(child: CircularProgressIndicator())
              : _items!.isEmpty
                  ? const Center(
                      child: Text('아직 저장한 글이 없어요.\n마음에 드는 글의 저장을 눌러 모아두세요.',
                          textAlign: TextAlign.center))
                  : RefreshIndicator(
                      onRefresh: _load,
                      child: ListView.builder(
                        padding: const EdgeInsets.all(12),
                        itemCount: _items!.length,
                        itemBuilder: (context, i) {
                          final it = _items![i];
                          final persona =
                              (it['source_persona']?['name'] ?? '익명') as String;
                          return Card(
                            margin: const EdgeInsets.only(bottom: 10),
                            child: ListTile(
                              leading: CircleAvatar(
                                  child: Text(persona.characters.first)),
                              title: Text(persona),
                              subtitle: Text(
                                  (it['content_transformed'] ?? '') as String,
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis),
                              onTap: () => Navigator.of(context).push(
                                  MaterialPageRoute(
                                      builder: (_) =>
                                          PostDetailScreen(post: it))),
                            ),
                          );
                        },
                      ),
                    ),
    );
  }
}
