import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'i18n.dart';

/// The phone version of the desktop bot's window (roguebot/ui.py): options, Start/Stop, status and log.
/// The bot itself runs in Kotlin (android/bot, android/app): see Engine.kt.
const version = '0.2.0';
const damageTypes = ['ice', 'lightning', 'fire', 'shuriken', 'venom', 'bleed'];
const engine = MethodChannel('roguebot/engine');
const events = EventChannel('roguebot/events');

void main() => runApp(const BotApp());

class BotApp extends StatelessWidget {
  const BotApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Rogue Legend Bot',
        theme: ThemeData(colorSchemeSeed: const Color(0xFF7B3FA0), useMaterial3: true),
        darkTheme: ThemeData(colorSchemeSeed: const Color(0xFF7B3FA0), brightness: Brightness.dark, useMaterial3: true),
        home: const BotPage(),
      );
}

/// Every option the user sets, saved between sessions (like data/settings.json on the desktop).
class Options {
  String lang = 'es', mode = 'normal', source = 'latest', level = '1', nature = 'physical', supportEvery = '3';
  bool repeat = false, full = false, loop = false, ads = false, support = false;
  List<String> order = [...damageTypes];

  Map<String, Object> toJson() => {
        'lang': lang, 'mode': mode, 'source': source, 'level': level, 'nature': nature, 'support_every': supportEvery,
        'repeat': repeat, 'full': full, 'loop': loop, 'ads': ads, 'support': support, 'damage_order': order,
      };

  /// Last session's choices; anything missing or invalid keeps its default.
  void restore(Map<String, dynamic> s) {
    T? pick<T>(String key, bool Function(T) ok) => s[key] is T && ok(s[key] as T) ? s[key] as T : null;
    lang = pick<String>('lang', uiLanguages.containsKey) ?? lang;
    mode = pick<String>('mode', ['normal', 'elite'].contains) ?? mode;
    source = pick<String>('source', ['latest', 'beaten', 'pending', 'stars'].contains) ?? source;
    nature = pick<String>('nature', ['physical', 'magic'].contains) ?? nature;
    level = pick<String>('level', (v) => int.tryParse(v) != null) ?? level;
    supportEvery = pick<String>('support_every', (v) => int.tryParse(v) != null) ?? supportEvery;
    repeat = pick<bool>('repeat', (_) => true) ?? repeat;
    full = pick<bool>('full', (_) => true) ?? full;
    loop = pick<bool>('loop', (_) => true) ?? loop;
    ads = pick<bool>('ads', (_) => true) ?? ads;
    support = pick<bool>('support', (_) => true) ?? support;
    final saved = (s['damage_order'] as List?)?.cast<String>();
    if (saved != null && ([...saved]..sort()).join() == ([...damageTypes]..sort()).join()) order = saved;
  }
}

class BotPage extends StatefulWidget {
  const BotPage({super.key});

  @override
  State<BotPage> createState() => _BotPageState();
}

class _BotPageState extends State<BotPage> with WidgetsBindingObserver {
  final options = Options();
  final log = <String>[];
  final logScroll = ScrollController();
  bool serviceOn = false, gameInstalled = true, running = false, stopping = false, showChangelog = false;
  String status = '';
  Color statusColor = Colors.grey;
  String changelog = '';
  StreamSubscription? sub;

  String t(String key, [Map<String, Object?> args = const {}]) => tr(options.lang, key, args);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    status = 'idle';
    _load();
    sub = events.receiveBroadcastStream().listen((e) => _onEvent(Map<String, dynamic>.from(e as Map)));
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    sub?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _refresh();  // e.g. back from the accessibility settings
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString('options');
    if (saved != null) options.restore(jsonDecode(saved) as Map<String, dynamic>);
    changelog = await rootBundle.loadString('CHANGELOG.md');
    await _refresh();
  }

  Future<void> _save() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('options', jsonEncode(options.toJson()));
  }

  /// The engine's state (the bot may have been running while this screen was closed).
  Future<void> _refresh() async {
    final s = Map<String, dynamic>.from(await engine.invokeMethod('state') as Map);
    setState(() {
      serviceOn = s['serviceEnabled'] as bool;
      gameInstalled = s['gameInstalled'] as bool;
      running = s['running'] as bool;
      log
        ..clear()
        ..addAll((s['log'] as List).cast<String>());
    });
    _onEvent(Map<String, dynamic>.from(s['status'] as Map));
  }

  void _onEvent(Map<String, dynamic> e) {
    setState(() {
      if (e['type'] == 'log') {
        log.add(e['line'] as String);
        if (log.length > 500) log.removeAt(0);
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (logScroll.hasClients) logScroll.jumpTo(logScroll.position.maxScrollExtent);
        });
        return;
      }
      switch (e['state']) {
        case 'running':
          running = true;
          _status(stopping ? 'stopping' : 'running', Colors.grey);
        case 'done':
          running = stopping = false;
          final report = Map<String, dynamic>.from(e['report'] as Map);
          status = renderReport(report, options.lang);
          statusColor = Colors.green;
        case 'stopped':
          running = stopping = false;
          _status('stopped', Colors.orange);
        case 'error':
          running = stopping = false;
          final key = e['key'] as String?;
          final msg = key != null ? t(key, Map<String, Object?>.from((e['args'] as Map?) ?? {})) : e['message'] as String;
          status = t('error', {'msg': msg});
          statusColor = Colors.red;
        default:
          if (!running) _status('idle', Colors.grey);
      }
    });
  }

  void _status(String key, Color color) {
    status = t(key);
    statusColor = color;
  }

  Future<void> _start() async {
    await _save();
    final every = int.tryParse(options.supportEvery.trim());
    final error = await engine.invokeMethod<String>('start', {
      'mode': options.mode,
      'source': options.source,
      'level': options.level,
      'repeat': options.repeat,
      'full': options.full,
      'loop': options.loop,
      'ads': options.ads,
      'nature': options.nature,
      'order': options.order,
      'supportEvery': options.support && every != null && every > 0 ? every : null,
    });
    if (error != null) {
      setState(() => _status(error, Colors.red));
      if (error == 'err_service') _refresh();
    }
  }

  Future<void> _stop() async {
    setState(() {
      stopping = true;
      _status('stopping', Colors.orange);
    });
    await engine.invokeMethod('stop');
  }

  void _set(void Function() change) {
    setState(change);
    _save();
  }

  @override
  Widget build(BuildContext context) {
    final o = options;
    final editable = !running;
    Widget check(String key, bool value, void Function(bool) onChanged) => CheckboxListTile(
          dense: true,
          contentPadding: EdgeInsets.zero,
          controlAffinity: ListTileControlAffinity.leading,
          value: value,
          onChanged: editable ? (v) => _set(() => onChanged(v!)) : null,
          title: Text(t(key)),
        );
    Widget radios(List<(String, String)> items, String group, void Function(String) onChanged) => Wrap(
          spacing: 4,
          children: [
            for (final (value, key) in items)
              ChoiceChip(
                label: Text(t(key)),
                selected: group == value,
                onSelected: editable ? (_) => _set(() => onChanged(value)) : null,
              ),
          ],
        );

    return Scaffold(
      appBar: AppBar(
        leading: Padding(padding: const EdgeInsets.all(8), child: Image.asset('assets/icon.png')),
        title: Text('${t('title')} v$version'),
        actions: [
          DropdownButton<String>(
            value: o.lang,
            underline: const SizedBox(),
            items: [for (final e in uiLanguages.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
            onChanged: (v) => _set(() {
              o.lang = v!;
              _onEvent({'type': 'status', 'state': running ? 'running' : 'idle'});
            }),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextButton.icon(
            style: TextButton.styleFrom(alignment: Alignment.centerLeft, padding: EdgeInsets.zero),
            onPressed: () => setState(() => showChangelog = !showChangelog),
            icon: Icon(showChangelog ? Icons.expand_more : Icons.chevron_right),
            label: Text(t('changelog')),
          ),
          if (showChangelog) Card(child: Padding(padding: const EdgeInsets.all(12), child: Text(changelog))),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(t('info_title'), style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 6),
                Text(t('info')),
                const SizedBox(height: 8),
                Text(t(serviceOn ? 'service_on' : 'service_off'), style: TextStyle(color: serviceOn ? Colors.green : Colors.red)),
                if (!gameInstalled) Text(t('game_missing'), style: const TextStyle(color: Colors.red)),
                if (!serviceOn)
                  FilledButton.tonal(onPressed: () => engine.invokeMethod('openAccessibility'), child: Text(t('open_settings'))),
              ]),
            ),
          ),
          const SizedBox(height: 8),
          Text(t('mode'), style: Theme.of(context).textTheme.titleSmall),
          radios([('normal', 'normal'), ('elite', 'elite')], o.mode, (v) => o.mode = v),
          Text(t('level'), style: Theme.of(context).textTheme.titleSmall),
          radios([('latest', 'latest'), ('beaten', 'beaten'), ('pending', 'pending'), ('stars', 'stars')], o.source, (v) => o.source = v),
          if (o.source == 'stars')
            SizedBox(
              width: 120,
              child: TextFormField(
                initialValue: o.level,
                enabled: editable,
                keyboardType: TextInputType.number,
                decoration: InputDecoration(labelText: t('level')),
                onChanged: (v) => _set(() => o.level = v),
              ),
            ),
          check('repeat', o.repeat, (v) => o.repeat = v),
          check('full', o.full, (v) => o.full = v),
          check('loop', o.loop, (v) => o.loop = v),
          check('ads', o.ads, (v) => o.ads = v),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(t('build_title'), style: Theme.of(context).textTheme.titleMedium),
                Text(t('build_nature')),
                radios([('physical', 'physical'), ('magic', 'magic')], o.nature, (v) => o.nature = v),
                const SizedBox(height: 6),
                Text(t('build_order')),
                ReorderableListView(
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  buildDefaultDragHandles: editable,
                  onReorderItem: (from, to) => _set(() => o.order.insert(to, o.order.removeAt(from))),
                  children: [
                    for (final (i, type) in o.order.indexed)
                      ListTile(key: ValueKey(type), dense: true, title: Text('${i + 1}. ${t('type_$type')}'), trailing: const Icon(Icons.drag_handle)),
                  ],
                ),
                Row(children: [
                  Checkbox(value: o.support, onChanged: editable ? (v) => _set(() => o.support = v!) : null),
                  Flexible(child: Text(t('build_support'))),
                  const SizedBox(width: 6),
                  SizedBox(
                    width: 48,
                    child: TextFormField(
                      initialValue: o.supportEvery,
                      enabled: editable,
                      keyboardType: TextInputType.number,
                      onChanged: (v) => _set(() => o.supportEvery = v),
                    ),
                  ),
                  const SizedBox(width: 6),
                  Flexible(child: Text(t('build_support_after'))),
                ]),
              ]),
            ),
          ),
          const SizedBox(height: 8),
          Row(children: [
            Expanded(child: FilledButton(onPressed: running ? null : _start, child: Text(t('start')))),
            const SizedBox(width: 8),
            Expanded(child: OutlinedButton(onPressed: running && !stopping ? _stop : null, child: Text(t('stop')))),
          ]),
          const SizedBox(height: 8),
          Text(status, style: TextStyle(fontWeight: FontWeight.bold, color: statusColor)),
          const SizedBox(height: 8),
          Text(t('log'), style: Theme.of(context).textTheme.titleSmall),
          Container(
            height: 280,
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(border: Border.all(color: Theme.of(context).dividerColor), borderRadius: BorderRadius.circular(8)),
            child: ListView.builder(
              controller: logScroll,
              itemCount: log.length,
              itemBuilder: (_, i) => Text(log[i], style: const TextStyle(fontFamily: 'monospace', fontSize: 11)),
            ),
          ),
        ],
      ),
    );
  }
}
