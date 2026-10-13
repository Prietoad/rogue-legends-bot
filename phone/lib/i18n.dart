/// UI texts in Spanish and English (the phone version of roguebot/i18n.py). Keys must exist in both.
const uiLanguages = {'es': 'Español', 'en': 'English'};

const texts = <String, Map<String, String>>{
  'es': {
    'title': 'Bot de Rogue Legend',
    'changelog': 'Novedades',
    'info_title': 'Info',
    'info': 'Requisitos:\n'
        '  • Android 11 o superior, con Rogue Legend instalado.\n'
        '  • El juego en español o inglés, con el tutorial inicial terminado.\n'
        '  • Activa «Rogue Legend bot» en Ajustes › Accesibilidad (ver el botón de abajo): así el bot toca por ti.\n'
        'Al pulsar Iniciar, acepta la captura de pantalla (el bot necesita ver el juego): abre el juego y juega con la pantalla encendida.\n'
        '  • No uses el móvil mientras el bot juega. Para pararlo: Detener aquí o en la notificación.\n'
        '  • Nunca gasta diamantes ni compra ofertas.\n'
        '  • Si tu cuenta no tiene una función (gremio, élite, modos…), la salta y sigue.\n'
        '  • Si se atasca, vuelve al juego y sigue. Las capturas de los fallos van a Android/data/com.diego.roguebot_phone/files/debug.\n'
        '  • Tus opciones se guardan para la próxima vez.',
    'language': 'Idioma',
    'service_on': '✓ Servicio de accesibilidad activado',
    'service_off': '✗ Servicio de accesibilidad desactivado',
    'open_settings': 'Abrir ajustes de accesibilidad',
    'game_missing': '✗ Rogue Legend no está instalado',
    'err_service': 'Activa el servicio de accesibilidad «Rogue Legend bot» antes de iniciar.',
    'err_game_missing': 'Rogue Legend no está instalado o no se pudo abrir.',
    'err_capture': 'Sin permiso para capturar la pantalla: el bot necesita ver el juego. Pulsa Iniciar y acepta.',
    'err_game_update': 'Rogue Legend necesita actualizarse: pulsa ACTUALIZAR en el juego (Google Play) y vuelve a Iniciar.',
    'err_game_load': 'Rogue Legend no llegó a la pantalla principal en {seconds} s.',
    'mode': 'Modo',
    'normal': 'Normal',
    'elite': 'Élite',
    'level': 'Nivel',
    'latest': 'Último desbloqueado',
    'beaten': 'Último superado',
    'pending': 'Estrellas pendientes',
    'stars': 'Desafío de Estrellas',
    'repeat': 'Repetir hasta quedarse sin energía (antes reclama la energía gratis)',
    'start': 'Iniciar',
    'stop': 'Detener',
    'build_title': 'Build (habilidades en niveles y tienda)',
    'build_nature': 'Daño preferido',
    'physical': 'Físico',
    'magic': 'Mágico',
    'build_order': 'Prioridad de tipos',
    'build_support': 'Coger una habilidad de soporte cada',
    'build_support_after': 'habilidades de daño',
    'type_ice': 'Hielo',
    'type_lightning': 'Rayo',
    'type_fire': 'Fuego',
    'type_shuriken': 'Shuriken',
    'type_venom': 'Veneno',
    'type_bleed': 'Sangrado',
    'stopping': 'Deteniendo... (termina la acción actual)',
    'stopped': 'Detenido por el usuario',
    'idle': 'En espera',
    'running': 'Ejecutando...',
    'bad_level': 'El nivel debe ser un número positivo',
    'error': 'Error: {msg}',
    'victory': 'Victoria',
    'defeat': 'Derrota',
    'level_finished': 'Nivel terminado: {result}',
    'out_of_energy': 'Sin energía tras {runs} partidas: {wins} victorias, {losses} derrotas',
    'loop': 'Repetir la rutina sin fin: modos, niveles hasta sin energía, esperar energía y volver a empezar',
    'ads': 'Ver anuncios (solo si la cuenta tiene comprada la opción de saltar anuncios)',
    'full': 'Rutina completa: Tarjetas VIP, recompensas diarias, correo, modos (Arena, Dojo, Torre, Mazmorra, Minas, Mascotas), patrulla, jefe del gremio, donación gratis y luego niveles hasta sin energía',
    'part_arena': 'Arena',
    'part_tower': 'Torre',
    'part_dojo': 'Batalla de Dojo',
    'part_dive': 'Descenso a la Mazmorra',
    'part_daily': 'Recompensas diarias',
    'part_mail': 'Correo',
    'part_mines': 'Minas de cristal',
    'part_pets': 'Reino de mascotas',
    'part_raid': 'Jefe de incursión',
    'part_vip': 'Tarjetas VIP',
    'part_patrol': 'Patrulla',
    'part_donate': 'Donación al gremio',
    'status_done': 'hecho',
    'status_skipped': 'omitido',
    'status_failed': 'FALLÓ',
    'log': 'Registro',
  },
  'en': {
    'title': 'Rogue Legend bot',
    'changelog': 'Changelog',
    'info_title': 'Info',
    'info': 'Requirements:\n'
        '  • Android 11 or newer, with Rogue Legend installed.\n'
        '  • The game in Spanish or English, with the first tutorial finished.\n'
        '  • Turn on "Rogue Legend bot" in Settings › Accessibility (button below): it lets the bot tap for you.\n'
        'On Start, allow the screen capture (the bot needs to see the game): it opens the game and plays with the screen kept on.\n'
        '  • Don\'t use the phone while the bot plays. To stop it: Stop here or in its notification.\n'
        '  • It never spends gems or buys offers.\n'
        '  • If your account lacks a feature (guild, elite, modes…), it skips it and moves on.\n'
        '  • If it gets stuck, it goes back to the game and goes on. Screenshots of failures go to Android/data/com.diego.roguebot_phone/files/debug.\n'
        '  • Your options are saved for next time.',
    'language': 'Language',
    'service_on': '✓ Accessibility service on',
    'service_off': '✗ Accessibility service off',
    'open_settings': 'Open accessibility settings',
    'game_missing': '✗ Rogue Legend is not installed',
    'err_service': 'Turn on the "Rogue Legend bot" accessibility service before starting.',
    'err_game_missing': 'Rogue Legend is not installed or could not be opened.',
    'err_capture': 'No permission to capture the screen: the bot needs to see the game. Press Start and allow it.',
    'err_game_update': 'Rogue Legend needs an update: press UPDATE in the game (Google Play), then Start again.',
    'err_game_load': 'Rogue Legend did not reach its main screen in {seconds} s.',
    'mode': 'Mode',
    'normal': 'Normal',
    'elite': 'Elite',
    'level': 'Level',
    'latest': 'Last unlocked',
    'beaten': 'Last beaten',
    'pending': 'Missing stars',
    'stars': 'Star Challenge',
    'repeat': 'Repeat until out of energy (claims free energy first)',
    'start': 'Start',
    'stop': 'Stop',
    'build_title': 'Build (skills in levels and shops)',
    'build_nature': 'Preferred damage',
    'physical': 'Physical',
    'magic': 'Magic',
    'build_order': 'Type priority',
    'build_support': 'Take a support skill every',
    'build_support_after': 'damage skills',
    'type_ice': 'Ice',
    'type_lightning': 'Lightning',
    'type_fire': 'Fire',
    'type_shuriken': 'Shuriken',
    'type_venom': 'Venom',
    'type_bleed': 'Bleed',
    'stopping': 'Stopping... (finishing the current action)',
    'stopped': 'Stopped by the user',
    'idle': 'Idle',
    'running': 'Running...',
    'bad_level': 'Level must be a positive number',
    'error': 'Error: {msg}',
    'victory': 'Victory',
    'defeat': 'Defeat',
    'level_finished': 'Level finished: {result}',
    'out_of_energy': 'Out of energy after {runs} runs: {wins} victories, {losses} defeats',
    'loop': 'Loop the routine forever: modes, levels until out of energy, wait for energy, start again',
    'ads': 'Watch ads (only if the account has bought the skip ads option)',
    'full': 'Full routine: VIP cards, daily rewards, mail, modes (Arena, Dojo, Tower, Dungeon, Mines, Pets), patrol, guild raid, free guild donation, then levels until out of energy',
    'part_arena': 'Arena',
    'part_tower': 'Tower',
    'part_dojo': 'Dojo Battle',
    'part_dive': 'Dungeon Dive',
    'part_daily': 'Daily rewards',
    'part_mail': 'Mail',
    'part_mines': 'Crystal Mines',
    'part_pets': 'Pet Kingdom',
    'part_raid': 'Guild raid',
    'part_vip': 'VIP cards',
    'part_patrol': 'Patrol',
    'part_donate': 'Guild donation',
    'status_done': 'done',
    'status_skipped': 'skipped',
    'status_failed': 'FAILED',
    'log': 'Log',
  },
};

String tr(String lang, String key, [Map<String, Object?> args = const {}]) {
  var s = texts[lang]![key] ?? key;
  args.forEach((k, v) => s = s.replaceAll('{$k}', '$v'));
  return s;
}

/// The finished run's summary line(s), like roguebot/report.py's render.
String renderReport(Map report, String lang) {
  final results = (report['results'] as List).cast<String>();
  if (report['repeat'] != true) {
    return tr(lang, 'level_finished', {'result': tr(lang, results.first)});
  }
  final wins = results.where((r) => r == 'victory').length;
  final levels = tr(lang, 'out_of_energy', {'runs': results.length, 'wins': wins, 'losses': results.length - wins});
  final parts = (report['parts'] as List).cast<List>();
  if (parts.isEmpty) return levels;
  final line = parts.map((p) => '${tr(lang, 'part_${p[0]}')}: ${tr(lang, 'status_${p[1]}')}').join(', ');
  return '$line\n$levels';
}
