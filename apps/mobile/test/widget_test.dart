import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:weza_mobile/api.dart';
import 'package:weza_mobile/main.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('start screen shows the WEZA proposition and starts a request', (tester) async {
    tester.view.physicalSize = const Size(1080, 2600);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(const WezaApp());
    await tester.pumpAndSettle();
    expect(find.text('Tell WEZA what financing you need.'), findsOneWidget);
    expect(find.text('Start'), findsOneWidget);
    expect(find.textContaining('not a lender'), findsOneWidget);
  });

  testWidgets('my requests asks unverified users to start first', (tester) async {
    await tester.pumpWidget(const WezaApp());
    await tester.pumpAndSettle();
    await tester.tap(find.text('My requests'));
    await tester.pumpAndSettle();
    expect(find.textContaining('verify your phone'), findsOneWidget);
  });

  test('money formatting matches the web app', () {
    expect(money(30000000), 'UGX 30M');
    expect(money(1500000), 'UGX 1.5M');
    expect(money(2500000000), 'UGX 2.5B');
    expect(money(450000), 'UGX 450K');
    expect(money(null), '—');
  });
}
