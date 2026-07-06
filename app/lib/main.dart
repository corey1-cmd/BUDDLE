import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/token_store.dart';
import 'providers.dart';
import 'screens/login_screen.dart';
import 'screens/shell.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await TokenStore.instance.load();
  runApp(const ProviderScope(child: BuddleApp()));
}

class BuddleApp extends ConsumerWidget {
  const BuddleApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authed = ref.watch(authedProvider);
    // Premium-tech "cosmic glass": deep blue-black ground, blue-violet
    // accent, tight tracking — mirrors web/buddle.css tokens.
    final base = ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        seedColor: const Color(0xFF7C82F7),
        brightness: Brightness.dark,
      ).copyWith(
        primary: const Color(0xFFA6ACFF),
        surface: const Color(0xFF07080E),
      ),
      scaffoldBackgroundColor: const Color(0xFF07080E),
      fontFamilyFallback: const ['NotoSansKR', 'sans-serif'],
    );
    final t = base.textTheme;
    final tight = t.copyWith(
      displayLarge: t.displayLarge?.copyWith(letterSpacing: -1.0),
      displayMedium: t.displayMedium?.copyWith(letterSpacing: -0.8),
      displaySmall: t.displaySmall?.copyWith(letterSpacing: -0.6),
      headlineLarge: t.headlineLarge?.copyWith(letterSpacing: -0.6),
      headlineMedium: t.headlineMedium?.copyWith(letterSpacing: -0.5),
      headlineSmall: t.headlineSmall?.copyWith(letterSpacing: -0.4),
      titleLarge: t.titleLarge?.copyWith(letterSpacing: -0.4),
      titleMedium: t.titleMedium?.copyWith(letterSpacing: -0.2),
      titleSmall: t.titleSmall?.copyWith(letterSpacing: -0.1),
      bodyLarge: t.bodyLarge?.copyWith(letterSpacing: -0.2),
      bodyMedium: t.bodyMedium?.copyWith(letterSpacing: -0.15),
      bodySmall: t.bodySmall?.copyWith(letterSpacing: -0.1),
      labelLarge: t.labelLarge?.copyWith(letterSpacing: 0),
    );
    return MaterialApp(
      title: 'buddle',
      debugShowCheckedModeBanner: false,
      theme: base.copyWith(textTheme: tight),
      home: authed ? const ShellScreen() : const LoginScreen(),
    );
  }
}
