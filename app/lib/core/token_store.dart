import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// JWT 토큰 보관소 — OS 보안 저장소(Keystore) 사용. 평문 프리퍼런스 금지.
class TokenStore {
  TokenStore._();
  static final TokenStore instance = TokenStore._();

  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );
  static const _kAccess = 'buddle.access';
  static const _kRefresh = 'buddle.refresh';

  String? _access;
  String? _refresh;

  String? get access => _access;
  String? get refresh => _refresh;
  bool get isAuthed => _access != null;

  Future<void> load() async {
    _access = await _storage.read(key: _kAccess);
    _refresh = await _storage.read(key: _kRefresh);
  }

  Future<void> save(String access, String refresh) async {
    _access = access;
    _refresh = refresh;
    await _storage.write(key: _kAccess, value: access);
    await _storage.write(key: _kRefresh, value: refresh);
  }

  Future<void> clear() async {
    _access = null;
    _refresh = null;
    await _storage.delete(key: _kAccess);
    await _storage.delete(key: _kRefresh);
  }
}
