import 'package:flutter/material.dart';

/// WEZA tokens (blueprint 02 §5.2): light blue for action & trust, gold reserved for meaning.
class WezaColors {
  static const blue = Color(0xFF2E8BC9);
  static const blueDark = Color(0xFF1B5E8C);
  static const blueTint = Color(0xFFEEF7FD);
  static const navy = Color(0xFF0E2A3F);
  static const gold = Color(0xFFC9A227);
  static const goldTint = Color(0xFFFBF3DC);
  static const goldText = Color(0xFF8F7012);
  static const canvas = Color(0xFFF6F9FC);
  static const line = Color(0xFFDCE5EE);
  static const muted = Color(0xFF5B6B7A);
  static const success = Color(0xFF1F8A5B);
  static const danger = Color(0xFFC0392B);
  static const warning = Color(0xFFB7791F);
}

ThemeData wezaTheme() {
  final base = ThemeData(
    useMaterial3: true,
    colorScheme: ColorScheme.fromSeed(seedColor: WezaColors.blue, primary: WezaColors.blue, secondary: WezaColors.gold, surface: Colors.white),
    scaffoldBackgroundColor: WezaColors.canvas,
  );
  return base.copyWith(
    appBarTheme: const AppBarTheme(backgroundColor: Colors.white, foregroundColor: WezaColors.navy, elevation: 0, surfaceTintColor: Colors.white),
    textTheme: base.textTheme.apply(bodyColor: WezaColors.navy, displayColor: WezaColors.navy),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(backgroundColor: WezaColors.blue, minimumSize: const Size(44, 46), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(foregroundColor: WezaColors.blueDark, minimumSize: const Size(44, 44), side: const BorderSide(color: WezaColors.line), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: WezaColors.line)),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: WezaColors.line)),
    ),
    cardTheme: CardThemeData(color: Colors.white, elevation: 0, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12), side: const BorderSide(color: WezaColors.line))),
  );
}
