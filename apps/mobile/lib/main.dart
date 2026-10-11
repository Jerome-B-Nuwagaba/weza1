import 'package:flutter/material.dart';

import 'api.dart';
import 'screens/chat.dart';
import 'screens/requests.dart';
import 'theme.dart';

void main() => runApp(const WezaApp());

class WezaApp extends StatelessWidget {
  const WezaApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(title: 'WEZA', debugShowCheckedModeBanner: false, theme: wezaTheme(), home: const HomeShell());
  }
}

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});
  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int tab = 0;
  @override
  Widget build(BuildContext context) {
    final pages = [const StartScreen(), const RequestsScreen()];
    return Scaffold(
      body: SafeArea(child: pages[tab]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: tab,
        onDestinationSelected: (i) => setState(() => tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.chat_bubble_outline), selectedIcon: Icon(Icons.chat_bubble), label: 'Request'),
          NavigationDestination(icon: Icon(Icons.track_changes_outlined), selectedIcon: Icon(Icons.track_changes), label: 'My requests'),
        ],
      ),
    );
  }
}

class StartScreen extends StatefulWidget {
  const StartScreen({super.key});
  @override
  State<StartScreen> createState() => _StartScreenState();
}

class _StartScreenState extends State<StartScreen> {
  final ctrl = TextEditingController();
  bool resumable = false;

  @override
  void initState() {
    super.initState();
    WezaApi.instance().then((api) => setState(() => resumable = api.journeyId != null));
  }

  void open({String? text, bool resume = false}) {
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => ChatScreen(firstText: text, resume: resume))).then((_) async {
      final api = await WezaApi.instance();
      if (mounted) setState(() => resumable = api.journeyId != null);
    });
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 28, 20, 20),
      children: [
        const WezaWordmark(),
        const SizedBox(height: 28),
        Text('Tell WEZA what financing you need.', style: Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w600, height: 1.15)),
        const SizedBox(height: 10),
        const Text('Describe it in your own words. WEZA asks only what matters, shows suitable institutions, and shares your request only with the one you choose.',
            style: TextStyle(color: WezaColors.muted, fontSize: 15, height: 1.4)),
        const SizedBox(height: 20),
        TextField(controller: ctrl, minLines: 2, maxLines: 4, decoration: const InputDecoration(hintText: 'e.g. I need UGX 30 million to expand my pharmacy')),
        const SizedBox(height: 12),
        FilledButton(onPressed: () => open(text: ctrl.text.trim().isEmpty ? null : ctrl.text.trim()), child: const Text('Start')),
        if (resumable) ...[
          const SizedBox(height: 8),
          OutlinedButton(onPressed: () => open(resume: true), child: const Text('Continue my last request')),
        ],
        const SizedBox(height: 24),
        for (final s in const ['I need UGX 30 million to expand my pharmacy', 'I need money for school fees', 'I need 3 million for seeds and fertiliser'])
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: ActionChip(label: Text(s), onPressed: () => open(text: s), backgroundColor: Colors.white, side: const BorderSide(color: WezaColors.line)),
          ),
        const SizedBox(height: 20),
        const Row(children: [
          Icon(Icons.verified_user_outlined, size: 18, color: WezaColors.blue),
          SizedBox(width: 8),
          Expanded(child: Text('WEZA is a marketplace, not a lender. Nothing is shared without your consent.', style: TextStyle(color: WezaColors.muted, fontSize: 13))),
        ]),
      ],
    );
  }
}

class WezaWordmark extends StatelessWidget {
  const WezaWordmark({super.key});
  @override
  Widget build(BuildContext context) {
    return Row(children: [
      Container(
        width: 30,
        height: 30,
        decoration: BoxDecoration(color: WezaColors.blue, borderRadius: BorderRadius.circular(8)),
        alignment: Alignment.center,
        child: const Text('W', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800)),
      ),
      const SizedBox(width: 8),
      const Text('WEZA', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, letterSpacing: 2.5)),
      const SizedBox(width: 4),
      Container(width: 7, height: 7, decoration: const BoxDecoration(color: WezaColors.gold, shape: BoxShape.circle)),
    ]);
  }
}
