import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';

/// Customer conversation — drives the same server-side journey graph as web and WhatsApp.
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, this.firstText, this.resume = false});
  final String? firstText;
  final bool resume;
  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  WezaApi? api;
  Map<String, dynamic>? view;
  List<dynamic> outputs = [];
  bool busy = true;
  String? error;
  final input = TextEditingController();
  final scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    api = await WezaApi.instance();
    try {
      if (widget.resume && api!.journeyId != null) {
        view = await api!.getJourney();
      } else {
        final r = await api!.startJourney(widget.firstText);
        view = r;
        outputs = r['outputs'] ?? [];
      }
    } on ApiException catch (e) {
      error = e.message;
    }
    if (mounted) setState(() => busy = false);
    _toBottom();
  }

  Future<void> send(Map<String, dynamic> payload) async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final r = await api!.send(payload);
      view = r;
      outputs = r['outputs'] ?? [];
    } on ApiException catch (e) {
      error = e.message;
    }
    if (mounted) setState(() => busy = false);
    _toBottom();
  }

  void _toBottom() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (scroll.hasClients) scroll.animateTo(scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
      });

  @override
  Widget build(BuildContext context) {
    final messages = (view?['messages'] as List?) ?? [];
    final qrs = (view?['quick_replies'] as List?) ?? [];
    final lastIdx = <String, int>{};
    for (var i = 0; i < messages.length; i++) {
      if (messages[i]['type'] == 'card') lastIdx[messages[i]['card']] = i;
    }
    final devCode = outputs.firstWhere((o) => o['card'] == 'otp_input', orElse: () => null)?['data']?['dev_code'];
    final ended = view != null && (view!['status'] == 'COMPLETED' || view!['status'] == 'EXPIRED');
    return Scaffold(
      appBar: AppBar(title: const Text('Your request'), actions: [
        IconButton(
          tooltip: 'Start a new request',
          icon: const Icon(Icons.refresh),
          onPressed: () async {
            await api?.clearJourney();
            if (context.mounted) Navigator.of(context).pop();
          },
        ),
      ]),
      body: Column(children: [
        Expanded(
          child: view == null && busy
              ? const Center(child: CircularProgressIndicator())
              : ListView.builder(
                  controller: scroll,
                  padding: const EdgeInsets.all(14),
                  itemCount: messages.length + (busy ? 1 : 0) + (error != null ? 1 : 0),
                  itemBuilder: (_, i) {
                    if (i == messages.length && busy) return const Padding(padding: EdgeInsets.all(8), child: Text('…', style: TextStyle(fontSize: 22, color: WezaColors.muted)));
                    if (i >= messages.length) return _banner(error!, WezaColors.danger);
                    final m = Map<String, dynamic>.from(messages[i]);
                    final active = m['type'] == 'card' && lastIdx[m['card']] == i && i >= messages.length - 3;
                    return _message(m, active, devCode);
                  },
                ),
        ),
        if (qrs.isNotEmpty && !busy)
          SizedBox(
            height: 48,
            child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 10), children: [
              for (final q in qrs)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
                  child: ActionChip(
                    label: Text(q['label']),
                    backgroundColor: WezaColors.blueTint,
                    side: const BorderSide(color: WezaColors.blue),
                    onPressed: () => send({'action': q['action'], 'value': q['value'], 'label': q['label'], if (q['action'] == 'answer') 'text': q['value']}),
                  ),
                ),
            ]),
          ),
        SafeArea(
          top: false,
          child: Container(
            color: Colors.white,
            padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
            child: ended
                ? const Padding(padding: EdgeInsets.all(8), child: Text('This conversation has ended. Start a new request any time.'))
                : Row(children: [
                    Expanded(
                      child: TextField(
                        controller: input,
                        minLines: 1,
                        maxLines: 4,
                        textInputAction: TextInputAction.send,
                        decoration: const InputDecoration(hintText: 'Type your reply…'),
                        onSubmitted: (_) => _submit(),
                      ),
                    ),
                    const SizedBox(width: 6),
                    IconButton.filled(onPressed: busy ? null : _submit, icon: const Icon(Icons.arrow_upward), tooltip: 'Send'),
                  ]),
          ),
        ),
      ]),
    );
  }

  void _submit() {
    final t = input.text.trim();
    if (t.isEmpty || busy) return;
    input.clear();
    send({'text': t});
  }

  Widget _banner(String text, Color c) => Container(
        margin: const EdgeInsets.symmetric(vertical: 6),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: c.withValues(alpha: 0.08), borderRadius: BorderRadius.circular(10), border: Border.all(color: c.withValues(alpha: 0.3))),
        child: Text(text, style: TextStyle(color: c)),
      );

  Widget _bubble(String text, bool out, {String? hint}) => Align(
        alignment: out ? Alignment.centerLeft : Alignment.centerRight,
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 4),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.82),
          decoration: BoxDecoration(
            color: out ? Colors.white : WezaColors.blue,
            border: out ? Border.all(color: WezaColors.line) : null,
            borderRadius: BorderRadius.circular(16),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(text, style: TextStyle(color: out ? WezaColors.navy : Colors.white, fontSize: 15, height: 1.35)),
            if (hint != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(hint, style: const TextStyle(color: WezaColors.muted, fontSize: 13))),
          ]),
        ),
      );

  Widget _message(Map<String, dynamic> m, bool active, String? devCode) {
    if (m['direction'] == 'IN') return _bubble('${m['text'] ?? m['label'] ?? m['action'] ?? ''}', false);
    if (m['type'] == 'text') return _bubble('${m['text']}', true, hint: m['hint']);
    final d = Map<String, dynamic>.from(m['data'] ?? {});
    switch (m['card']) {
      case 'understanding':
        return _card(
          tint: WezaColors.blueTint,
          title: 'What I understood',
          child: Column(children: [
            for (final row in [['Amount', d['amount']], ['Purpose', d['purpose']], ['You are', d['customer_type']], ['Sector', d['sector']], ['District', d['district']]])
              if (row[1] != null) _kv(row[0], '${row[1]}'),
          ]),
        );
      case 'otp_input':
        if (!active) return const SizedBox.shrink();
        return Column(children: [
          if (devCode != null) _banner('Test mode — SMS isn\'t connected yet. Your code is $devCode', WezaColors.goldText),
          _inlineInput('6-digit code', TextInputType.number, (v) => send({'text': v})),
        ]);
      case 'phone_input':
        if (!active) return const SizedBox.shrink();
        return _inlineInput('Mobile number, e.g. 0772 123 456', TextInputType.phone, (v) => send({'text': v}));
      case 'options':
        return Column(children: [for (final o in (d['options'] as List? ?? [])) _option(Map<String, dynamic>.from(o), active)]);
      case 'consent':
        return _card(
          title: 'Consent · version ${d['version']}',
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${d['title']}', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 16)),
            const SizedBox(height: 6),
            Text('${d['text']}', style: const TextStyle(height: 1.4)),
            const SizedBox(height: 8),
            const Text('Shared:', style: TextStyle(fontWeight: FontWeight.w600)),
            for (final c in (d['categories'] as List? ?? [])) Text('• ${c['label']}'),
            if (active) ...[
              const SizedBox(height: 10),
              FilledButton(onPressed: busy ? null : () => send({'action': 'agree', 'value': d['template_id'], 'label': 'I agree'}), child: Text('I agree — share with ${d['institution']}')),
              TextButton(onPressed: () => send({'action': 'decline', 'label': 'Not now'}), child: const Text('Not now')),
            ],
          ]),
        );
      case 'submitted':
        return _card(
          tint: const Color(0xFFE6F4ED),
          title: 'Request shared',
          child: Text('${d['reference']} with ${d['institution']}. Expected first contact within ${d['expected_contact_hours']} hours.', style: const TextStyle(fontSize: 15)),
        );
      case 'documents_needed':
        return _card(
          title: 'Documents needed',
          child: Text('Please upload: ${(d['documents'] as List? ?? []).map((x) => x['label']).join(', ')}. Use WEZA on the web (My documents) to upload securely.'),
        );
      default:
        return const SizedBox.shrink();
    }
  }

  Widget _option(Map<String, dynamic> o, bool active) {
    final gold = (o['score'] as num) >= 90;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 5),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12), side: BorderSide(color: gold ? WezaColors.gold : WezaColors.line)),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            CircleAvatar(
              radius: 21,
              backgroundColor: gold ? WezaColors.goldTint : WezaColors.blueTint,
              child: Text('${o['score']}', style: TextStyle(fontWeight: FontWeight.w700, color: gold ? WezaColors.goldText : WezaColors.blueDark)),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${o['institution']}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                Text('${o['product']}'),
              ]),
            ),
          ]),
          const SizedBox(height: 6),
          Text('${o['amount_range']} · ${o['tenor']} · ${o['pricing']}', style: const TextStyle(color: WezaColors.muted, fontSize: 13)),
          const SizedBox(height: 6),
          Wrap(spacing: 6, runSpacing: 4, children: [
            for (final w in (o['why'] as List).take(4))
              Chip(label: Text('✓ $w', style: const TextStyle(fontSize: 12, color: WezaColors.success)), visualDensity: VisualDensity.compact, side: BorderSide.none, backgroundColor: const Color(0xFFE6F4ED)),
          ]),
          if (o['readiness'] != 'READY') Text('Needs: ${(o['outstanding'] as List).join('; ')}', style: const TextStyle(color: WezaColors.warning, fontSize: 13)),
          if (active && o['readiness'] == 'READY')
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: FilledButton(onPressed: busy ? null : () => send({'action': 'select', 'value': o['match_id'], 'label': 'Choose ${o['institution']}'}), child: const Text('Choose this option')),
            ),
          const SizedBox(height: 4),
          const Text('A match is not a loan approval.', style: TextStyle(color: WezaColors.muted, fontSize: 11)),
        ]),
      ),
    );
  }

  Widget _card({required String title, required Widget child, Color? tint}) => Container(
        margin: const EdgeInsets.symmetric(vertical: 6),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(color: tint ?? Colors.white, borderRadius: BorderRadius.circular(12), border: Border.all(color: WezaColors.line)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title.toUpperCase(), style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 0.8, color: WezaColors.blueDark)),
          const SizedBox(height: 6),
          child,
        ]),
      );

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          Expanded(child: Text(k, style: const TextStyle(color: WezaColors.muted))),
          Flexible(child: Text(v, textAlign: TextAlign.right, style: const TextStyle(fontWeight: FontWeight.w600))),
        ]),
      );

  Widget _inlineInput(String hint, TextInputType type, void Function(String) onSubmit) {
    final c = TextEditingController();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(children: [
        Expanded(child: TextField(controller: c, keyboardType: type, decoration: InputDecoration(hintText: hint), onSubmitted: onSubmit)),
        const SizedBox(width: 8),
        FilledButton(onPressed: busy ? null : () => onSubmit(c.text.trim()), child: const Text('Send')),
      ]),
    );
  }
}
