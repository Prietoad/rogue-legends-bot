# Changelog

## 1.12.0 (2026-11-14)
- **Heliora, blacksmith's anvil** ("Yunque del Herrero"): a new screen that offers an item to take ("Recibes") or to gamble on upgrading ("Reforzar", with a success chance). The bot stopped on it. Seen: a small attack boost → 70% → a common skill → 40% → a legendary skill → 10%. The bot upgrades while the chance is 40% or more, then takes the item. What a failed upgrade shows has not been seen yet.

## 1.11.1 (2026-11-14)
- Patrol: since the World Map compass moved the lobby buttons, the game's "Patrulla" and "Desafío de Estrellas" labels are sometimes read as one text, and the bot tapped between the two buttons (it opened the star list and the patrol was reported as failed). It now taps the patrol button itself.

## 1.11.0 (2026-11-14)
- **Worlds:** new "World" option (Current / Everdale / Heliora). The bot opens the game's World Map (the compass next to the chapter chest) and enters the chosen world before starting a level. "Current" keeps the world the game is in. If the account has no World Map or the world is locked, it plays the current world instead of stopping.
- **Heliora levels** (the bot used to get stuck on their new screens):
  - Forks ("Camino A / Camino B"): takes the path to the shop when it has at least 76 coins, otherwise the other path.
  - Shop: buys the stat boost first ("ATQ ↑↑↑", "PS máx. ↑↑", 3 per visit: three attack boosts raised the attack from 1.5m to 2.0m), and "Curar 30%" when below 50% HP. Then the skills, as before.
  - The Black Market is a normal shop paid with run coins at half price: the bot now buys there instead of leaving.
  - Campfire ("Un Momento de Descanso"): trains a skill at 60% HP or more, rests below that. It used to always rest, even at full HP.
  - Events: takes the free option (No gracias, Rechazar, Rezar, Espiar, Observar) instead of the ones that cost coins or max HP.
  - Treasure miner minigame ("Minero de Tesoros"): digs on a search pattern and, when it finds a piece of a treasure, digs around it until the treasure is whole (a whole treasure gives a skill).
  - Cursed vendor ("Vendedor Maldito"): signs the contract whose known terms add up best (campfires turned into inns are worth more than doubled shop prices; half the skills disabled is the worst).
  - Trained skill result ("NEXT" button): tapped. The bot took its green button for auto-play and waited there for hours.
- Skill picks: the bot waits until every card is on screen. A pick read while the cards were still flying in showed one card and wasted the reroll.
- The Spanish "Recompensas x2" button at the level end is recognised (doubled with "Watch ads" on).
- A screen that looks like auto-play for about 3 minutes with no fight in between now stops the level (and the usual restart recovery runs) instead of waiting forever.
- Result on Heliora 2-1 with a 28.8m power account: from dying at roll 16–22 to surviving the 30 rolls and reaching the boss. No victory yet.

## 1.10.0 (2026-11-08)
- Arena: the bot now fights the opponent highest in the list that is not stronger than you, since higher rows give more arena points. It used to pick the strongest opponent below your power, wherever it was in the list. If every opponent is stronger, nothing changes (free refresh, then the weakest).

## 1.9.0 (2026-10-28)
- Uses far less CPU: about 1.5 cores on average while running instead of 2.6–3.8 (−60% to −65% CPU per screen read), at the same speed in levels and ~35% faster when going back to the lobby and in the full routine. The text reader no longer keeps the processor busy while it waits, uses at most 4 cores, and no longer runs a step that turned short texts upside down, so it now reads texts like "x1", "x5", "Modos" or "3,3m" correctly. Finding the ✕, back arrow and tutorial hand on screen is ~15 times faster.
- Uses far less memory: ~120 MB committed instead of ~600 MB. Most of it was reserved at startup by a math library the bot doesn't need, once per processor core.
- The log in the window keeps the last 2000 lines (it grew without limit over days of running; `debug/bot.log` still keeps everything).

## 1.8.0 (2026-10-27)
- Arena: the bot always fights the closest opponent that is not stronger. Some opponent powers ("3,3m") were misread and that opponent was left out of the choice, so the bot sometimes fought a much weaker one. A misread power is now read again from a close-up of its row. The log lists every opponent's power.
- Unknown popups over the lobby (new seasonal events, like the autumn "¡Sendero de Ascuas!"): the bot no longer mistakes them for a level, which used to make it tap around the lobby and restart MuMu Player. A popup it doesn't recognize is closed by its ✕ (any size) or by a tap outside it, never inside it (popups have purchase buttons). Its screenshot is saved in `debug/popup_unknown_*.png`.

## 1.7.0 (2026-10-21)
- Fortune Teller ("Adivino") in levels: the bot now uses its crystal balls instead of leaving. On each visit it tries the 40% ball once, then the 70% ball up to 3 times, as long as the orbs allow (5 orbs = exactly that), and then leaves. Won skills are claimed.

## 1.6.0 (2026-10-18)
- Simpler options: "Keep running" and "Full routine" replace the three old checkboxes. Levels now always run until out of energy (claiming the free energy first). "Keep running" then waits for energy and starts again (with the full routine too, if ticked); off, the bot stops when out of energy. "Full routine" runs the secondary content first, then the levels from Mode/Level.
- Patrol: the reward is claimed once it holds at least 2 hours (it used to wait for almost 8). It is checked before each level and, in the full routine, before the modes.

## 1.5.2 (2026-10-16)
- Auto-play: if one press-and-hold on the dice doesn't turn auto-play back on (after a shop, for example), the bot holds again instead of rolling by taps for the rest of the level. It only switches to taps if auto-play never worked in that level, or after 3 misses in a row.

## 1.5.1 (2026-10-16)
- Interrupted level ("¿Continuar la aventura?" after the game was closed mid-level): the bot now recognizes the Spanish dialog and always taps "Confirmar" to resume the level (its energy is already spent), never "Abandonar".
- MuMu's own store ads drawn over the game ("Claim Your Free SSR Goddess") are closed automatically. They blocked every tap and ignored Back.
- If the bot finds a level still running when it tries to go back to the lobby, it plays the level out instead of restarting MuMu Player (the level used to be lost).
- Guild donation: the guild castle is found even when its name is hard to read behind the flag (the donation used to fail some days).

## 1.5.0 (2026-10-15)
- Frozen emulator: if the screen stays exactly the same with no input for 60 seconds (also during auto-play or fights), MuMu Player is restarted. If MuMu ignores the shutdown, its processes are closed.
- After a restart the full routine continues at the part it was doing, instead of starting over or giving up. A part that keeps breaking the run is marked failed and the routine moves on.
- Tower: after a win the bot taps "Próximo piso" and goes straight to the next floor (one ticket each, like before), skipping the loading screens and the tower screen. It never uses it for the last ticket.
- Dojo and guild raid skill picks now follow your build (nature, damage types, support), like levels.
- Dungeon Dive: its end screen ("DERROTA/VICTORIA" + "Confirmar") is recognized; a run used to get stuck there.
- Challenge buttons that the game ignored (right after a screen appears) are tapped again.
- If a part fails and leaves the game on a screen the bot can't leave, the bot restarts instead of failing every remaining part.
- Free energy: after claiming the Daily Pack or a video, the bot takes the reward first and then reads the popup again, so it no longer stops with energy videos left.
- Starting the bot while a level is still running (after Stop) plays that level out first instead of restarting MuMu.
- The log is also saved to `debug/bot.log`.

## 1.4.2 (2026-10-13)
- The bot finds its way back to the lobby from the Mascotas and Tienda tabs too (it didn't recognize the bottom tab bar there and got stuck).

## 1.4.1 (2026-10-13)
- Ads for other apps that the emulator shows over the game no longer stop the bot: it presses Back, brings the game to the front again and, if the ad only closes by tapping it, taps it and closes the page it opens.

## 1.4.0 (2026-10-13)
- Full routine: new Dojo Battle (fights while there are tickets, claims its free progress chest) and Dungeon Dive (plays its 3-depth runs like a level, with your build, until no tickets are left).
- Full routine: daily rewards (top-left menu → Recompensas Diarias, claimed on the game's web page, then back to the game) and mail (Reclamar todo).

## 1.3.0 (2026-10-12)
- New "Watch ads" option (off by default; only for accounts that have bought ad skipping). When off, the bot never watches an ad: no energy videos, x2 rewards, video revives, ad tickets or quick patrol videos.
- Every option in the window (and the language) is saved and restored the next time.
- Works on other accounts: features the account doesn't have yet (elite, Desafío de Estrellas, patrol, guild, modes…) are skipped instead of stopping the bot.
- Clearer Info section: requirements and what the bot does.

## 1.2.0 (2026-10-12)
- Auto-play: the bot holds the dice to turn on the game's auto-play, then lets the level roll by itself (it falls back to tapping if auto-play isn't available).
- Faster between levels: the Patrol popup is only opened when its reward is due (or after midnight, when the free quick patrols come back), instead of after every level.

## 1.1.0 (2026-10-12)
- Windows exe (`RogueLegendBot.exe`): no Python needed. Settings and the skill database live in a `data` folder next to it.
- Rogue Legend icon in the window, the taskbar and the exe.
- Changelog in the window (hidden by default).

## 1.0.0 (2026-10-12)
- Levels: normal or elite (highest elite cost the energy allows); last unlocked, last beaten, missing stars or any star challenge level.
- Repeat until out of energy, claiming the free energy (Daily Pack, videos).
- Build: skill picks and shop purchases follow the preferences (physical/magic, damage type order, a support skill every N).
- Full routine: VIP cards, Arena, Tower, Crystal Mines, Pet Kingdom, Patrol, guild raid and donation, then levels.
- Loop mode: routine, levels, wait for energy, again.
- Unattended: starts MuMu Player and the game, resumes interrupted levels, follows forced tutorials, restarts MuMu on freezes.
- Spanish and English (game and window).
