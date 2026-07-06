import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import 'config.dart';
import 'token_store.dart';

/// 서버 WS 프레임 (dialogue / argument 공통 소비 형태).
class WsFrame {
  WsFrame(this.type, this.data);
  final String type;
  final Map<String, dynamic> data;

  String get content => (data['content'] ?? '') as String;
  bool get typingStart => type == 'typing' && data['state'] != 'stop';
}

/// buddle WebSocket 세션 — 첫 프레임 토큰 인증(쿼리스트링 금지, 보안 설계).
class BuddleSocket {
  BuddleSocket._(this._channel, this._authFrame);

  final WebSocketChannel _channel;
  final Map<String, dynamic> _authFrame;
  final _frames = StreamController<WsFrame>.broadcast();
  bool _closed = false;

  Stream<WsFrame> get frames => _frames.stream;

  /// 대화형 글쓰기(③): 페르소나 대화 소켓.
  /// 인증 프레임 = {"type":"auth","token":...}
  static BuddleSocket dialogue(String personaId) {
    final ch = WebSocketChannel.connect(
        Uri.parse('${AppConfig.wsBase}/v1/ws/dialogue/$personaId'));
    return BuddleSocket._(
        ch, {'type': 'auth', 'token': TokenStore.instance.access})
      .._start();
  }

  /// 게시글 이해 AI(④): mode=claim(이 글의 주장) | author(이 사람의 생각).
  /// 인증 프레임 = {"token":...}
  static BuddleSocket argument(String postId, {String mode = 'claim'}) {
    final ch = WebSocketChannel.connect(
        Uri.parse('${AppConfig.wsBase}/v1/ws/argument/$postId?mode=$mode'));
    return BuddleSocket._(ch, {'token': TokenStore.instance.access})
      .._start();
  }

  void _start() {
    _channel.sink.add(jsonEncode(_authFrame));
    _channel.stream.listen((raw) {
      try {
        final m = jsonDecode(raw as String);
        if (m is Map<String, dynamic>) {
          _frames.add(WsFrame((m['type'] ?? '') as String, m));
        }
      } catch (_) {/* 비정형 프레임 무시 */}
    }, onDone: () {
      if (!_closed) {
        _frames.add(WsFrame('closed', const {}));
      }
    }, onError: (Object _) {
      _frames.add(WsFrame('error',
          const {'code': 'SOCKET', 'message': '연결이 끊어졌습니다.'}));
    });
  }

  void sendUserMessage(String content, {String? sessionId}) {
    _channel.sink.add(jsonEncode({
      'type': 'user_message',
      'content': content,
      if (sessionId != null) 'session_id': sessionId,
    }));
  }

  /// 이해 AI 대화 중 유용한 맥락을 글에 저장(부가 맥락 노트).
  void saveNote(String content, {String kind = 'context'}) {
    _channel.sink.add(jsonEncode(
        {'type': 'save_note', 'content': content, 'note_kind': kind}));
  }

  void close() {
    _closed = true;
    _frames.close();
    _channel.sink.close();
  }
}
