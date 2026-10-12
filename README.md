# rogue-legends-bot

A bot that farms **Rogue Legend** (PocketHaven) in the **MuMu Player 12** emulator on Windows. It works only
from the screen: screenshots over ADB, OCR to read them, and taps. No memory reading or network tampering.
It plays in Spanish or English.

**Money rule:** it never uses offers and never spends diamonds. Popups are closed only through their
"tap to close" text or their ✕. Reward videos are watched (the VIP pass skips them).

## What it does

- **Levels:** normal or elite (elite cost 5/10/15 from the energy you have). The level can be:
  - the last unlocked level;
  - the last beaten level;
  - a level that still misses stars (star rewards include diamonds);
  - any beaten level N from Desafío de Estrellas.
- **Build:** picks level skills and shop items by your preferences: physical or magic damage, the
  order of the damage types, and a support skill every N damage skills. Every new skill is saved in
  `data/skills.json` with inferred tags, which you can edit.
- **Full routine:**
  - VIP cards "claim all";
  - Arena, Tower, Crystal Mines and Pet Kingdom (tickets, free ads);
  - Patrol: the reward near its 8 h cap, plus free and energy quick patrols;
  - guild raid boss and the free guild donation;
  - then levels until out of energy, claiming free energy (Daily Pack, videos).
- **Loop:** the full routine forever: routine → levels → wait for energy → again.
- **Unattended:**
  - starts MuMu Player and opens the game;
  - resumes an interrupted level;
  - follows the game's forced tutorials;
  - on a freeze, crash or stuck screen it restarts MuMu and continues. It stops only if the same error
    repeats.

## Setup

1. Python 3.13 with the optional **tcl/tk** feature (python.org installer → Modify).
2. `pip install -r requirements.txt`
3. MuMu Player 12 with Rogue Legend installed. The emulator screen must be portrait 9:16
   (e.g. 1080x1920 or 1440x2560).

## Usage

```bash
python -m roguebot              # the window: pick the options, press Start
python -m roguebot --dry-run -v # navigate to the level without starting it (no energy spent)
python -m pytest -q             # tests on real screenshots (no emulator needed)
```

The window detects the MuMu Player folder when it can; otherwise choose it with "Browse…". Start
opens the emulator and the game when they are closed, and shows any problem in red. Stop ends the
run at the next step.

See `CLAUDE.md` for how it works inside: architecture, game knowledge, and every screen the bot knows.
