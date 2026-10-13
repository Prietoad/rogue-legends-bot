# rogue-megalegend

Bot that plays the Android game **Rogue Legend** (PocketHaven, `com.pockethaven.roguelegend`) running in the **MuMu Player 12** emulator on Windows. It works only from the screen: it takes screenshots over ADB, reads the screen with OCR (and later template matching), and sends taps and swipes. No memory reading, hooking or network tampering.

## Goals / roadmap
1. ✅ **Navigation**: from the main UI, open the level the user picked:
   - mode: Normal or Elite (skull toggle next to the start button: `APAGADO` = normal, `ACTIVADO` = elite)
   - level: last unlocked (lobby start button), **missing stars** (`RunRequest.pending_stars`: a beaten level whose card header shows fewer than 3 gold stars, `card_stars`; scans the star list upwards from its end; none left → last beaten), last beaten (`RunRequest.last_beaten`: lobby level − 1, started from Desafío de Estrellas; never pinned, replaying it unlocks nothing) or a beaten level N from **Desafío de Estrellas**
2. ✅ **Play a full level** (`play.py`, the same code for normal and elite): roll dice, wait out fights, pick the first skill, leave events/shops, until VICTORIA/DERROTA → Continuar. No build logic yet.
3. ✅ **Elite energy**: the "Modo Élite" dialog sets the run cost to 5/10/15. The bot always uses the highest the current energy allows.
4. ✅ **Run flow**: navigate → play → Continuar → back in the Aventura lobby (popups closed). The UI shows "Level finished: Victory/Defeat", or the error in red if the bot couldn't continue.
5. ✅ **x2 speed**: on board frames, if the speed button shows `x1` the bot taps it once. If it's still `x1` after that, x2 is treated as locked on this account and not retried.
6. ✅ **Ad reward doubling**: on the level end screen, some runs show "x2 Rewards" (bottom-right, with a daily counter). The bot taps it before Continue (VIP skips the ad). The Spanish label hasn't been seen yet.
7. ✅ **Repeat until out of energy** (UI checkbox): replays the same level. With "Last unlocked", a victory unlocks the next level, so the bot pins the played number and replays it from Desafío de Estrellas. When energy < 5 it opens the energy popup and claims every free option (Daily Pack "Free", reward videos); never the gem-priced one. It stops when nothing free is left.
8. ✅ **Spanish and English UI** (see `labels.py`).
9. ✅ **Energy videos (resolved 2026-10-12):** there is no cooldown state: the 3 daily videos are spent across the day's claims, and the popup then shows "Intentos Restantes Hoy: 0" under the video button (the 3 under the gem button is the gem option). The bot saves `debug/energy_none_*.png` whenever it finds nothing free, and re-reads if videos are left without a yellow button. Old notes: In the live test, the Daily Pack and the first reward video worked (energy 1 → 16 → 31). After that one video, though, the bot reported "No free energy left to claim" while the popup still had 3 chances. Likely cause: the video button shows a cooldown/timer between videos, so it's no longer recognized as the yellow button. To do:
   - Capture the energy popup right after a video, in both languages, and save it as a fixture.
   - Recognize the cooldown state.
   - Decide whether to wait out the cooldown or stop.
   - 2026-10-10: the popup shows "Intentos Restantes Hoy: N" for videos (3 per day) and separately for the gem button. When the video count is 0 the bot correctly stops (fixture `energy_popup_no_videos.png`). The cooldown case (count > 0 but no yellow button) is still not captured.
   - Add the Spanish labels of the energy popup, which so far has only been seen in English.
10. 🚧 **Full routine** (see the section below): modes, guild raid, then repeat levels.
    - **Loop** (UI checkbox, `RunRequest.loop`, implies full): modes → levels until out of energy → idle in the lobby checking energy every `ENERGY_WAIT_POLL` s (`Device.wait`, interrupted by Stop) → whole routine again. A cycle that raises is logged and the next cycle runs; only Stop ends it.
11. ✅ **Build (skill choice)**: see "Build" below. 12. Later: event choices, black market (not seen yet).
13. ✅ **Auto-play (2026-10-12)**: **holding** the red dice (`AUTO_PLAY_HOLD` 2 s, `Device.hold` = a swipe that doesn't move) turns on the game's auto-play: the dice turns lime green with "Toca para Detener" (`dice_auto` → `LevelScreen.AUTO_PLAY`, never tapped, since a tap stops it). Seen live: it keeps rolling through skill picks, events, shops, duels and revives until the level ends. `Player` always tries the hold on a red dice. If the red dice comes back without auto-play ever showing, it's unavailable and the bot taps for the rest of the level. If auto-play stops mid-level, it holds again.

## Environment assumptions
- MuMu Player 12, ADB serial `127.0.0.1:16384`, MuMu's own adb at `C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe`.
- Any **portrait 9:16** resolution. The code works in reference coordinates (1440x2560): `Device` resizes screenshots to that size and scales taps back. Other aspect ratios fail at startup with a clear message. We don't change the emulator's display size (`wm size`), because that changes the user's emulator and the Unity layout.
- **Game UI language: Spanish or English.** Every matched text lives in `roguebot/labels.py` as (Spanish, English) variants. Only variants actually seen on screen are listed (plus `DEFEAT` English, inferred). A screen in a language without a variant makes the bot stop with a screenshot: add the variant and an `en_*`/Spanish fixture test.
- **Emulator start (requested 2026-10-11, `emulator.py`):** the UI has a "MuMu Player folder" field (auto-detected from the Windows uninstall registry `MuMuPlayerGlobal` → parent of `uninstall.exe`, then usual install paths; saved in `data/settings.json`, git-ignored). On Start: MuMuManager.exe `info -v 0` → `control -v 0 launch` if Android is off (wait `EMULATOR_BOOT_TIMEOUT`) → adb connect to the `adb_host_ip:adb_port` it reports → `pm list packages` (installed?) → `app launch -pkg` if not in front (`dumpsys window` mCurrentFocus; `dumpsys window windows` does not print it on MuMu) → `Navigator.wait_for_lobby(GAME_LOAD_TIMEOUT)`. Each failing step raises `EmulatorError(i18n key)`, shown translated in red. Tools live in `nx_main\` (or `shell\` on older MuMu 12).
- **Recovery (requested 2026-10-11):** `make_runner.run` repeats `attempt()` until it finishes. Any error (frozen emulator/game, crash, stuck screen) → `Emulator.shutdown()` and a new attempt (MuMu started, game opened, interrupted level resumed; results and the pinned level are kept). The same error (`_error_key`: numbers and screenshot paths ignored) more than `MAX_SAME_ERROR` times with no level finished in between → stop with it. Never retried: Stop, `NoEnergyError` (normal end), `PERMANENT_ERRORS` (folder, game missing, update needed). Every adb call has `ADB_TIMEOUT` (a frozen emulator used to hang screencap for 10 min); an empty screenshot raises.
- **Speed (2026-10-12):** one capture + OCR costs ~0.9 s (screencap PNG 0.35 s, OCR 0.55 s; raw screencap is slower, half-res OCR saves too little). Waits cut: `UI_SETTLE` 0.7, `POLL_INTERVAL` 0.3, `VIDEO_SETTLE` 3, `SCROLL_SETTLE` 0.8 (a level went from ~8 to ~4 min, the routine parts from ~4 to ~2 min). With short waits a frame can be stale, so steps that decide on the frame right after a tap wait to see the change first (`Navigator._capture_change`, `Routine._wait_change`): elite cost +/-, mode toggle, and the guild donation (its free button turns into a **gem price** in place). The stuck-tap guard needs `MAX_REPEATED_TAPS` **and** `STUCK_TAP_SECONDS`. Modes list / star list: tap a card only when seen twice in the same place (scroll inertia).
- Arena season change: "¡Felicidades por tu ascenso!" popup over the arena screen (closes by its "para cerrar" text). `Routine._claim_or` closes reward and text-closable popups in every routine wait.
- **Code review fixes (2026-10-12):** a retry never replays a single requested level and never re-runs the routine of the same cycle; a stuck lobby between parts no longer aborts the remaining parts; an unreadable energy counter is read again (`_energy`), never taken as 0; the black market (unverified, maybe gem prices) is left without buying; the x2 rewards button is given up for Continue after `DOUBLE_REWARD_TRIES`; a skill pick seen again (missed tap) is counted once; label variants are normalized once and `Text.norm` is cached.
- **Ads for other apps (requested 2026-10-13):** the emulator sometimes shows ads for other apps over the game; some close only by tapping them, which opens another app/tab. `go_to_lobby`, on a screen it doesn't know, checks the foreground package (`Navigator._leave_other_app`): another app in front → Back (`BROWSER_BACK_MAX`) → `Device.launch` (monkey, brings the game to the front) → still not the game: tap the ad (`OTHER_APP_AD_TAP`) and the same again. Only when another package is in front, so the game itself is never tapped blindly. Not seen live yet (no screenshot of such an ad).
- Game start can show "Nueva Actualización" + ACTUALIZAR (forced update via Google Play): `go_to_lobby` stops with `err_game_update`; the bot never drives Google Play.
- The developer's account has the VIP pass, so ads are skipped instantly. **Other people use the bot on their own accounts** (requested 2026-10-12): those can lack ad skipping and any feature (guild, elite, Desafío de Estrellas, modes, patrol, auto-play, x2 speed).
- **Missing features never stop the run; the bot moves on to the next step.** Routine parts → `failed`/`skipped`. `parse_lobby` treats the elite toggle and the stars button as optional (`Lobby.has_elite`, `stars_button` None). A button only counts as missing after `FEATURE_READS` lobby reads (`Navigator._lobby_until`), so one bad OCR frame isn't "not unlocked". Any star-list start without a star list or a beaten level (`StarsUnavailable`) → last unlocked level, remembered for the session (`state["no_stars"]`: no pinning). Elite chosen but not unlocked (`EliteUnavailable`) → stop with that message, no emulator restart. The after-level patrol backs off to `_patrol_next(PATROL_CLAIM_AFTER)` after `PATROL_FAILS_TO_BACK_OFF` failures in a row. The energy popup exists on every account, so its errors still go through the normal restart recovery. New code must follow this: a feature that isn't on screen means skip, never restart or stop. Tapless waits (no-ads revive, x2 screen without a readable Continue) are `UNKNOWN`, so the stuck guard still applies.
- **UI options persist** (requested 2026-10-12): `App.options()` (every form value + UI language + valid MuMu folder) is saved to `data/settings.json` on Start, language change and window close, and `_restore_options` reloads it (invalid values keep the defaults). A new form option must be added to both.

## Hard rules (money)
- **Never use any offer and never spend diamonds (gems).** Don't tap purchase, price, offer or gem buttons. Lobby popups are closed only through their "Toca … para cerrar" text.
- **Ads only with "Watch ads" ticked** (`RunRequest.ads`, default off, requested 2026-10-12; only for accounts that skip ads). Off → never tap any ad: energy videos (`Navigator.ads`), x2 rewards (Continue instead, and never the x2 button even when Continue isn't read yet), free revive (let the countdown run out), Mines/Pets ad tickets and quick patrol videos (`Routine.ads`). Daily Pack "Free" isn't an ad and is always claimed. A new ad button must be gated the same way.

## Game knowledge (from exploration)
- **Footer**: the center tab is **Aventura** (the lobby). The lobby shows the current level title `"N. Name"`, the buttons `Recompensas de Capítulo / Patrulla / Desafío de Estrellas`, and the start button (`INICIO ⚡x5` for normal, `LISTO` for elite) with the elite skull toggle to its right.
- **Desafío de Estrellas**: a vertical list of cards. Each card has a header `"N. Name"` (`(Élite)` in elite), 3 star conditions, and a start button (`INICIO`/`LISTO`). The level that's still unbeaten shows as a locked card ("Desbloquea completando el capítulo"). The list opens scrolled near its end. Back arrow at the bottom left.
- **Elite start**: LISTO opens a "Modo Élite" dialog (level modifiers, `INICIO ⚡X5`, −/+ for "Recompensa de N vez" = cost 5/10/15, ✕ to close). + goes up to 15 even when energy is lower, so the cost has to be capped in code. The same dialog appears from the elite Desafío list.
- **Energy**: top-bar counter `"12/32"`. Normal runs cost 5.
- **Lobby popups** after returning from a level (promo packs, weekend roulette). They contain purchase/gem buttons. Close them **only** through their bottom text "Toca (en cualquier lugar) para cerrar".
- **In a level** (board layouts vary: a loop with floors `Profundidad X/3`, or a path with a roll counter `N/30`). The run starts with a skill pick.
  - Board: big red dice button (bright red = ready, grey = rolling; detected by color, `dice_ready`).
  - Fights play automatically (`Ronda N/30`).
  - Skill pick: "¡SUBISTE DE NIVEL!" (level-up) or "¡SUBIDA DE PODER!" (after a boss, with a 1–5 pick counter); "Selecciona una Habilidad para aprender", 3 cards, each with a rarity tag in its top-left corner. **No timeout**: the game waits.
  - Tile events: centered title at y≈1400, option labels at y≈1790 with icons below (e.g. "Carro de Botín Abandonado": Robado/Salir; "Un Momento de Descanso": Descansar/Entrenar).
  - Shop: buy nothing, "Salir" button at the bottom.
  - Wheels: Lucky Treasure "¡GIRAR!" → "Toca en cualquier lugar para reclamar"; Monje Sabio "GIRAR" → "Meditación completa" + "Salir".
  - Event outcomes: "Toca para continuar".
  - Card flip "Excavar en Busca de Tesoro": 4x3 face-down "?" cards (detected by color); flip them in order.
  - Dice duel "¡Batalla de Dados!": `Yo N / 21`. TIRAR while N < 15, else RESISTIR.
  - Speed button bottom-left: "» x2" / "» x1" shows the **current** speed (tap toggles x2 ↔ x1, verified 2026-10-12).
  - The yellow "x4" badge above it opens the **paid** "Tarjeta VIP" offer ("Desbloquea Velocidad de Juego x4"): never tap it. x4 speed is not available.
  - End: "DERROTA" / "¡VICTORIA!" + "Continuar" → "Cargando..." → lobby (and popups).

## Tech stack
- Python 3.13, deps pinned in `requirements.txt`
- `adbutils`: device connection, `screencap`, taps and swipes
- `rapidocr` + `onnxruntime`: OCR (fast, local, no GPU)
- `opencv-python` / `numpy`: images (BGR `np.ndarray`, full resolution)
- `tkinter` (standard library): the minimal UI window. It is **not** pip-installable: Python must be installed with the optional "tcl/tk and IDLE" feature (python.org installer → Modify). Without it, `python -m roguebot` prints this hint and exits.
- `pytest`: tests against real screenshots

## Architecture
```
roguebot/
  config.py      constants only: adb/serial, resolution, fixed tap coords, geometry, timings
  emulator.py    MuMu Player: find the install folder, start the emulator, open the game (MuMuManager.exe + adb)
  settings.py    UI settings kept between sessions (data/settings.json)
  device.py      Device: ADB wrapper (screenshot/tap/swipe). No game knowledge. Raises Stopped once the stop Event is set (UI Stop button).
  labels.py      every game text as (Spanish, English) variants
  vision.py      Ocr (RapidOCR wrapper, region crops), Text, normalize/matches/find, match_template
  templates/     image templates (close_x.png: the popup ✕; back_arrow.png: menus' ← button)
  screens.py     pure recognition: OCR output -> typed screen states (Lobby, Card, EliteDialog, LevelState...). Never sends input.
  navigation.py  Navigator: lobby -> mode -> level -> (elite cost) -> start, with verification
  play.py        Player: in-level loop (classify screen -> tap or wait) until VICTORY/DEFEAT
  request.py     RunRequest + form validation (no UI imports, so it's testable)
  mode_screens.py pure recognition for the full routine (modes list, arena, dojo, tower, dive, mines/pets, guild raid, lobby menu, mail)
  routine.py     Routine: full-routine parts (vip, daily, mail, arena, dojo, tower, dive, mines, pets, patrol, raid, donate); per-part failure -> "failed"
  skills.py      skill database (data/skills.json): auto-adds new skills with inferred tags
  build.py       Build preferences + pure choice rules (choose / shop_order)
  ui.py          tkinter window: info (prerequisites), mode, level source, level number, repeat, full routine, build (nature, type order, support every N), Start/Stop, status line, live log
  __main__.py    entry point; make_runner = the Start action (connects to the emulator on Start, navigate, play, back to lobby)
tools/capture.py dev helper: save screenshot (+ OCR dump) to captures/
tests/           pytest on tests/fixtures/*.png (real 1440x2560 screenshots)
```

### Testing rules (mandatory)
- **Every change must add new tests** that cover it (new screen → fixture screenshot + recognition test; new logic → unit test).
- **Every change must pass the full suite**: `python -m pytest -q` runs all previous and new tests, and all of them must pass before the change is done. Don't delete or weaken existing tests to make a change pass.
- **Every code change must rebuild the app** (requested 2026-10-12): after the tests pass, run `.\build.ps1`. It replaces `dist\RogueLegendBot.exe`, which the user runs to test. Then smoke-test it: launch it from an empty folder and check that the window opens. The one-file exe runs the UI in a child process, so close both processes afterwards.

### Patterns and conventions
- **Layers**: `device` (I/O) → `vision` (perception) → `screens` (interpretation, pure and testable) → `navigation` / `play` (behavior) → `ui`. Keep game knowledge out of `device`, and keep input out of `screens`.
- **Observe → decide → act → verify.** Every action is followed by a fresh screenshot that confirms the expected screen. On failure, raise `NavigationError` and save the frame to `debug/`.
- **Prefer reading text over fixed coordinates.** Tap OCR'd text centers when the element has a label. Fixed coordinates only for unlabeled elements (footer tab, skull toggle, back arrow), and they live in `config.py`.
- Text matching goes through `vision.normalize` (lowercase, no accents), because OCR returns `Desafio`/`Desafío` and `Élite` inconsistently.
- Full-frame OCR misses some text on colored bars. Re-OCR a **cropped region** (see `parse_star_list`, which reads each card's header `HEADER_ABOVE_BUTTON` px above its button).
- Unity scroll lists have inertia. Use slow drags (`SCROLL_DURATION`) sized from the known `CARD_PITCH`, never shorter than `MIN_DRAG` (a short swipe can register as a tap on a button).
- **In-level loop**: `classify_level_screen` maps each frame to a `LevelState(kind, tap)`. `Player` taps or waits. Safety nets: an UNKNOWN screen for longer than `UNKNOWN_SCREEN_TIMEOUT`, or the same tap repeated more than `MAX_REPEATED_TAPS` times → stop with a screenshot in `debug/`. To support a new screen, add a branch in `classify_level_screen` (or a label in `CONTINUE_BUTTONS`) plus a fixture test.
- **Never tap purchase or gem buttons, and never tap blindly.** Popups close only through their "para cerrar"/"to close" text or their ✕ (template match). The footer tab is tapped only when the footer is visible at full brightness (`footer_visible`; popups darken it). Anything else: wait, then stop with a screenshot.
- The energy video button is chosen by position (under "Chances Left Today: N>0") **and** color (yellow); the gem button next to it is green and can never match.
- Prefer anchoring taps on stable text (rarity tags, option labels) over fixed offsets from titles: screen variants shift layouts.
- New screen → add a fixture screenshot to `tests/fixtures/` and a recognition test in `tests/test_screens.py`. Pure logic → `tests/test_logic.py`.
- Keep code simple: no speculative abstractions, and no game logic in the UI or entry point.

## Commands
```bash
pip install -r requirements.txt
python -m roguebot              # UI window: pick mode/level, Start -> navigate, play the full level
python -m roguebot --dry-run -v # navigate (and set the elite cost) but don't start; no energy spent
python -m pytest -q             # recognition tests (no device needed)
python -m tools.capture NAME --ocr   # save captures/NAME.png and print OCR boxes
.\build.ps1                     # rebuild dist\RogueLegendBot.exe (pip install pyinstaller); after every code change
```
Tip when exploring: `--dry-run` doesn't spend energy. A real start costs 5 energy (normal) or 5–15 (elite).

## Full routine (requested 2026-10-10)
UI checkbox "Full routine" (`RunRequest.full`, implies `repeat`). `routine.py` (`Routine.run_parts`) runs the parts below in order, then `__main__` runs the usual repeat level loop. A part that raises (`NavigationError`/`PlayError`) is logged and reported as `failed`, and the routine continues with the next part. Between the six modes the bot stays in the modes tab (`_back_to_modes`: popup text, ✕, ← until the modes list; falls back to the lobby if that fails); it goes to the lobby only before the raid and after it. `Report.parts` = [(part, done|skipped|failed)], shown on the status line.
Recognition lives in `mode_screens.py` (pure, like `screens.py`); tests in `tests/test_mode_screens.py` (fixtures) and `tests/test_routine.py` (fake screens).

**Spec (from the user):**
0. **VIP cards** (first part, requested 2026-10-11): lobby left-column icon "Tarjetas VIP" (`vip_cards_icon`) → tap only the exact "Reclamar todo" at the bottom (`vip_claim_all`); the screen also has $ purchase buttons and per-card "Reclamar". Grey once claimed today (a tap does nothing). Reward popups via "tap to claim", then ← back to the lobby. No icon → skipped. English labels ("VIP Cards", "Claim All") guessed.
0b. **Daily rewards + mail** (after VIP, requested 2026-10-13): lobby top-left ≡ (unlabeled, `config.MENU_BUTTON`) opens a menu (Configuraciones, Correo, Bolsa, Código de Regalo, Invitar Amigos, Recompensas Diarias; `menu_entry`). **Daily**: "Recompensas Diarias" popup → green "Reclamar" (`daily_claim`; not "Introducir Código") → the game opens its **web store roguelegend.io in a browser** (Chrome custom tab, logged in as the player): only "Reclamar ahora!" is tapped (the store sells VIP/$ items) → the store page shows "Recompensas diarias" Día 1–5 with checks → `Device.back()` until the game is in front (`_back_to_game`, always, also on failure). The reward arrives by **mail** ("Recompensa diaria"). **Mail**: "Correo" popup → "Reclamar todo" (`mail_claim_all`; never "Eliminar todo" next to it) → claim popups → ✕. Not logged in on the web (other accounts) → no "Reclamar ahora!" → back to the game, part failed. English labels guessed. Not seen: the web page on a day not yet claimed (the claim showed Día 4 checked right after the tap).
1. **Modes** (lobby → Modes button bottom-right, fixed `config.MODES_BUTTON`: its Spanish label "Modos" OCRs badly). List order: Arena, Dojo Battle (Batalla de Dojo), Tower Challenge (Desafío de torre), Dungeon Dive (Descenso a la Mazmorra), Crystal Mines (Minas de cristal), Pet Kingdom (Reino de las mascotas); the routine runs them in that order (Dojo and Dive added 2026-10-13).
   - **Arena**: while tickets ≥ 1: Challenge → 5 opponents → fight the strongest whose Power ≤ ours. All stronger → "Free Refresh" only if free, then the weakest.
   - **Tower**: Challenge until the first defeat or no tickets.
   - **Crystal Mines / Pet Kingdom**: challenge the shown (highest) difficulty; after a defeat, "Sweep previous stage" until no tickets. At 0 tickets, watch the free ad ("Dungeon Tickets x1 (k/2)") while offered.
   - **Dojo Battle** (`dojo`): screen "Batalla de Dojo" (training dummy "Muñeco de Paja", "Daño Total"), tickets top-right (crop `DOJO_TICKETS_REGION`), "Desafío" with its ticket cost; at 0 tickets the button shows "Se actualiza en". Fight = "Dojo de Entrenamiento": 5 skill steps (same screen as the raid: "Aprender habilidades (k/2)", picked by rarity), 10 rounds of damage, then "VICTORIA" + "Confirmar" (always). Progress chest "RECLAMAR" ("Intenta el Dojo N veces") is a free reward (50 gems): claimed. Verified live (1 ticket).
   - **Dungeon Dive** (`dive`): screen "Ruinas Olvidadas 12" (name changes), "Recompensas", tickets top bar "N/2" with a refill timer, "Desafío" (stays at 0 tickets; **never tapped at 0**: tapping it froze the game once). A run is a **level board** with "Profundidad N/3" and "Modificadores de nivel" + Continuar: played by `Player` (build, auto-play) through `Routine.play_level` (set by `__main__`). Plays every ticket whatever the result. **Not verified end to end**: the only live try froze the game on the modifiers popup (0% CPU, identical frames) and the ticket was lost; check the first real run.
1b. **Patrol** (`patrol` part after the modes, and after **every** normal/elite level via `__main__._claim_patrol`; requested 2026-10-11): lobby "Patrulla" → popup ("Tiempo de patrulla", "Patrulla Rápida" + "Reclamar"; a "Tarjeta Mensual VIP" offer below is never tapped) → Reclamar **only when the "Tiempo de patrulla" counter is ≥ 7:50:00** (`PATROL_CLAIM_AFTER`; it stops at 8 h; unreadable → no claim) → "Toca … para reclamar" → Patrulla Rápida → popup "Reclama de inmediato las recompensas de 2 h" with a free video ("Gratis"/"Free") and an energy option ("⚡x10", green button: identified by its cyan lightning icon, `QUICK_PATROL_CYAN_MIN`), each with "Cantidad restante: N"/"Remaining: N". Uses the video while N>0, then energy while N>0 **and** energy ≥ cost; never gems. A patrol failure after a level is logged and never stops the run. **After-level skip (2026-10-12):** `Routine.patrol_wait` (time until the counter reaches 7:50) → `__main__._patrol_next` → the after-level check is skipped until then or local midnight (the daily quick patrols reset), whichever is first. It used to cost ~6 s per level for nothing.
- Lobby parts (VIP, daily, mail, patrol, raid, donate) read the lobby through `Routine._lobby_texts`: the game sometimes opens a screen by itself right after the lobby shows ("Fondo del Álbum", events), so it re-reads and goes back.
2. **Guild raid** (only if the lobby shows the "Gremio"/"Guild" book bottom-left): Guild map → "Raid Boss" → Challenge → 5 skill steps → fight; until "Daily Attempts Left" is 0.
2b. **Guild donation** (after the raid, requested 2026-10-11; skipped outside a guild): Guild map → castle "Sala de Gremio"/"GuildHall" → bottom "Donar" → popup "Donación de Gremio" with "Intentos restantes hoy: N" and a green "Gratis" button. Only the exact "Gratis"/"Free" is tapped (`free_donation`): after the one free donation per day the button shows a **gem price ("25")** and the bot leaves via ✕. Reward: "Toca en cualquier lugar para reclamar". English "Donate"/"Guild Donation" guessed.
3. Then normal/elite level clearing until out of energy (repeat mode, claiming free energy).

**User decisions:** arena all-stronger → free refresh only, then the weakest. Stuck part → screenshot, back to lobby, mark failed, continue. Skill picks in modes/raid → **highest rarity** (Mythic > Legendary > Epic > Rare > Common), top card on ties. Allowed to spend tickets/attempts and watch ads while developing.

**Game knowledge (English UI, seen 2026-10-10):**
- **Never tap "Skip" in mode/raid fights**: it opens a paid "VIP Card" offer ($6.99; this account's VIP is not that card). Fights just play out (~30–45 s); the bot waits. That offer closes via "Tap anywhere to close".
- Menus have a square ← button bottom-left (template `templates/back_arrow.png`, `mode_screens.back_arrow`); `go_to_lobby` taps it after popups/✕.
- Modes list: keeps its scroll position between visits, so `_open_mode` scrolls back to the top until Arena shows. Card titles right-aligned (Arena, Tower Challenge, Crystal Mines, Pet Kingdom; Pet Kingdom visible at y≈2241 without scrolling).
- Arena: tickets in the top bar, re-read from a crop (`ARENA_TICKETS_REGION`). Opponent panel "Arena Challenge": our power "534,8k" in its header, rows with "Challenge" (x≈1071) and power below the name (x≈580). Powers use k/m/b with a comma decimal (`parse_power`). Result: "VICTORY!" + "OK".
- Tower ("Tower of Heroes N", "Floor N"): tickets = top-bar "13/10" (can exceed the max). A defeat spends the ticket. Result: "DEFEAT" + "Tap to Continue" → loading → tower screen. Victories are handled by the same result parser (live: 5 floors won in a row, then a defeat).
- Crystal Mines / Pet Kingdom: a popup over the modes list ("Difficulty" number, tickets "N/2", "Sweep previous stage" + "Challenge"; the buttons stay at 0 tickets, so read the counter). **A defeat does not spend the ticket.** The ad button replaces both buttons only at 0 tickets. Rewards: "Tap anywhere to claim". Opens at the highest difficulty (only a ← arrow shown). **What happens after a win (next difficulty shown?) not seen yet.**
- Guild map: "Raid Boss" label. Raid: "Guild Raid", "Challenge" + "Daily Attempts Left: N" (→ "Refreshes In: 22h" when done). Skill steps: "Select a Skill to learn!" + 3–4 cards with rarity tags + "Learn Skills (k/n)" (pick n, then press it; "Reroll" ignored). Fight "Round: N/10"; result "DEFEAT" (always, it's a damage race) + "OK".
- **Language test (2026-10-10), full routine in Spanish and English:** seen and fixed in Spanish: modes list, arena (0 tickets), tower ("Torre de los Héroes", button "Desafío" not "Desafiar", a fight + "Toca para continuar"), mines/pets popups (0 tickets), guild map ("Jefe de / Incursión" wraps), raid ("Asalto de Gremio", "Se actualiza en"), energy popup ("Comprar", "Intentos Restantes Hoy:" with the count on the next line, "Gratis", "Se actualiza en"), Fortune Teller "Adivino", dice duel "RECLAMAR". English run: clean. **Still unseen in Spanish** (labels marked (?) in `labels.py`): arena opponent panel / free refresh, mines/pets ad and sweep buttons, raid attempts text, raid skill pick, arena/raid "OK", rarities other than Común/Legendario, x2 rewards.
- **Revive on death** (levels): "¡Revivir ahora!" / "Revive" popup with a 10 s countdown, a green gem button ("60") and a yellow video button ("Gratis"/"Free"). The bot taps the free one only if it is yellow (`LevelScreen.REVIVE`); it never taps the gem one. Seen live in both languages.
- **Missed start taps:** sometimes the lobby ignores the INICIO tap (screen still settling). `_press_start` taps the same button again if it is still in place after `START_RETAP_AFTER` s (max `START_RETAPS`); a start that registered leaves the screen, so this never double-spends.
- **Daily reset (2026-10-11):** right after midnight the game opened the Fishing event by itself just after the lobby showed (`detect_language` now retries via `go_to_lobby`), and the Arena card showed "Abre en 4m" (closed): `mode_closed` → arena part `skipped` (English "Opens in" guessed).
- **New chapter unlock (2026-10-11, level 14):** a chain of 6+ lobby popups (album, events) → `MAX_LOBBY_ATTEMPTS` 16. Then a **forced tutorial hand** pointed at the new "Álbum" button and the game ignored every other tap (looked like an input freeze; restarting the game/emulator does not clear it). `screens.tutorial_hand` (template `templates/tutorial_hand.png`, it blinks: ~0.97 when shown) → `go_to_lobby` taps its target ring (`TUTORIAL_TAP_OFFSET` below the hand, which bobs ~50 px) on **any** screen, up to `TUTORIAL_MAX_STEPS`, then backs out of what opened. Seen chains: Álbum; Equip tab → Heroes tab → Companions "+" → "Choose Power Skill" popup (closed via ✕).
- Mines/Pets after a win show the next difficulty (seen: 20 → 21). Spanish arena panel "Desafío de la Arena", "Desafiar", "Recarga Gratis" (seen).
- **Interrupted run** (game closed mid-level): the lobby shows "Continue Adventure? You have an ongoing adventure. Resume?" (Abandon / OK). `go_to_lobby` taps OK and plays it out via `Navigator.resume_level` (set by `__main__`; its energy is already spent). Spanish text guessed. Verified live in English.
- Event "Forbidden Knowledge" (Read / Walk Away): a failed "Read" greys the option (taps do nothing). `_event_option` skips options whose icon is greyed (`EVENT_DISABLED_MAX_SATURATION`); "Walk Away" counts as leave.
- Board tiles can say "BLACK MARKET" (seen on a level board, not yet entered).
- The game can hang on "Cargando..." (seen once; needed a manual restart). The bot stops with a screenshot after `LEVEL_LOAD_TIMEOUT`.

Dev helpers used during exploration live in the session scratchpad (o.py: tap+screenshot+OCR; addcase.py: add a level-screen fixture case; lab.py: add a label variant).

## Build (requested 2026-10-10)
- **Skill database** `data/skills.json` (`skills.Catalog`): key = name letters only (OCR-proof), fuzzy match (0.85) for typos. Every skill seen on a level skill pick or in a shop is added with `infer_tags(name, description)`:
  - damage type: ice / lightning / fire / shuriken / venom / bleed (the game calls bleed "Wound"): the type whose keyword appears first (name first). Keywords in both languages, matched at word start ("ice" never matches "twice").
  - nature: magic = ice/lightning/fire, physical otherwise (also untyped skills).
  - role: damage if typed; support if the *name* has a support word (Lifesteal, Dodge, Shield); else damage/support by description words; default damage.
  - rarity: from the card tag (common, rare, epic, legendary, mythic).
  - The user fixes wrong tags by editing the JSON and setting `"auto": false`.
- **UI "Build"**: preferred nature (physical/magic), ordered damage types (▲/▼), "take a support skill every N damage skills". Passed as `RunRequest.build` → `Player(build, catalog)`.
- **Rules** (`build.py`, pure): wanted = damage skills of the preferred nature, ordered by type priority (untyped after the listed types), then rarity, then top card. Support wanted after N damage skills; if none is offered, take the damage skill and keep wanting support. Nothing wanted → reroll if available (once per pick); still nothing → rarest, then top.
- **Skill pick**: reroll = "Volver a tirar"/"Reroll" with "(N)" uses below (one per level, seen as "(1)").
- **Shop**: buying = tap the yellow price button (no confirm; card turns "SOLD OUT"; coins = top-left counter). Sale cards show the old price above the current one (the lowest number is the price). Reroll is free once ("GRATIS"/"FREE"), then costs coins: the bot only uses it while free. Order: wanted first, then the rest rarest-first, buying while coins allow. Stat items (ATK/Heal) are ignored. Black market: title label guessed, parsed like the shop; not seen yet.
- Raid skill picks still use highest rarity (unchanged).
- **Safety nets learned live (2026-10-10):**
  - `classify_level_screen` returns UNKNOWN whenever the footer is visible: lobby texts once looked like an event and the bot "started" a level that never started, then tapped the lobby for minutes.
  - Repeat-tap guard compares taps with `SAME_TAP_TOLERANCE` (OCR jitters text centers by 1–3 px, so exact equality never fired).
  - The revive popup check runs late (just before the fight check): skill/shop cards can contain "Revive" ("Resurrection: Revive after your first death").
- **Tag inference notes:** "def$" = DEF as a whole word (not "Definitiva"/"defeat"); "Wound"/"Herida" = bleed; untyped skills mentioning "Magical"/"Mágico" first are magic (Wizard). OCR can garble names ("Venene Drofunde" = Veneno Profundo) and create duplicates; review `data/skills.json` from time to time.
- **More live findings (2026-10-10, evening):**
  - Spanish tower victory: "¡VICTORIA!" + "Confirmar" (OK label now includes confirmar/confirm).
  - After clearing a whole tower (10 floors): "Congrats / Congratulations on clearing Tower of Heroes N" screen with a chest and **no back arrow**: tap the chest (`TOWER_CHEST`), then "Tap anywhere to claim" → next tower. Spanish text guessed ("Felicidades"/"Enhorabuena").
  - `go_to_lobby` checks the ← arrow **before** the footer: on mode screens the footer tab spot (720, 2410) is their Challenge button, and a transition frame once looked like a footer (a tower ticket was spent).
  - Late lobby promos (e.g. "¡Oferta limitada!") are see-through: `parse_lobby` ignores the lobby while a "para cerrar"/"to close" text shows, and the energy claim closes such popups and reopens the energy popup.
