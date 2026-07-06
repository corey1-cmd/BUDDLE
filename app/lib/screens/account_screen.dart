import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api.dart';
import '../core/config.dart';
import '../providers.dart';

/// 계정 — 로그아웃 + 계정 삭제(Google Play 필수 인앱 경로) + 개인정보처리방침.
class AccountScreen extends ConsumerWidget {
  const AccountScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('계정')),
      body: ListView(
        children: [
          ListTile(
            leading: const Icon(Icons.privacy_tip_outlined),
            title: const Text('개인정보처리방침'),
            trailing: const Icon(Icons.open_in_new, size: 16),
            onTap: () async {
              final url =
                  Uri.parse('${AppConfig.apiBase}/privacy.html');
              await launchUrl(url, mode: LaunchMode.externalApplication);
            },
          ),
          const Divider(height: 1),
          ListTile(
            leading: const Icon(Icons.logout),
            title: const Text('로그아웃'),
            onTap: () async {
              await Api.instance.logout();
              ref.read(authedProvider.notifier).state = false;
            },
          ),
          const Divider(height: 1),
          ListTile(
            leading: Icon(Icons.delete_forever,
                color: Theme.of(context).colorScheme.error),
            title: Text('계정 삭제',
                style: TextStyle(color: Theme.of(context).colorScheme.error)),
            subtitle: const Text('계정과 개인정보가 영구 삭제됩니다.'),
            onTap: () => _confirmDelete(context, ref),
          ),
        ],
      ),
    );
  }

  Future<void> _confirmDelete(BuildContext context, WidgetRef ref) async {
    final password = TextEditingController();
    String? error;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setState) => AlertDialog(
          title: const Text('계정을 삭제할까요?'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                  '되돌릴 수 없습니다. 계정·페르소나·저장·알림이 삭제되고, '
                  '공개 게시글은 작성자 정보가 제거된 채 남습니다.'),
              const SizedBox(height: 12),
              TextField(
                controller: password,
                obscureText: true,
                decoration: InputDecoration(
                  labelText: '비밀번호 확인',
                  border: const OutlineInputBorder(),
                  errorText: error,
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('취소')),
            FilledButton(
              style: FilledButton.styleFrom(
                  backgroundColor: Theme.of(ctx).colorScheme.error),
              onPressed: () async {
                try {
                  await Api.instance.deleteAccount(password.text);
                  if (ctx.mounted) Navigator.pop(ctx, true);
                } catch (e) {
                  setState(() => error = apiErrorMessage(e));
                }
              },
              child: const Text('삭제'),
            ),
          ],
        ),
      ),
    );
    if (ok == true) {
      ref.read(authedProvider.notifier).state = false;
    }
  }
}
