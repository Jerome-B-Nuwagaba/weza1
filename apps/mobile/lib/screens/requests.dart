import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';

/// Status tracker: shows only institution-reported statuses (BRD §33, BR-005).
class RequestsScreen extends StatefulWidget {
  const RequestsScreen({super.key});
  @override
  State<RequestsScreen> createState() => _RequestsScreenState();
}

class _RequestsScreenState extends State<RequestsScreen> {
  List<dynamic>? needs;
  String? error;
  bool signedIn = false;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    final api = await WezaApi.instance();
    signedIn = api.sessionToken != null;
    if (!signedIn) {
      setState(() {});
      return;
    }
    try {
      needs = await api.needs();
      error = null;
    } on ApiException catch (e) {
      error = e.message;
      if (e.status == 401) {
        api.sessionToken = null;
        signedIn = false;
      }
    }
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    if (!signedIn) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text('Start a request and verify your phone to track it here.', textAlign: TextAlign.center, style: TextStyle(color: WezaColors.muted, fontSize: 15)),
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('My requests', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          const Text('Statuses are reported by the institutions you chose.', style: TextStyle(color: WezaColors.muted)),
          const SizedBox(height: 12),
          if (error != null) Text(error!, style: const TextStyle(color: WezaColors.danger)),
          if (needs == null && error == null) const Center(child: Padding(padding: EdgeInsets.all(24), child: CircularProgressIndicator())),
          if (needs != null && needs!.isEmpty) const Text('No requests yet.'),
          for (final n in needs ?? []) _need(Map<String, dynamic>.from(n)),
        ],
      ),
    );
  }

  Widget _need(Map<String, dynamic> n) {
    final opps = (n['opportunities'] as List?) ?? [];
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${money(n['amount'])} · ${n['purpose'] ?? 'Financing request'}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
          if (n['waiting'] != null && n['waiting']['status'] == 'OPTED_IN')
            const Padding(padding: EdgeInsets.only(top: 4), child: Text('In the Waiting Room — we\'ll message you when a suitable institution is available.', style: TextStyle(color: WezaColors.goldText))),
          if (opps.isEmpty) const Padding(padding: EdgeInsets.only(top: 6), child: Text('Not yet shared with any institution.', style: TextStyle(color: WezaColors.muted))),
          for (final o in opps)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: Text('${o['institution']} · ${o['reference']}', style: const TextStyle(fontWeight: FontWeight.w600))),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(color: WezaColors.blueTint, borderRadius: BorderRadius.circular(20)),
                    child: Text('${o['status_label']}', style: const TextStyle(fontSize: 12, color: WezaColors.blueDark)),
                  ),
                ]),
                for (final t in (o['timeline'] as List? ?? [])) Text('• ${t['label']}', style: const TextStyle(color: WezaColors.muted, fontSize: 13)),
                for (final x in (o['outcomes'] as List? ?? []))
                  Text('${x['label']}${x['disbursed_amount'] != null ? ' · ${money(x['disbursed_amount'])}' : ''} — reported by ${x['reported_by']}', style: const TextStyle(fontSize: 13, fontStyle: FontStyle.italic)),
                if (o['can_withdraw'] == true)
                  TextButton(
                    onPressed: () async {
                      final ok = await showDialog<bool>(
                        context: context,
                        builder: (c) => AlertDialog(
                          title: const Text('Withdraw this request?'),
                          content: const Text('The institution will be told you no longer wish to proceed, and WEZA will stop sharing your details.'),
                          actions: [TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Withdraw'))],
                        ),
                      );
                      if (ok == true) {
                        await (await WezaApi.instance()).withdraw(o['id']);
                        load();
                      }
                    },
                    child: const Text('Withdraw request'),
                  ),
              ]),
            ),
        ]),
      ),
    );
  }
}
