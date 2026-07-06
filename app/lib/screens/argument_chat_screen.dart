import 'dart:async';

import 'package:flutter/material.dart';

import '../core/ws.dart';

/// ④ 게시글 이해 AI — 그 글(사용자 글)을 분석한 AI와 RAG 대화.
/// "이 글 무슨 말이지?"에 핵심주장·논리구조·개념을 설명하고 질문에 답한다.
/// 유용한 답은 글의 '부가 맥락'으로 저장 가능(save_note).
class ArgumentChatScreen extends StatefulWidget {
  const ArgumentChatScreen(
      {super.key,
      required this.postId,
      required this.mode,
      required this.title});
  final String postId;
  final String mode; // claim | author
  final String title;

  @override
  State<ArgumentChatScreen> createState() => _ArgumentChatScreenState();
}

class _Msg {
  _Msg(this.mine, this.text, {this.label});
  final bool mine;
  final String text;
  final String? label;
}

class _ArgumentChatScreenState extends State<ArgumentChatScreen> {
  late final BuddleSocket _socket;
  StreamSubscription<WsFrame>? _sub;
  final _messages = <_Msg>[];
  final _input = TextEditingController();
  final _scroll = ScrollController();
  bool _typing = false;

  @override
  void initState() {
    super.initState();
    _socket = BuddleSocket.argument(widget.postId, mode: widget.mode);
    _sub = _socket.frames.listen((f) {
      if (!mounted) return;
      setState(() {
        switch (f.type) {
          case 'ai_message':
            _typing = false;
            _messages.add(_Msg(false, f.content,
                label: (f.data['label'] ?? '') as String));
          case 'typing':
            _typing = f.typingStart;
          case 'note_saved':
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                content: Text('글의 부가 맥락으로 저장했어요.')));
          case 'error':
            _typing = false;
            _messages.add(
                _Msg(false, '⚠ ${f.data['message'] ?? '오류가 발생했습니다.'}'));
          case 'closed':
            _typing = false;
        }
      });
      _autoScroll();
    });
  }

  void _autoScroll() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 200),
            curve: Curves.easeOut);
      }
    });
  }

  void _send() {
    final text = _input.text.trim();
    if (text.isEmpty) return;
    setState(() {
      _messages.add(_Msg(true, text));
      _typing = true;
    });
    _socket.sendUserMessage(text);
    _input.clear();
    _autoScroll();
  }

  @override
  void dispose() {
    _sub?.cancel();
    _socket.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: Column(children: [
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(10),
          color: Theme.of(context).colorScheme.surfaceContainerHighest,
          child: Text(
            widget.mode == 'claim'
                ? '이 AI는 게시글의 "주장"을 재현합니다 — 핵심주장·근거·논리구조를 물어보세요.'
                : '이 AI는 작성자의 "글 속 생각"을 재현합니다 (실제 인물이 아닙니다).',
            style: const TextStyle(fontSize: 12),
          ),
        ),
        Expanded(
          child: ListView.builder(
            controller: _scroll,
            padding: const EdgeInsets.all(12),
            itemCount: _messages.length + (_typing ? 1 : 0),
            itemBuilder: (context, i) {
              if (i == _messages.length) {
                return const Padding(
                  padding: EdgeInsets.all(8),
                  child: Align(
                      alignment: Alignment.centerLeft,
                      child: Text('생각 중…',
                          style: TextStyle(color: Colors.grey))),
                );
              }
              final m = _messages[i];
              return Align(
                alignment:
                    m.mine ? Alignment.centerRight : Alignment.centerLeft,
                child: GestureDetector(
                  onLongPress: m.mine
                      ? null
                      : () => _socket.saveNote(m.text),
                  child: Container(
                    margin: const EdgeInsets.symmetric(vertical: 4),
                    padding: const EdgeInsets.all(12),
                    constraints: BoxConstraints(
                        maxWidth:
                            MediaQuery.of(context).size.width * 0.78),
                    decoration: BoxDecoration(
                      color: m.mine
                          ? Theme.of(context).colorScheme.primaryContainer
                          : Theme.of(context)
                              .colorScheme
                              .surfaceContainerHighest,
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (m.label != null && m.label!.isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 4),
                            child: Text(m.label!,
                                style: TextStyle(
                                    fontSize: 10,
                                    color: Theme.of(context)
                                        .colorScheme
                                        .primary)),
                          ),
                        Text(m.text),
                        if (!m.mine)
                          const Padding(
                            padding: EdgeInsets.only(top: 4),
                            child: Text('길게 눌러 글의 맥락으로 저장',
                                style: TextStyle(
                                    fontSize: 10, color: Colors.grey)),
                          ),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
        ),
        SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
            child: Row(children: [
              Expanded(
                child: TextField(
                  controller: _input,
                  onSubmitted: (_) => _send(),
                  decoration: const InputDecoration(
                      hintText: '이 글에 대해 물어보세요…', isDense: true),
                ),
              ),
              IconButton(icon: const Icon(Icons.send), onPressed: _send),
            ]),
          ),
        ),
      ]),
    );
  }
}
