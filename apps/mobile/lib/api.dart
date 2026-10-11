import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// WEZA core API base URL. Override at build time:
/// flutter build apk --dart-define=WEZA_API_URL=https://your-api.onrender.com
const String apiBase = String.fromEnvironment('WEZA_API_URL', defaultValue: 'http://10.0.2.2:8000');

class ApiException implements Exception {
  ApiException(this.status, this.code, this.message, [this.correlationId]);
  final int status;
  final String code;
  final String message;
  final String? correlationId;
  @override
  String toString() => message;
}

/// Thin client over the same /api/v1 contract the web app uses (TSD §5: web and mobile share backend services).
class WezaApi {
  WezaApi._(this._prefs);
  final SharedPreferences _prefs;
  static WezaApi? _instance;

  static Future<WezaApi> instance() async {
    _instance ??= WezaApi._(await SharedPreferences.getInstance());
    return _instance!;
  }

  String? get sessionToken => _prefs.getString('customer_session');
  set sessionToken(String? v) => v == null ? _prefs.remove('customer_session') : _prefs.setString('customer_session', v);
  String? get journeyId => _prefs.getString('journey_id');
  String? get journeyToken => _prefs.getString('journey_token');

  Future<void> saveJourney(String id, String token) async {
    await _prefs.setString('journey_id', id);
    await _prefs.setString('journey_token', token);
  }

  Future<void> clearJourney() async {
    await _prefs.remove('journey_id');
    await _prefs.remove('journey_token');
  }

  Future<void> signOut() async {
    await clearJourney();
    await _prefs.remove('customer_session');
  }

  Future<dynamic> _send(String method, String path, {Object? body, Map<String, String>? headers, bool auth = false}) async {
    final h = <String, String>{'Content-Type': 'application/json', ...?headers};
    if (auth && sessionToken != null) h['Authorization'] = 'Bearer $sessionToken';
    final uri = Uri.parse('$apiBase/api/v1$path');
    late http.Response r;
    try {
      r = method == 'GET'
          ? await http.get(uri, headers: h).timeout(const Duration(seconds: 70))
          : await http.post(uri, headers: h, body: jsonEncode(body ?? {})).timeout(const Duration(seconds: 70));
    } catch (_) {
      throw ApiException(0, 'NETWORK', 'Can\'t reach WEZA right now. Check your connection and try again.');
    }
    final data = r.body.isEmpty ? null : jsonDecode(utf8.decode(r.bodyBytes));
    if (r.statusCode >= 400) {
      final e = (data is Map ? data['error'] : null) ?? {};
      throw ApiException(r.statusCode, e['code'] ?? 'HTTP_ERROR', e['message'] ?? 'Something went wrong.', e['correlation_id']);
    }
    return data;
  }

  Future<Map<String, dynamic>> startJourney(String? text) async {
    final r = await _send('POST', '/journeys', body: {'channel': 'app', 'text': text, 'src': 'app'}, auth: true);
    await saveJourney(r['journey_id'], r['token']);
    _absorb(r);
    return Map<String, dynamic>.from(r);
  }

  Future<Map<String, dynamic>> getJourney() async {
    final r = await _send('GET', '/journeys/$journeyId', headers: {'X-Journey-Token': journeyToken!});
    return Map<String, dynamic>.from(r);
  }

  Future<Map<String, dynamic>> send(Map<String, dynamic> payload) async {
    final r = await _send('POST', '/journeys/$journeyId/messages',
        body: {...payload, 'message_id': 'app:${DateTime.now().microsecondsSinceEpoch}'},
        headers: {'X-Journey-Token': journeyToken!});
    _absorb(r);
    return Map<String, dynamic>.from(r);
  }

  void _absorb(dynamic r) {
    for (final o in (r['outputs'] as List? ?? [])) {
      if (o['type'] == 'card' && o['card'] == 'session') sessionToken = o['data']['token'];
    }
  }

  Future<List<dynamic>> needs() async => (await _send('GET', '/me/needs', auth: true))['needs'] as List;
  Future<Map<String, dynamic>> profile() async => Map<String, dynamic>.from(await _send('GET', '/me/profile', auth: true));
  Future<List<dynamic>> notifications() async => (await _send('GET', '/me/notifications', auth: true))['notifications'] as List;
  Future<void> withdraw(String oppId) async => _send('POST', '/me/opportunities/$oppId/withdraw', auth: true);
}

String _trim(String s) => s.contains('.') ? s.replaceAll(RegExp(r'0+$'), '').replaceAll(RegExp(r'\.$'), '') : s;

String money(num? v) {
  if (v == null) return "—";
  final a = v.abs();
  if (a >= 1e9) return "UGX ${_trim((a / 1e9).toStringAsFixed(a >= 1e10 ? 1 : 2))}B";
  if (a >= 1e6) return "UGX ${_trim((a / 1e6).toStringAsFixed(a >= 1e8 ? 0 : 1))}M";
  if (a >= 1e3) return "UGX ${(a / 1e3).round()}K";
  return "UGX ${a.round()}";
}
