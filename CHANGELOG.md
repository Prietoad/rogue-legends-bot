# Changelog

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
