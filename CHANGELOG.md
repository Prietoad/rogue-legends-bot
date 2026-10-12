# Changelog

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
