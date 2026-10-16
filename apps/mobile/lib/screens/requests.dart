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

  /// Indicative terms as reported by the institution — never presented as a WEZA offer.
  Widget _terms(Map<String, dynamic> t) {
    final parts = <String>[
      if (t['tenor_months'] != null) '${t['tenor_months']} months',
      if (t['interest_rate'] != null) '${t['interest_rate']}% ${t['rate_period'] == 'ANNUAL' ? 'per year' : 'per month'}',
      if (t['monthly_repayment'] != null) '${money(t['monthly_repayment'])}/month',
      if (t['fees'] != null) 'fees ${money(t['fees'])}',
    ];
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Indicative terms${parts.isEmpty ? '' : ': ${parts.join(' · ')}'}', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
        if (t['conditions'] != null) Text('Conditions: ${t['conditions']}', style: const TextStyle(color: WezaColors.muted, fontSize: 13)),
        if (t['valid_until'] != null)
          Text('${t['expired'] == true ? 'Expired' : 'Valid until'} ${t['valid_until']}', style: TextStyle(color: t['expired'] == true ? WezaColors.danger : WezaColors.muted, fontSize: 13)),
        Text('${t['label']}', style: const TextStyle(color: WezaColors.muted, fontSize: 12, fontStyle: FontStyle.italic)),
      ]),
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
                for (final r in (o['info_requests'] as List? ?? []))
                  if (r['status'] == 'OPEN') _InfoRequestTile(r: Map<String, dynamic>.from(r), institution: '${o['institution']}', onDone: load)
                  else if (r['status'] == 'FULFILLED')
                    Text('You answered ${o['institution']}\'s request', style: const TextStyle(color: WezaColors.muted, fontSize: 13)),
                for (final x in (o['outcomes'] as List? ?? [])) ...[
                  Text('${x['label']}${x['disbursed_amount'] != null ? ' · ${money(x['disbursed_amount'])}' : ''} — reported by ${x['reported_by']}', style: const TextStyle(fontSize: 13, fontStyle: FontStyle.italic)),
                  if (x['terms'] != null) _terms(Map<String, dynamic>.from(x['terms'])),
                ],
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

/// An institution's request for a document or an answer. Answering is the customer's choice.
class _InfoRequestTile extends StatefulWidget {
  const _InfoRequestTile({required this.r, required this.institution, required this.onDone});
  final Map<String, dynamic> r;
  final String institution;
  final Future<void> Function() onDone;
  @override
  State<_InfoRequestTile> createState() => _InfoRequestTileState();
}

class _InfoRequestTileState extends State<_InfoRequestTile> {
  final answer = TextEditingController();
  List<dynamic> docs = [];
  bool busy = false;
  String? error;

  bool get isDoc => widget.r['kind'] == 'DOCUMENT';

  @override
  void initState() {
    super.initState();
    if (isDoc) {
      WezaApi.instance().then((api) => api.documents()).then((all) {
        if (mounted) {
          setState(() => docs = all.where((d) => d['state'] == 'STORED' && d['doc_type'] == widget.r['doc_type']).toList());
        }
      }).catchError((_) {});
    }
  }

  @override
  void dispose() {
    answer.dispose();
    super.dispose();
  }

  Future<void> respond({String? text, String? documentId}) async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await (await WezaApi.instance()).respondInfoRequest(widget.r['id'], text: text, documentId: documentId);
      await widget.onDone();
    } on ApiException catch (e) {
      if (mounted) setState(() => error = e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = widget.r;
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(color: WezaColors.blueTint, borderRadius: BorderRadius.circular(10)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${widget.institution} asks: ${isDoc ? r['doc_label'] : 'a question'}', style: const TextStyle(fontWeight: FontWeight.w600)),
        const SizedBox(height: 2),
        Text('${r['message']}'),
        if (r['fact_label'] != null)
          Text('Your answer will also update your profile (${r['fact_label']}).', style: const TextStyle(color: WezaColors.muted, fontSize: 12)),
        const SizedBox(height: 6),
        if (!isDoc) ...[
          TextField(controller: answer, maxLines: 3, minLines: 1, maxLength: 2000, decoration: const InputDecoration(hintText: 'Your answer')),
          FilledButton(onPressed: busy ? null : () => answer.text.trim().isEmpty ? null : respond(text: answer.text.trim()), child: const Text('Send')),
        ] else if (docs.isEmpty)
          const Text('Upload this document on the WEZA website under My documents, then send it from here.', style: TextStyle(color: WezaColors.muted, fontSize: 13))
        else
          Wrap(spacing: 8, children: [
            for (final d in docs) OutlinedButton(onPressed: busy ? null : () => respond(documentId: d['id']), child: Text('Send ${d['filename']}')),
          ]),
        const Text('WEZA and institutions will never ask for your PIN, password or one-time codes.', style: TextStyle(color: WezaColors.muted, fontSize: 12)),
        if (error != null) Text(error!, style: const TextStyle(color: WezaColors.danger)),
      ]),
    );
  }
}
