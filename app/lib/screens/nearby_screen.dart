import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';

import '../core/api.dart';
import '../providers.dart';

/// 위치 매칭 — "지역을 바꾸고, 도시를 바꾸고, 나라를 바꾸고, 세계를 바꾼다".
///
/// 10단계 반지름 계층(1km~1000km). 서버가 로지스틱(1–6) + C¹ 지수꼬리(7–10)
/// 가중으로 랭킹한 결과를 tier 라벨로 보여준다. 위치 공유는 opt-in이며,
/// 상대 좌표는 항상 일반화(coarsened)되어 내려온다.
class NearbyScreen extends ConsumerStatefulWidget {
  const NearbyScreen({super.key});

  @override
  ConsumerState<NearbyScreen> createState() => _NearbyScreenState();
}

/// tier(1~10) → 사용자에게 보여줄 계층 이름.
const tierLabels = {
  1: '이웃 (1km)',
  2: '동네 (5km)',
  3: '우리 지역 (10km)',
  4: '구·군 (30km)',
  5: '도시 (50km)',
  6: '광역권 (100km)',
  7: '지방 (200km)',
  8: '전국 (300km)',
  9: '나라 (500km)',
  10: '세계 (1000km)',
};

class _NearbyScreenState extends ConsumerState<NearbyScreen> {
  bool _sharing = false;
  bool _busy = false;
  String? _status;
  List<Map<String, dynamic>> _matches = const [];

  Future<void> _enableAndMatch() async {
    setState(() {
      _busy = true;
      _status = null;
    });
    try {
      // 1) 위치 권한 + 현재 좌표 (opt-in: 버튼을 눌렀을 때만)
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        setState(() => _status = '위치 권한이 필요해요. 설정에서 허용해 주세요.');
        return;
      }
      final pos = await Geolocator.getCurrentPosition();

      // 2) 내 페르소나에 위치 등록(공유 on) 후 근접 매칭 조회
      final persona = await ref.read(defaultPersonaProvider.future);
      final personaId = persona['id'] as String;
      await Api.instance.setLocation(personaId,
          lat: pos.latitude, lon: pos.longitude, sharing: true);
      final matches = await Api.instance.nearby(personaId);
      setState(() {
        _sharing = true;
        _matches = matches;
        _status = matches.isEmpty
            ? '아직 근처에 참여자가 없어요 — 첫 번째가 되어보세요!'
            : null;
      });
    } catch (e) {
      setState(() => _status = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _disable() async {
    setState(() => _busy = true);
    try {
      final persona = await ref.read(defaultPersonaProvider.future);
      await Api.instance
          .setLocation(persona['id'] as String, sharing: false);
      setState(() {
        _sharing = false;
        _matches = const [];
        _status = '위치 공유를 껐어요.';
      });
    } catch (e) {
      setState(() => _status = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('근처의 대화')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('지역이 도시를, 도시가 나라를, 나라가 세계를 바꿉니다',
                      style: TextStyle(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 6),
                  const Text(
                    '가까운 사람과 화제가 더 잘 통해요. 위치 공유는 선택이며, '
                    '다른 사람에게는 대략적인 위치(약 1km 격자)만 보입니다.',
                    style: TextStyle(fontSize: 13),
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: _sharing
                        ? OutlinedButton(
                            onPressed: _busy ? null : _disable,
                            child: const Text('위치 공유 끄기'))
                        : FilledButton.icon(
                            icon: const Icon(Icons.my_location, size: 18),
                            onPressed: _busy ? null : _enableAndMatch,
                            label: Text(
                                _busy ? '찾는 중…' : '내 위치로 근처 참여자 찾기'),
                          ),
                  ),
                ],
              ),
            ),
          ),
          if (_status != null)
            Padding(
              padding: const EdgeInsets.all(12),
              child:
                  Center(child: Text(_status!, textAlign: TextAlign.center)),
            ),
          for (final m in _matches) _MatchTile(match: m),
        ],
      ),
    );
  }
}

class _MatchTile extends StatelessWidget {
  const _MatchTile({required this.match});
  final Map<String, dynamic> match;

  @override
  Widget build(BuildContext context) {
    final tier = (match['tier'] as num?)?.toInt() ?? 0;
    final graded = (match['graded_affinity'] as num?)?.toDouble() ?? 0;
    final name = (match['name'] ?? '익명') as String;
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        leading: CircleAvatar(child: Text(name.characters.first)),
        title: Text(name),
        subtitle: Text(
            '${tierLabels[tier] ?? '범위 밖'} · ${match['distance_km']}km'),
        trailing: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text('${(graded * 100).round()}%',
                style: const TextStyle(
                    fontWeight: FontWeight.w700, fontSize: 15)),
            const Text('매칭 가중', style: TextStyle(fontSize: 10)),
          ],
        ),
      ),
    );
  }
}
