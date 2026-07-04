// 로그인 화면이 뜨는지 확인하는 스모크 테스트.
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:buddle_app/screens/login_screen.dart';
import 'package:flutter/material.dart';

void main() {
  testWidgets('login screen renders', (tester) async {
    await tester.pumpWidget(const ProviderScope(
        child: MaterialApp(home: LoginScreen())));
    expect(find.text('buddle'), findsOneWidget);
  });
}
