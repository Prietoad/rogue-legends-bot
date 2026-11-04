# Changelog

## 1.10.1 (2026-11-04)
- Version 1.11.0 was an interim label for this tree. This release is 1.10.1.
- Tower: a win that shows Next (floors 1–9, also "Next Floor" / "Próximo piso") continues straight to the next floor. Floor 10 has no Next: Okay, then the chest. A ticket-count guess no longer taps Okay and bounces back to the tower menu while Next is on screen.
- Tower: a full-screen Loading… after a fight is a transition, not a loss. The bot waits through it and reads Victory, Next, or Okay again before it can call the fight failed.
- Daily rewards: the web store is given time to load, the daily reward is claimed, the page is scrolled, and the free spin (Daily Wheel / Ruleta diaria) is taken. Then the bot returns to the game and continues with VIP. Opening the site from a lobby pass and leaving at once is no longer done.
- Dungeon Dive: a victory with Okay, Confirm, or Tap to Continue is dismissed so the routine moves on.
- Guild: after the raid the bot stays on the guild map for the free donation, then claims the Guild Vault's free daily personal reward, and only then returns to the main menu.
- Dojo and guild raid skill picks reroll once when the offer has nothing the build wants, the same way a level does. Dungeon Dive already rerolls through the level player.
- Missing stars: a card cut off at the top of Star Challenge (its header is off screen, a grey condition star is still visible) is played. The scan no longer gives up on a loading or empty frame and falls through to the last beaten level while that card still misses a star. When every beaten level really has 3 stars, the bot keeps playing the last beaten level (lobby level − 1) in the selected mode until energy is gone or Stop. It does not switch that run to Last unlocked.
- Wise Monk: after each of the two spins, the reward overlay ("Tap anywhere to claim" / "You Received") is dismissed before the next spin or Leave. A spin no longer sits on that overlay until the run restarts.
- Last unlocked (normal and elite): a win starts the newly unlocked level from the lobby. A loss on that level falls back to the previous one. A win of the fallback tries the new level again. The level just won is no longer pinned and replayed.
- Shops refresh more than once while the coins allow, to find a skill the build wants. A refresh is skipped when paying it would leave too few coins to buy a wanted skill that is already affordable, or to buy a cheap skill the next roll could offer.
- Daily rewards (English): "Claim Rewards" is tapped from the lobby menu. "Enter Code" is not. If that button is missing, the popup is closed so mail and the rest of the routine can continue.
- Elite energy stays a choice of 5, 10 or 15 (default 5). The bot spends that much when the counter can pay it, otherwise the next lower cost.
- World 2 (lobby `2-N` titles, path choice, and World 2 events) is unchanged.

## 1.10.0 (2026-11-01)
- Star Challenge keeps scrolling up when the list is stuck on a high page. The same frame no longer counts as the end of the list while the target level is still above the lowest card on screen (that used to stop the run with "Level X not found (list ends at Y)").
- Last unlocked: after a win, the level that gets replayed is the one just played. A stale low number (38 while the lobby is on ~76) is corrected from the lobby title.
- Elite energy is a choice of 5, 10 or 15 (default 5, so more runs). The bot spends that much when the counter can pay it, otherwise the next lower cost. It no longer always picks the highest affordable.
- Daily rewards: if the web claim never opens, the popup is closed (its ✕) so mail is not left on the wrong window.
- Patrol: a Quick Patrol sheet that is already open is closed first, then the timed reward (green Reclamar, from 2 hours) is claimed. A clock OCR put on the next line still counts.
- Dojo: the progress chest is claimed when its label is on screen, including while tickets remain.
- Skip fights is off by default. When it is on, a green Skip on a mode fight is tapped once. The grey Skip (it opens a purchase) is never tapped.
- Wise Monk spins twice, then leaves. It does not leave early because of HP.
- Build presets: Shuriken (shuriken, bleed, venom; never Deadly Stars), Fire (fire only), Poison (venom, bleed, shuriken), Ice, Lightning and Sustain. Shops still buy only wanted skills. A skill already taken this run is preferred over a new one of the same type. Glass Cannon and Darkside are not taken on farm builds.

## 1.9.2 (2026-10-31)
- Campfire ("Un Momento de Descanso"): the bot upgrades a skill. It restores HP only when the top-bar heart line is under 40%. If that line cannot be read, it still upgrades (the "39% de HP" under Descansar is the heal amount, not the current HP).
- Shops buy skills of the build only (your damage-type order, then rarity). They no longer spend leftover coins on other cards. A level-up with no named damage type uses the reroll before taking an untyped skill. A damage type written on the card (shuriken, venom, …) wins over a stale saved tag.
- Star Challenge keeps scrolling until the target level is on screen. One drag that does not move the list is tried again; the search no longer stops after a short scroll.
- Pause holds the bot at the next screenshot or tap so you can fix the game by hand. Resume continues the same run. Stop still ends it.

## 1.9.1 (2026-10-31)
- Star Challenge no longer opens Boss Rush: with Boss Rush (or other Rush/Challenge events) featured, the bot used to tap the first "Challenge" on screen — often the event banner. It now only taps the Star Challenge control just above Start (English split "Star" / "Challenge", full "Star Challenge", or Spanish "Desafío de Estrellas"), and ignores Boss Rush, Wish Challenge, Chest Rush, and Egg Rush.
- Quick Patrol closes on its own: opening Quick Patrol used to leave the bot stuck tapping the dimmed Patrol ✕ underneath. It now closes the Quick Patrol sheet first (`Closing Quick Patrol` in the log), then the Patrol menu.
- No gem, gold, or energy spends added. Phone engine got the same recognition logic.

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
