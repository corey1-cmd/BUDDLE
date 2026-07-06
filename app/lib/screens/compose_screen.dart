import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/ws.dart';
import '../providers.dart';

/// ③ 대화형 글쓰기 — 이 앱의 핵심 순환.
///
/// 말하기(AI 대화) → AI가 주장·근거·논점 정리(초안) → 사용자 수정 →
/// **AI 보정**(한마디를 객관적·정중한 문장으로) → **공식 출처 인용 추천**
/// (공공누리 1유형 = 인용·재구성 가능 배지 우선) → 게시.
class ComposeScreen extends ConsumerStatefulWidget {
  const ComposeScreen({super.key});

  @override
  ConsumerState<ComposeScreen> createState() => _ComposeScreenState();
}

class _Msg {
  _Msg(this.mine, this.text);
  final bool mine;
  final String text;
}

class _ComposeScreenState extends ConsumerState<ComposeScreen>
    with AutomaticKeepAliveClientMixin {
  BuddleSocket? _socket;
  StreamSubscription<WsFrame>? _sub;
  String? _personaId;

  final _messages = <_Msg>[];
  final _input = TextEditingController();
  final _draft = TextEditingController();
  final _scroll = ScrollController();
  bool _typing = false;
  bool _draftMode = false; // false=대화, true=초안 검토
  bool _busy = false;
  // AI 응답을 초안으로 받는 중인지 (보정/정리 요청의 다음 응답을 초안에 넣음)
  bool _captureToDraft = false;
  List<Map<String, dynamic>> _citations = const [];

  @override
  bool get wantKeepAlive => true;

  Future<void> _ensureSocket() async {
    if (_socket != null) return;
    final persona = await Api.instance.ensureDefaultPersona();
    _personaId = persona['id'] as String;
    final s = BuddleSocket.dialogue(_personaId!);
    _socket = s;
    _sub = s.frames.listen((f) {
      if (!mounted) return;
      setState(() {
        switch (f.type) {
          case 'persona_message':
            _typing = false;
            if (_captureToDraft) {
              _captureToDraft = false;
              _draft.text = f.content;
              _draftMode = true;
              _busy = false;
              _loadCitations();
            } else {
              _messages.add(_Msg(false, f.content));
            }
          case 'typing':
            _typing = f.typingStart;
          case 'error':
            _typing = false;
            _busy = false;
            _messages
                .add(_Msg(false, '⚠ ${f.data['message'] ?? '오류'}'));
        }
      });
      _autoScroll();
    });
  }

  void _autoScroll() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.jumpTo(_scroll.position.maxScrollExtent);
      }
    });
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty) return;
    await _ensureSocket();
    setState(() {
      _messages.add(_Msg(true, text));
      _typing = true;
    });
    _socket!.sendUserMessage(text);
    _input.clear();
    _autoScroll();
  }

  /// 대화 전체 → 주장·근거·논점을 갖춘 글 초안으로 정리 요청.
  Future<void> _makeDraft() async {
    if (_messages.isEmpty && _draft.text.trim().isEmpty) return;
    await _ensureSocket();
    setState(() {
      _busy = true;
      _captureToDraft = true;
      _typing = true;
    });
    final base = _draft.text.trim().isNotEmpty
        ? _draft.text.trim()
        : _messages.where((m) => m.mine).map((m) => m.text).join('\n');
    _socket!.sendUserMessage(
        '지금까지 내가 말한 내용을 하나의 글로 정리해줘. 요구사항: '
        '(1) 핵심 주장을 첫 문단에 명확히, (2) 근거를 항목으로, '
        '(3) 감정적 표현은 객관적이고 정중한 문장으로 보정, '
        '(4) 빠진 논점이나 반론이 있으면 마지막에 한 줄로 짚어줘. '
        '설명 없이 게시할 글 본문만 출력해줘.\n\n--- 내 생각 ---\n$base');
  }

  /// 현재 초안 한 번 더 AI 보정 (객관성·신뢰감 향상).
  Future<void> _refineDraft() async {
    if (_draft.text.trim().isEmpty) return;
    await _ensureSocket();
    setState(() {
      _busy = true;
      _captureToDraft = true;
    });
    _socket!.sendUserMessage(
        '다음 글을 보정해줘: 단정적·감정적 표현을 완화하고, 주장-근거 구조를 '
        '분명히 하고, 과장 없이 객관적이고 신뢰감 있는 톤으로. '
        '본문만 출력해줘.\n\n${_draft.text.trim()}');
  }

  /// 초안 키워드와 겹치는 공식 출처(뉴스 브리핑) 인용 추천.
  /// 공공누리 1유형(정부·공공)은 "인용·재구성 가능"이라 최우선 정렬.
  Future<void> _loadCitations() async {
    try {
      final briefings = await Api.instance.newsBriefings(limit: 60);
      final words = _draft.text
          .split(RegExp(r'[\s,.!?~·]+'))
          .where((w) => w.length >= 2)
          .toSet();
      int overlap(Map<String, dynamic> b) {
        final hay = '${b['title']} ${b['gist_ko']} ${(b['tags'] as List).join(' ')}';
        return words.where(hay.contains).length;
      }

      final scored = briefings
          .map((b) => (b: b, score: overlap(b)))
          .where((e) => e.score > 0)
          .toList()
        ..sort((x, y) {
          final xOpen = x.b['rights'] == 'kogl_type1' ? 1 : 0;
          final yOpen = y.b['rights'] == 'kogl_type1' ? 1 : 0;
          if (xOpen != yOpen) return yOpen - xOpen; // 개방 출처 우선
          return y.score - x.score;
        });
      if (mounted) {
        setState(() => _citations =
            scored.take(5).map((e) => e.b).toList(growable: false));
      }
    } catch (_) {/* 인용 추천은 부가 기능 — 실패해도 글쓰기 무중단 */}
  }

  void _insertCitation(Map<String, dynamic> b) {
    final line = '\n\n(참고: ${b['title']} — ${b['source']}, ${b['url']})';
    _draft.text = _draft.text.trimRight() + line;
  }

  Future<void> _publish() async {
    final content = _draft.text.trim();
    if (content.isEmpty || _personaId == null) return;
    setState(() => _busy = true);
    try {
      await Api.instance
          .createPost(personaId: _personaId!, content: content);
      if (!mounted) return;
      setState(() {
        _draftMode = false;
        _draft.clear();
        _messages.clear();
        _citations = const [];
      });
      ref.invalidate(feedProvider);
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('게시했어요! 피드에서 확인해 보세요.')));
    } catch (e) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _sub?.cancel();
    _socket?.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(_draftMode ? '초안 검토' : '대화로 글쓰기'),
        actions: [
          if (_draftMode)
            TextButton(
                onPressed: () => setState(() => _draftMode = false),
                child: const Text('← 대화로')),
        ],
      ),
      body: _draftMode ? _buildDraft(context) : _buildChat(context),
    );
  }

  Widget _buildChat(BuildContext context) {
    return Column(children: [
      Container(
        width: double.infinity,
        padding: const EdgeInsets.all(10),
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        child: const Text(
          '글을 잘 쓸 필요 없어요 — 생각을 말하듯 던지면, AI가 주장·근거를 정리해 초안을 만들어 드립니다.',
          style: TextStyle(fontSize: 12),
        ),
      ),
      Expanded(
        child: _messages.isEmpty
            ? const Center(
                child: Text('어떤 이야기를 하고 싶으세요?\n예) "요즘 전세 제도가 문제인 것 같아"',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.grey)))
            : ListView.builder(
                controller: _scroll,
                padding: const EdgeInsets.all(12),
                itemCount: _messages.length + (_typing ? 1 : 0),
                itemBuilder: (context, i) {
                  if (i == _messages.length) {
                    return const Align(
                        alignment: Alignment.centerLeft,
                        child: Padding(
                            padding: EdgeInsets.all(8),
                            child: Text('생각 중…',
                                style: TextStyle(color: Colors.grey))));
                  }
                  final m = _messages[i];
                  return Align(
                    alignment: m.mine
                        ? Alignment.centerRight
                        : Alignment.centerLeft,
                    child: Container(
                      margin: const EdgeInsets.symmetric(vertical: 4),
                      padding: const EdgeInsets.all(12),
                      constraints: BoxConstraints(
                          maxWidth:
                              MediaQuery.of(context).size.width * 0.78),
                      decoration: BoxDecoration(
                        color: m.mine
                            ? Theme.of(context)
                                .colorScheme
                                .primaryContainer
                            : Theme.of(context)
                                .colorScheme
                                .surfaceContainerHighest,
                        borderRadius: BorderRadius.circular(14),
                      ),
                      child: Text(m.text),
                    ),
                  );
                },
              ),
      ),
      SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Row(children: [
              Expanded(
                child: TextField(
                  controller: _input,
                  onSubmitted: (_) => _send(),
                  decoration: const InputDecoration(
                      hintText: '생각을 말해보세요…', isDense: true),
                ),
              ),
              IconButton(icon: const Icon(Icons.send), onPressed: _send),
            ]),
            SizedBox(
              width: double.infinity,
              child: FilledButton.tonalIcon(
                icon: const Icon(Icons.auto_awesome, size: 18),
                label: Text(_busy ? '정리 중…' : '대화를 글 초안으로 정리'),
                onPressed:
                    _busy || _messages.isEmpty ? null : _makeDraft,
              ),
            ),
          ]),
        ),
      ),
    ]);
  }

  Widget _buildDraft(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        TextField(
          controller: _draft,
          maxLines: null,
          minLines: 8,
          decoration: const InputDecoration(
            border: OutlineInputBorder(),
            labelText: '초안 (자유롭게 수정하세요)',
          ),
        ),
        const SizedBox(height: 10),
        Row(children: [
          Expanded(
            child: OutlinedButton.icon(
              icon: const Icon(Icons.auto_fix_high, size: 18),
              label: const Text('AI 보정'),
              onPressed: _busy ? null : _refineDraft,
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: FilledButton.icon(
              icon: const Icon(Icons.publish, size: 18),
              label: Text(_busy ? '처리 중…' : '게시하기'),
              onPressed: _busy ? null : _publish,
            ),
          ),
        ]),
        const SizedBox(height: 18),
        Row(children: [
          const Icon(Icons.format_quote, size: 18),
          const SizedBox(width: 6),
          Text('공식 출처 인용 추천',
              style: Theme.of(context).textTheme.titleSmall),
          const Spacer(),
          IconButton(
              icon: const Icon(Icons.refresh, size: 18),
              onPressed: _loadCitations),
        ]),
        if (_citations.isEmpty)
          const Padding(
            padding: EdgeInsets.all(12),
            child: Text('초안과 겹치는 출처를 찾지 못했어요. 새로고침을 눌러보세요.',
                style: TextStyle(fontSize: 13, color: Colors.grey)),
          ),
        for (final b in _citations)
          Card(
            margin: const EdgeInsets.only(bottom: 8),
            child: ListTile(
              title: Text((b['title'] ?? '') as String,
                  maxLines: 2, overflow: TextOverflow.ellipsis),
              subtitle: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text((b['gist_ko'] ?? '') as String,
                      maxLines: 2, overflow: TextOverflow.ellipsis),
                  const SizedBox(height: 4),
                  Row(children: [
                    Text((b['source'] ?? '') as String,
                        style: const TextStyle(fontSize: 11)),
                    const SizedBox(width: 6),
                    if (b['rights'] == 'kogl_type1')
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 6, vertical: 1),
                        decoration: BoxDecoration(
                            color: const Color(0x1F4FC98F),
                            borderRadius: BorderRadius.circular(8)),
                        child: const Text('공공누리 · 인용/재구성 가능',
                            style: TextStyle(
                                fontSize: 10,
                                color: Color(0xFF6FD9A6))),
                      ),
                  ]),
                ],
              ),
              trailing: IconButton(
                icon: const Icon(Icons.add_link),
                tooltip: '초안에 출처 넣기',
                onPressed: () => _insertCitation(b),
              ),
            ),
          ),
      ],
    );
  }
}
