import 'package:flutter/material.dart';

import '../core/api.dart';

/// ⑤ 토론 흐름 요약 — 화제(태그)의 대화 축·찬반·쟁점을 한눈에.
/// "찬성 측은? 반대 측은? 쟁점은?"을 댓글 전쟁 없이 즉답.
class DebateScreen extends StatefulWidget {
  const DebateScreen({super.key, required this.tagId, required this.tagName});
  final String tagId;
  final String tagName;

  @override
  State<DebateScreen> createState() => _DebateScreenState();
}

/// 태그 "이름"만 알 때: 이름→id 해석 후 대시보드 진입 (피드의 트렌딩 칩 등).
Future<void> openDebateForTagName(BuildContext context, String name) async {
  try {
    final tags = await Api.instance.searchTags(name);
    final match = tags.where((t) => t['name'] == name).toList();
    final tag = match.isNotEmpty
        ? match.first
        : (tags.isNotEmpty ? tags.first : null);
    if (tag == null) throw Exception('화제를 찾지 못했습니다');
    if (!context.mounted) return;
    await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) =>
            DebateScreen(tagId: tag['id'] as String, tagName: name)));
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
    }
  }
}

class _DebateScreenState extends State<DebateScreen> {
  Map<String, dynamic>? _dash;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await Api.instance.debateDashboard(widget.tagId);
      if (mounted) setState(() => _dash = d);
    } catch (e) {
      if (mounted) setState(() => _error = apiErrorMessage(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _dash;
    return Scaffold(
      appBar: AppBar(title: Text('#${widget.tagName} 토론 흐름')),
      body: _error != null
          ? Center(child: Text(_error!))
          : d == null
              ? const Center(child: CircularProgressIndicator())
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceAround,
                          children: [
                            _Stat(label: '주장', value: d['total_claims']),
                            _Stat(label: '근거', value: d['total_grounds']),
                            _Stat(label: '반박', value: d['total_rebuttals']),
                            _Stat(label: '질문', value: d['total_questions']),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text('대화 축 (쟁점)',
                        style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 6),
                    if ((d['axes'] as List).isEmpty)
                      const Padding(
                        padding: EdgeInsets.all(24),
                        child: Center(
                            child: Text(
                                '아직 정리된 토론 축이 없어요.\n첫 주장을 올려 토론을 시작해 보세요.')),
                      ),
                    for (final a in (d['axes'] as List)
                        .cast<Map<String, dynamic>>())
                      Card(
                        margin: const EdgeInsets.only(bottom: 10),
                        child: Padding(
                          padding: const EdgeInsets.all(14),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text((a['representative_claim'] ?? '') as String,
                                  style: const TextStyle(
                                      fontWeight: FontWeight.w600)),
                              const SizedBox(height: 10),
                              _StanceBar(
                                pro: (a['pro'] as num).toInt(),
                                con: (a['con'] as num).toInt(),
                                neutral: (a['neutral'] as num).toInt(),
                              ),
                              const SizedBox(height: 8),
                              Text(
                                '주장 ${a['claim_count']} · 근거 ${a['ground_count']} · '
                                '반박 ${a['rebuttal_count']} · 최근 7일 +${a['recent_claims']}',
                                style: TextStyle(
                                    fontSize: 12,
                                    color: Theme.of(context)
                                        .colorScheme
                                        .outline),
                              ),
                            ],
                          ),
                        ),
                      ),
                  ],
                ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value});
  final String label;
  final dynamic value;

  @override
  Widget build(BuildContext context) => Column(children: [
        Text('${value ?? 0}',
            style: const TextStyle(
                fontSize: 20, fontWeight: FontWeight.w700)),
        Text(label, style: const TextStyle(fontSize: 12)),
      ]);
}

/// 찬성/반대/중립 분포 막대 — 입장을 한눈에.
class _StanceBar extends StatelessWidget {
  const _StanceBar(
      {required this.pro, required this.con, required this.neutral});
  final int pro;
  final int con;
  final int neutral;

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      ClipRRect(
        borderRadius: BorderRadius.circular(6),
        child: SizedBox(
          height: 10,
          child: Row(children: [
            // flex 0인 Expanded는 레이아웃 오류 — 값이 있는 구간만 그린다.
            if (pro > 0)
              Expanded(
                  flex: pro,
                  child: Container(color: const Color(0xFF1E9E67))),
            if (neutral > 0)
              Expanded(
                  flex: neutral,
                  child: Container(color: Colors.grey.shade700)),
            if (con > 0)
              Expanded(
                  flex: con,
                  child: Container(color: const Color(0xFFC06B3E))),
            if (pro + neutral + con == 0)
              Expanded(child: Container(color: Colors.grey.shade800)),
          ]),
        ),
      ),
      const SizedBox(height: 4),
      Text('찬성 $pro · 중립 $neutral · 반대 $con',
          style: const TextStyle(fontSize: 12)),
    ]);
  }
}
