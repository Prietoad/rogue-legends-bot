# Changelog (phone app)

## 0.3.0 (2026-10-18)
- Same changes as the desktop bot 1.6.0: two options ("Keep running" and "Full routine"; levels always run until out of energy), and the patrol reward is claimed from 2 hours, checked before each level and before the modes.

## 0.2.2 (2026-10-16)
- Same fix as the desktop bot 1.5.2: a missed press-and-hold on the dice is retried, so auto-play keeps running instead of switching to taps for the rest of the level.

## 0.2.1 (2026-10-16)
- Same fixes as the desktop bot 1.5.1: the Spanish "¿Continuar la aventura?" dialog resumes the interrupted level, a level still running is played out instead of failing, and the guild castle is found even when its name reads badly.

## 0.2.0 (2026-10-15)
- Same fixes as the desktop bot 1.5.0: tower "Próximo piso", Dojo/raid skill picks by your build, the Dungeon Dive end screen, re-tapped challenge buttons, free energy videos no longer skipped after a claim, and a routine that continues at the part it was doing after a recovery.

## 0.1.1 (2026-10-13)
- Finds its way back to the lobby from the Mascotas and Tienda tabs too (same fix as the desktop bot 1.4.2).

## 0.1.0 (2026-10-13)
- First version of the Android app: the desktop bot (1.4.1) running on the phone where Rogue Legend is installed.
- Same options as the desktop window: mode, level, repeat, full routine, loop, watch ads, build. They are saved for next time.
- Same text recognition as the desktop bot (its own OCR models), so it reads the game the same way.
- Plays through an accessibility service (taps) and screen capture (allowed on each Start); keeps the screen on while it plays and shows a notification with Stop.
- If a level was left running, it is played out first.
- Tested on MuMu Player (1440x2560): full routine and levels. Not tried yet on a phone with a taller screen.
