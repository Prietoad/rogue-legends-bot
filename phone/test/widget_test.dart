import 'package:flutter_test/flutter_test.dart';
import 'package:roguebot_phone/i18n.dart';
import 'package:roguebot_phone/main.dart';

void main() {
  test('every UI text exists in both languages', () {
    expect(texts['es']!.keys.toSet(), texts['en']!.keys.toSet());
  });

  test('a full routine report lists the parts, then the levels', () {
    final report = {
      'results': ['victory', 'defeat', 'victory'],
      'repeat': true,
      'parts': [
        ['vip', 'done'],
        ['raid', 'skipped'],
      ],
    };
    expect(renderReport(report, 'en'), 'VIP cards: done, Guild raid: skipped\nOut of energy after 3 runs: 2 victories, 1 defeats');
    expect(renderReport({'results': ['defeat'], 'repeat': false, 'parts': []}, 'es'), 'Nivel terminado: Derrota');
  });

  test('saved options are restored, invalid ones keep their defaults', () {
    final o = Options()
      ..restore({
        'lang': 'en',
        'mode': 'elite',
        'source': 'nonsense',
        'level': 'x',
        'loop': true,
        'ads': 'yes',
        'damage_order': ['fire', 'ice', 'lightning', 'shuriken', 'venom', 'bleed'],
      });
    expect([o.lang, o.mode, o.source, o.level, o.loop, o.ads], ['en', 'elite', 'latest', '1', true, false]);
    expect(o.order.first, 'fire');
    final bad = Options()..restore({'damage_order': ['fire']});
    expect(bad.order, damageTypes);
  });

  test('options survive a save and restore', () {
    final o = Options()
      ..full = true
      ..supportEvery = '4'
      ..nature = 'magic';
    final copy = Options()..restore(o.toJson());
    expect(copy.toJson(), o.toJson());
  });
}
