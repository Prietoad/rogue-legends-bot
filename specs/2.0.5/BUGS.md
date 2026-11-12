# 2.0.5 bug list

From Brian's 2.0.4 live tests on Nov 10, 2026 (America/New_York). Source baseline is `main` at `91a01cdf` (release 2.0.4). Fixtures in this folder are referenced as `specs/2.0.5/<file>`. Afternoon session 3:35–5:36 PM: 15 runs, no hangs, no gem/gold spend, no core skill rerolled away. Evening sessions 5:50–9:18 PM added items #6–#10. Daily Rewards worked in the evening (Claim Now → Collect → free spin → "you won" → Android back ×2).

Later 2.0.4 sessions overnight Nov 10–11 and through the evening of Nov 11 added items #11–#15, a recurrences section, and a New data section (Serpent Stance, Outbreak). Implement every numbered item (#1–#15), including §5a, and add the catalog skills in New data. Recurrences are evidence for existing items, not new work. Curse/blessing weights stay held: do not invent them.

Coordinates and line numbers below are for 1440×2560 frames and the 2.0.4 source.

---

## 1. Treasure Miner: pickaxe icon count still stuck, and it overrides the accurate dig counter

Log only (no miner screenshot in the test captures). 11 of 13 visits printed `9 pickaxe icons visible` on every read, including after 8–9 confirmed tile changes.

`play.py:972-976` prefers `count_pickaxes()` whenever it returns a number `> 0`, and ignores the dig-change counter (`MINER_PICKAXES - self._miner_used`). After a visit has already logged `changed the tile (0 pickaxes left)`, icons still say 9, so the bot keeps digging:

```
15:36:58 Treasure Miner: dig (1, 5) changed the tile (0 pickaxes left)
15:36:58 Treasure Miner: 9 pickaxe icons visible
15:36:58 Treasure Miner: dig (0, 6) (9 pickaxes left) -> tap (1179, 1107)
15:37:00 Treasure Miner: dig (0, 6) did not change the tile; trying another
15:37:00 Treasure Miner: dig (2, 0) (9 pickaxes left) -> tap (285, 1397)
15:37:03 Treasure Miner: out of pickaxes
15:37:03 event -> tap (718, 2299)   # Leave — this part worked
```

Same leftover-after-zero pattern at 5:32:17 PM. Mid-visit "did not change" taps at 4:58:25 and 5:35:20 / 5:35:25 PM are consistent with the icon reader never decrementing, so the bot thinks it still has 9 and will retry a cell that already spent a pickaxe or was a miss.

`count_pickaxes` (`world2.py:1844`) looks for light, low-saturation blobs in a strip above the grid. Used/dimmed icons (or other light HUD blobs) still match, so the count stays at 9. Visit 11 (5:15:20 PM) was the opposite misread: icons stuck at **2** the whole time while the dig counter correctly went 8, 7, …, 1.

The comment at `play.py:981-983` already says a 0 from the icon reader must not stop early, and that nine confirmed tile changes is the real stop — but a stuck-high icon count bypasses that stop.

Suggested fix: once any tile change has been confirmed this visit, use `min(icons, counted)` (or just `counted` once `self._miner_used > 0`). Stop digging after 9 confirmed changes and wait for Leave. Tighten `count_pickaxes` so dimmed icons are not counted (cross-check Remaining Treasures if that line is readable).

### Acceptance criteria

- After at least one confirmed tile change in a visit, remaining pickaxes follow the dig-change counter, not a stuck icon count.
- The bot stops digging after 9 confirmed tile changes and waits for Leave, even if `count_pickaxes()` still returns 9 (or any number `> 0`).
- A stuck-low icon read (e.g. 2 for the whole visit) must not stop the bot before the dig-change counter is exhausted.
- A leftover dig after `0 pickaxes left` must not happen (this also prevents the likely Skill Info opener in #6).
- Offline unit tests cover the "icons stuck at 9 after confirmed changes" and "icons stuck at 2" cases. No fixture image for this item.

---

## 2. Treasure Miner: measured grid can still pass the step check and tap off the board (x=1303)

5:15:20 PM, visit 11, no `grid step off … using fallback` line. First tap: `dig (1, 6) (2 pickaxes left) -> tap (1303, 1178)` — the same off-board column-6 x that 2.0.3 used. `did not change the tile`. Later taps in that visit were 337, 704, 998, 1003, 1155 — a shifted grid, not the fallback (285…1179).

`miner_step_ok` (`world2.py:1731-1744`) only checks whether the **average step** is within 15% of 149. A grid whose columns run ~337 to 1303 has step ≈161, which is inside 15% of 149 (149×1.15=171), so fallback never kicks in. The 2.0.4 guard was meant to catch exactly this x=1303 case.

11 of 13 visits did fall back and those taps were on-board. Visit 7 and 9 also used mixed measured centers (559/711, 338/570/852) without falling back; those happened to stay on the board. Only visit 11 landed off-board.

Suggested fix: also compare the first and last column (and row) to the scaled fallback edges (285 and 1179, ± a tight tolerance, e.g. 40 px). If either edge is off, use fallback even when the step looks fine. Optionally reject any center with x > 1200 or x < 250 on a 1440-wide frame.

### Acceptance criteria

- A measured grid whose last column is around x=1303 (average step still within 15% of 149) must be rejected and must use the fallback centers (285…1179), not tap x=1303.
- Fallback also triggers when the first or last column/row is off the scaled fallback edges (285 and 1179, ± a tight tolerance such as 40 px).
- A clearly on-board measured grid may still be used.
- Offline unit tests cover the x=1303 / step-≈161 case. No fixture image for this item.

---

## 3. Statue offers away catalog-core venom skills (Corrosion, Special Experiment)

`is_core_skill` (`world2.py:236-253`) and `decide_statue` (`world2.py:538-544`) only run `infer_tags(name, "")` on the **name words**. They do not look at `skills.json`. Skill picks and the shop already know these two as venom damage.

Live:

- 5:09:32 PM picked Special-Experiment (venom). **5:09:39 PM** statue: `choice offering (named skill is not a core preset skill) … skill: 'special experiment'`. The bot forgot a core venom skill it had just learned.
- **5:17:37 PM** and **5:22:18 PM**: `choice offering … skill: 'corrosion', core: False`. Corrosion is `venom` / `damage` in the live catalog.

Pray worked when the type is in the name: poison cloud, wound shuriken, poison strike, ultimate poison, sneaky poison. Offerings of lash out, counter icicle, and lacerate look right (lacerate is not in the catalog; treat as unknown later if it turns out to be bleed).

Ninja Dodge must stay **not** core (Brian, 2.0.4: no change). `name_is_support` already returns False-for-core on "dodge" / "heal", which is what we want for Ninja Dodge and Heal Shuriken.

Suggested fix: if the name is in the catalog, use the catalog `damage_type` and `role`. Keep the support-name exception (and the explicit Ninja Dodge behavior). Only fall back to name-word `infer_tags` when the skill is not in the catalog. Same idea that was sketched under 2.0.4 #10, scoped so Ninja Dodge does not become core.

### Acceptance criteria

- `is_core_skill` / `decide_statue` use the catalog `damage_type` and `role` when the name is in `data/skills.json`, not name-word tags alone.
- Corrosion and Special Experiment are treated as core venom skills (Special Experiment when pets are equipped — see §5a). The statue must not offer them away.
- Ninja Dodge and Heal Shuriken stay **not** core.
- Skills not in the catalog may still fall back to name-word `infer_tags`.
- Offline unit tests cover Corrosion, Special Experiment, and the Ninja Dodge exception. No fixture image for this item.

---

## 4. Zoomed / mid-walk board still saved as unknown_events. minor

Fixtures:

- `specs/2.0.5/20261110_154206_after_event.png`
- `specs/2.0.5/20261110_160257_after_event.png`
- `specs/2.0.5/20261110_161702_after_event.png`
- `specs/2.0.5/20261110_165755_after_event.png`
- `specs/2.0.5/20261110_171138_after_event.png`

2.0.4 already classified some board/chest/battle follow-ups (`Event follow-up is a battle, the board, or a chest; not saving it` ×3 that afternoon). These five frames are still the map: Molten Core path with a BLACK MARKET cart; Elysium overview; zoomed shrine; zoomed ballista (twice). The bot tapped through and moved on in 5–24 s — not a hang — but they should not be saved, and the 4:02:57 PM one needed a second follow-up tap before the victory screen.

Suggested fix: treat a World 2 board as the map when the HUD (EXP / Lv / VIP / Skills) is up and there is no event title or Sign/Stay/Leave button, including zoomed path frames and mid-walk shots. Don't require a specific building label (SHOP / BLACK MARKET may or may not be in the OCR).

### Acceptance criteria

- Each of the five fixtures is classified as the map / board, not as an unknown event, and is not saved under `debug/unknown_events/`.
- Zoomed or mid-walk frames with the HUD up and no event title or Sign/Stay/Leave button are treated as the map even when SHOP / BLACK MARKET is missing from the OCR.
- Offline tests load these fixtures (and their classification) without an emulator.

---

## 5. Poison build: prioritize combo skills (Brian, 2026-11-10 5:49 PM)

When the build is poison, rank combo skills higher, since extra attacks stack more Poison (Combo Rate Up, Enhanced Combo, Combo Mastery, Follow-up Strike, Weapon Mastery, Master of War, Relentless Flurry, combo-gain legendary).

### 5a. Game's answer (2026-11-10 5:50 PM), applies to poison builds

- Until Poison Strike is owned, rank it above every combo skill (combo attacks only add Poison through Poison Strike's weapon-attack Poison).
- After that, the order: Poison Strike > Deep Venom > Combo Mastery > Follow-up Strike > Corrosion > Poison Mastery > Venom Burst > Weapon Mastery > Combo Rate Up ≈ Relentless Flurry > Master of War > Poison Cloud > Fester / Ultimate Poison > Special Experiment > Enhanced Combo > Toxic Retaliation > Envenom / Sneaky Poison / Crippling Cloud / Poison Shuriken.
- Combo Bolt (lightning) ranks low; never pick it in a poison build.
- Counter skills count, but rank below combo skills.
- Protected core (the statue must never offer these away): Corrosion, Poison Strike, Deep Venom, Combo Mastery once owned, and Special Experiment when pets are equipped (usually yes).
- Use a catalog/damage_type lookup for `is_core_skill`, not name words. This also fixes item #3.

### Acceptance criteria

- In a poison build, skill picks, shop buys, and reroll decisions follow the §5a ranking.
- Until Poison Strike is owned, it ranks above every combo skill.
- Combo Bolt is never picked in a poison build.
- Counter skills may be taken, but they rank below combo skills.
- Protected core matches §5a: Corrosion, Poison Strike, Deep Venom, Combo Mastery once owned, and Special Experiment when pets are equipped. The statue must not offer these away.
- Related reroll fixtures, once ranking is in, should keep the on-build combo card rather than reroll it:
  - `specs/2.0.5/20261110_195310.png` (+ `.txt`) — Follow-up Strike
  - `specs/2.0.5/20261110_200330.png` (+ `.txt`) — Weapon Mastery
- Offline unit tests cover the ranking, the Poison Strike-first rule, the Combo Bolt exclusion, and protected-core names. See also #8.

---

## 6. Skill Info overlay after Treasure Miner: continue taps miss the ✕, then four lobby retries fail the run

8:13:34–8:13:56 PM, run 3 of SC 17 Elysium V. Same leftover as #1: icon count stuck at 9, and after `changed the tile (0 pickaxes left)` the bot kept digging (`dig (0, 6) (9 pickaxes left) -> tap (1179, 1107)`). This visit never logged `out of pickaxes` or Leave. Two seconds later the screen was a treasure-claim popup (`Tap anywhere to claim`) with **Skill Info** on top of it for Common **Counter Rate Up**.

6× `continue -> tap (719, 2380)` (8:13:58–8:14:08 PM), then `PlayError: Tapping (719, 2380) on continue has no effect` (`specs/2.0.5/play_20261110_201409.png`). Recovery `go_to_lobby` then failed four times on the same overlay: `Could not reach the Aventura lobby` (`specs/2.0.5/fail_20261110_201455.png`, `fail_20261110_201541.png`, `fail_20261110_201628.png`, `fail_20261110_201713.png`), `Same error 4 times, giving up`, `Run failed`. Brian had to restart (~17 min gap). The four fail shots are the same Skill Info screen as the play shot (hashes differ slightly; the ✕ and the claim line behind it are unchanged). The error string still says "Aventura" on an English client (navigation leftover).

`(719, 2380)` is the OCR center of "Tap anywhere to claim", in `FOOTER_Y` (`config.py:35`, `screens.py:615-618` / `L.TAP_TO_CLAIM`). The Skill Info ✕ sits at **(720, 2259)** — both the claim-line tap and `EVENT_CLEAR_TAP` `(720, 2462)` are below it and do nothing.

`is_skills_overlay` (`world2.py:1970-1973`) only matches a top-of-screen title **"Skills"**, not **"Skill Info"**. The default `close_button` template (`screens.py:235-238`) returns None on these frames. `close_button_any_size` does find the ✕ at (720, 2259), but `go_to_lobby` (`navigation.py:323, 349-351`) only uses the default-size template (any-size is reserved for Daily Rewards and `_improvise_close`, which needs a lobby behind the popup). So the four retries never tapped the ✕; they waited ~45 s each and gave up. `MAX_REPEATED_TAPS` / `STUCK_TAP_SECONDS` (`config.py:156-157`, `play.py:390-391`) are what stopped the continue loop.

The last miner dig at (1179, 1107) after pickaxes were gone is the likely opener: the claim skill's `?` is on the right of the card, and that tap can land on it once the miner board is gone.

Fixtures: `specs/2.0.5/play_20261110_201409.png`, `specs/2.0.5/fail_20261110_201455.png`, `specs/2.0.5/fail_20261110_201541.png`, `specs/2.0.5/fail_20261110_201628.png`, `specs/2.0.5/fail_20261110_201713.png`.

Suggested fix: detect the title "Skill Info" and tap the ✕ (`close_button_any_size`, which already hits (720, 2259) on these frames). Do that in the level loop *and* in `go_to_lobby` (don't wait for a lobby footer). Stop digging after nine confirmed tile changes (#1) so a leftover dig cannot open `?`. Prefer "Skill Info" over a claim-line continue while the overlay is up. Optionally rename the fail string from "Aventura lobby" to "Adventure lobby".

### Acceptance criteria

- All five fixtures are recognized as a Skill Info overlay. `close_button_any_size` (or equivalent) returns the ✕ near (720, 2259).
- The level loop taps that ✕ and does not tap "Tap anywhere to claim" at (719, 2380) or `EVENT_CLEAR_TAP` at (720, 2462) while Skill Info is up.
- `go_to_lobby` uses the any-size close matcher on this overlay and does not require a lobby footer first.
- Offline tests load these fixtures and check detection + close-button coordinates.
- Fixing #1 is part of preventing this overlay from being opened by a leftover miner dig.

---

## 7. Skill Info hang for 13.7 minutes mid-run; watchdog never fired

8:39:58 PM, SC 17 run 1 (session after the crash). Campfire upgrade, then `Skill: Opportunist … skill_pick -> tap (720, 1054)` (top card). Two seconds later: `Unknown event saved: …204000_skill_info` and `Unknown event Skill Info: no safe option; waiting`. The fixture is Skill Info for **Opportunist+** over the POWER UP result; the ✕ is again at (720, 2259). The first tap did **not** learn the skill — when the overlay finally closed at 8:53:47 PM, the same three-card Opportunist / Shuriken Throw / Lash Out offer was still up and the bot picked Opportunist again. The run still won at 8:58:51 PM.

For 13 m 47 s the bot logged "no safe option; waiting" (512 times) and, every ~20 s, `Event follow-up still up; tapping through` → `continue -> tap (720, 2462)` (`EVENT_CLEAR_TAP`, `play.py:326-334`, `config.py:164-165`) — 39 follow-up taps, all below the ✕. `is_skills_overlay` / `close_button` miss this screen the same way as #6. `204015_after_event` is the same overlay, saved again as a follow-up.

The watchdog never logged (`WATCHDOG_IDLE=90`, `WATCHDOG_STOP=300`, `play.py:426-456`). `StuckWatch.see` (`world2.py:2082-2096`) resets whenever `progress_signature` changes, and that signature includes the raw OCR line tuple (`world2.py:2066-2073`). Jitter on the same Skill Info text keeps `idle` at 0, so 90 s / 5 min never trip. The follow-up CONTINUE frames also refresh `last_known` (`play.py:340-341`).

Fixtures: `specs/2.0.5/20261110_204000_skill_info.png` (+ `.txt`), `specs/2.0.5/20261110_204015_after_event.png` (+ `.txt`).

Suggested fix: same Skill Info → tap ✕ handler as #6 (do it before the unknown-event waiter). Do not use `EVENT_CLEAR_TAP` on this overlay. Make `progress_signature` ignore OCR-line jitter (HUD rolls / HP / tokens, or a stable screen kind, not the full text tuple) so the watchdog can still end a real hang. Don't treat a "tapping through" continue as progress that restarts the idle timer.

### Acceptance criteria

- Both fixtures are recognized as Skill Info and are not saved as unknown events. The handler taps the ✕ near (720, 2259) and never `EVENT_CLEAR_TAP` (720, 2462).
- This runs before the unknown-event waiter, in the level loop.
- `progress_signature` does not change when only OCR jitter (HUD rolls / HP / tokens, or the same Skill Info text with slightly different boxes) changes, so `StuckWatch` can still reach `WATCHDOG_IDLE` (90s) and `WATCHDOG_STOP` (300s) on a real hang.
- A "tapping through" continue that does not change the screen does not reset the idle timer.
- Offline tests cover Skill Info detection on both fixtures, the ✕ coordinate, and a watchdog signature that stays stable across OCR jitter.

---

## 8. Protected core skills were rerolled away (Combo Mastery in a level, Poison Strike in raid)

### Level pick, 6:09:08 PM

`No wanted skill in ['Warrior', 'Combo Mastery', 'Exoplating']: rerolling` — fixture `specs/2.0.5/20261110_180908.png` (+ `.txt`). LEVEL UP! with Legendary **Combo Mastery Lv. 2** in the middle (Warrior Lv. 2, Exoplating). Game's protected core (#5a) includes Combo Mastery once owned. `core_index` (`build.py:206-211`) only keeps a card whose `damage_type` is in `build.order`. Catalog `combomastery` is `role=damage` but `damage_type=None`, so it is not "wanted" and the free reroll throws it away. `is_core_skill` (`world2.py:236-253`) has the same gap (name-word tags; "Combo Mastery" does not name venom).

### Dojo / raid, no screenshots (`routine.py`)

`offer_is_unfavorable` (`build.py:120-127`, used at `routine.py` ~856-857) rerolls the **whole** 4-card offer when `len(_preferred) < picks`. A single core / on-build card is not enough to fill four picks, so it gets thrown away:

- 7:17:40 PM dojo: rerolled an offer that already had PoisonShuriken
- 7:18:34 PM dojo: rerolled an offer that already had Poison Cloud
- **7:47:20 PM raid: `No wanted skill in ['Poison Strike', 'Enraged Strength', 'Fire Weapon', 'Deadly Fireball']: rerolling`** — Poison Strike is explicit protected core

Related to #5 (ranking not in 2.0.4 yet), not a new protected-core miss: 7:53:10 PM rerolled Follow-up-Strike (`specs/2.0.5/20261110_195310.png`); 8:03:30 PM rerolled Weapon-Mastery (`specs/2.0.5/20261110_200330.png`). The other 10 `play.py` reroll captures were off-build (bolts, dodge, ice, etc.).

Suggested fix: never reroll an offer that already contains a protected core (Corrosion, Poison Strike, Deep Venom, Combo Mastery once owned, Special Experiment when pets are on). Take the core and fill the rest. Tag Combo Mastery in the catalog (or keep an explicit core-name list) so `core_index` / `is_core_skill` see it — same catalog lookup as #3 / #5a. For dojo/raid, if a preferred or core card is present, pick it instead of requiring enough preferred cards to fill every remaining slot before the offer is allowed to stay.

### Acceptance criteria

- A level-up offer that already contains a protected core (Combo Mastery once owned, as in `specs/2.0.5/20261110_180908.png`) is not rerolled; the core card is taken.
- A dojo/raid 4-card offer that contains a preferred or protected-core card (e.g. Poison Strike among otherwise off-build cards) is not rerolled just because it cannot fill every remaining slot with preferred cards. Take the core/preferred card and fill the rest.
- `core_index` / `is_core_skill` see Combo Mastery as protected core once owned, even though the catalog entry is untyped (`damage_type=None`).
- Offline tests cover the Combo Mastery fixture and the raid-style Poison Strike 4-card offer. Follow-up Strike / Weapon Mastery fixtures are covered under #5 once the poison ranking is in.

---

## 9. Dungeon "Level Modifiers" intro: already classified, then overwritten; coin flip can tap the HUD book

7:34:18 PM routine entered Dungeon Dive. Depth 1/3 opens a **Level Modifiers** panel (three modifiers + a green Continue; HUD "Level Modifiers" book above Skills).

`screens.py:604-605` already handles this: if `Continue` and exact "level modifiers" are both on the frame, return CONTINUE on the green button. OCR on both evening frames has those lines (`specs/2.0.5/20261110_193431_level_modifiers.txt`, `specs/2.0.5/20261110_193814_level_modifiers.txt`). `footer_visible` is false, so classify should have returned CONTINUE. But `play.py:235` always runs `_world2`, and `play.py:902-916` treats an unknown title + `looks_like_event` as a new event, saves the frame, and coin-flips.

7:34:31 PM: `COIN FLIP … options ['Continue', 'Level', 'Modifiers'] -> picked Modifiers` (the HUD book, not the green button). Two seconds later a second flip picked Continue and the dive recovered (victory 7:37:57 PM). 7:38:14 PM (second ticket): same unknown save; this time the flip picked Continue immediately (victory 7:42:31 PM).

`_coin_button` (`world2.py:1415-1431`) already blocks HUD "skills" / "vip" / "settings", but not "level" / "modifiers". Those labels sit just above the Skills book, inside the 1750–2320 coin-flip y-band, and `tap_forbidden` (`world2.py:1355-1363`) only excludes the Skills button itself (±90 px).

Fixtures: `specs/2.0.5/20261110_193431_level_modifiers.png` (+ `.txt`), `specs/2.0.5/20261110_193814_level_modifiers.png` (+ `.txt`).

Suggested fix: keep the existing Continue handler, and stop `_world2` from coin-flipping over a state classify already set (CONTINUE / known panel). Treat "Level Modifiers" as a known title. Add "level" and "modifiers" to the HUD blocklist in `_coin_button`, and include the Level Modifiers book in `tap_forbidden` (same right-side column, above Skills).

### Acceptance criteria

- Both fixtures classify as CONTINUE on the green Continue button, not as an unknown event, and are not saved under `debug/unknown_events/`.
- `_world2` must not overwrite or coin-flip over a CONTINUE / known-panel classification from `classify_level_screen`.
- "level" and "modifiers" are on the HUD blocklist; a coin flip must not tap the Level Modifiers book.
- Offline tests load both fixtures and check classification plus the HUD blocklist.

---

## 10. Dungeon "Tap To Stop" reward spinner is unhandled; coin flip tapped the HUD "Level" book

7:42:07 PM, same dive, Depth 3/3. A prize strip runs across the top (keys, 55.5k coins, **x10 gems**, eggs, …) and the auto-play button is replaced by a green **Tap To Stop**. Unhandled: saved as `unknown_events/20261110_194207_x10x55_5kx1` (title came from the prize-strip OCR `x10x55.5kx1`). `COIN FLIP … options ['Level', 'Modifiers', 'Tap To Stop'] -> picked Level`. "Tap To Stop" is not in `CONTINUE_BUTTONS` / `EXACT_BUTTONS` (`labels.py:91-98`: only "tap anywhere" / "tap to continue"). The run still finished victory 24 s later (the spinner may auto-stop). The x10 gems on the strip are a prize, not a purchase — the bot did not spend gems.

Fixture: `specs/2.0.5/20261110_194207_x10x55_5kx1.png` (+ `.txt`).

Suggested fix: recognize "Tap To Stop" on a dungeon board and tap that button (never the HUD Level / Modifiers book). Don't use the prize-strip text as an event title. Same HUD blocklist as #9. Do not treat gem/coin prizes on the strip as a shop.

### Acceptance criteria

- The fixture is recognized as a dungeon "Tap To Stop" spinner, not as an unknown event, and the prize-strip OCR (`x10x55.5kx1`) is not used as the event title.
- The bot taps the green "Tap To Stop" button, never the HUD "Level" / "Modifiers" book.
- Gem and coin amounts on the prize strip are not treated as a shop and are never purchased. Never auto-spend gems or gold.
- Offline tests load the fixture and check classification plus the tap target.

---


## 11. Treasure Miner: "no unopened tile, waiting for Leave" while tiles and pickaxes remain; watchdog ends the level; lobby recovery fails

Nov 11, 8:49–9:03 PM ET, SC 17 run 4. Icons stuck at **2** the whole visit (same leftover as #1, the stuck-low case). The dig-change counter still moved 8, 7, …, 2. At 8:50:22 PM, after `changed the tile (2 pickaxes left)`, the bot logged `no unopened tile; waiting for Leave` and sat there. Leave never appeared.

Watchdog at 8:51:22 PM: `back`, then `no back arrow or safe exit`; 8:51:32 PM `exit`, same; 8:54:50 PM `stop` — `screen unchanged for 300s; ending the level`. `go_to_lobby` then failed four times (`specs/2.0.5/fail_20261111_205702.png` and later retries `_210352` not in this folder), `Same error 4 times, giving up`, `Run failed`.

The watchdog / fail frames are the same miner board: "Perfect timing. My arms need a break.", **2 lit pickaxes + 7 dim**, many closed (cracked) tiles still on the grid, **Remaining Treasures: 5**, and **no Leave button**. The grid reader was wrong (centers were a measured board, not fallback, e.g. `(560, 1099)` … `(1147, 1390)`), so it stopped digging while pickaxes and tiles remained. `play.py` miner path only taps Leave when the Leave label is found, or waits when it thinks the board is exhausted (`play.py:934-941`). `go_to_lobby` has no miner Leave / safe-exit path for this screen (`navigation.py:387`).

Fixtures: `specs/2.0.5/watchdog_back_20261111_205121.png`, `specs/2.0.5/watchdog_stop_20261111_205450.png`, `specs/2.0.5/fail_20261111_205702.png`.

Suggested fix: if icons or "Remaining Treasures" show remaining work, do not wait for Leave — reread / fall back to the measured centers and keep digging. Only wait for Leave after the dig counter (or a real 0-icon read) says the pickaxes are gone. If Leave is still missing, treat the miner's "arms need a break" line (or a long wait) as a reason to try a board tap or a safe exit, not a 5-minute hang. `go_to_lobby` should dismiss this event (Leave if present, else a back / close) instead of failing four times.

### Acceptance criteria

- On a board with remaining closed tiles and remaining pickaxes (as in the three fixtures: 2 lit pickaxes, Remaining Treasures 5, no Leave), the bot keeps digging or re-locates the grid. It does not log `no unopened tile; waiting for Leave` and sit until the watchdog stops the level.
- It only waits for Leave when Leave is actually on screen, or after the dig counter (or a real 0-icon read) says the pickaxes are gone.
- A stuck miner is left without a Run failed / Aventura-lobby give-up. `go_to_lobby` dismisses this event (Leave if present, else a back / close / safe exit) instead of failing four times.
- Offline tests load the three fixtures and check that the board is not treated as exhausted.

---

## 12. Tower skip-climb dies with "Tower did not finish" on a Victory / Next screen (Tower of Heroes 201)

Nov 11, 7:07:09–7:33:25 PM ET. After dojo failed, tower started (`challenge (10 tickets)`, one tower cleared, then `challenge (19 tickets)`). Skip was on. It climbed successfully for ~26 minutes (`Skipping the fight` / `Fight finished: victory` / `Tower: next floor` — 12× `floor cleared`, 205× `next floor`). Then `Routine: tower failed: Tower did not finish` on a **Victory!** screen, "Tower of Heroes 201", with **OK** and **Next** still up (Auto Next Level unchecked). The routine then "Finished the fight before leaving" (another victory) and moved on to dungeon dive.

`routine.py:158-176` loops `while stalls < MAX_MODE_ACTIONS` (`config.py:214`, **40**). `stalls` resets only when `result.saw_fight` is true; otherwise it increments. A long skip-climb, or repeated reads of the same Victory/Next if Next did not start the next floor, can burn that budget while the climb is still succeeding. The comment at `routine.py:149-153` already warns that four 10-floor towers (40 floors) used to trip this.

Fixture: `specs/2.0.5/fail_20261111_193325.png`.

Suggested fix: reset the stall budget on every real floor change (the "Tower of Heroes N" index, or a Next that actually leaves the victory). Do not count a skipped floor that already showed a round/result as a stall. If Victory + Next is on screen when the budget expires, tap Next (or OK after the last floor) and continue, instead of failing the mode. Raise or remove a 40-action cap that is smaller than a 19-ticket skip-climb.

### Acceptance criteria

- A 19-ticket skip-climb can clear many towers without "Tower did not finish" while Next is still a valid advance.
- The fixture (Victory! / Tower of Heroes 201 / OK + Next) is treated as a floor advance, not a mode failure.
- The routine only fails the tower when it is actually stuck (same victory for a long time, no Next/OK).
- Offline tests load the fixture and check that Victory + Next is a continue, not a fatal tower error.

---

## 13. Dojo: "Expected the dojo screen" on the Modes list (0 tickets) after a pause

Nov 11, 7:06:42–7:07:04 PM ET. Routine entered dojo, Brian paused 8 s later and resumed 4 s later, then `Routine: dojo failed: Expected the dojo screen`. The fixture is the **Modes** list, not an inner dojo page: Dojo Battle shows **0 tickets**, Tower has 10, Dive has 2. Tower ran next from that same list and worked.

`dojo()` (`routine.py:205-226`) already skips when `screen.tickets < 1` (`Dojo: no tickets left`), but only after `_wait_for(..., "dojo screen")` (`routine.py:213-214, 962`) has parsed an inner dojo screen. After the pause, parse never matched, so it failed instead of treating the modes list + 0 tickets as a skip. `_open_mode` (`routine.py:638`) may also have returned success before the screen settled.

Fixture: `specs/2.0.5/fail_20261111_190704.png`.

Suggested fix: if `_wait_for` is still on the modes list, treat 0 tickets (or a closed card) as a skip, same as arena. Don't fail the routine. Pause/resume should re-run `_open_mode` or re-read tickets rather than requiring the inner screen on a stale deadline.

### Acceptance criteria

- A 0-ticket dojo on the Modes list (as in the fixture) is logged as "no tickets left" and skipped.
- A short pause on the modes list does not produce "Expected the dojo screen" or a routine error.
- Offline tests load the fixture and check that it is treated as a skip, not a dojo-screen failure.

---

## 14. Guild vault cinematic blocks lobby recovery after "no free daily personal claim"

Nov 11, 7:46:44–7:48:02 PM ET. `Guild vault: opening`, then `no free daily personal claim` at 7:47:06, then 56 s later `Routine: could not get back to the lobby after vault: Could not reach the Aventura lobby`. The fixture is a full-screen **open-safe animation** (gold light, no buttons, no footer, no back arrow). After the error the bot logged `Leaving the guild` twice and started SC 17 — farm continued. No gem spend.

`vault()` (`routine.py:577-604`) taps the building, waits for a personal-claim button or the personal-vault title, then `_leave_guild()` (`routine.py:606-618`), which only backs out while `guild_screen` is true. This cinematic is not a lobby and may not look like the guild map, so recovery falls through to `go_to_lobby` and dies on a screen with no close control (`navigation.py:387`).

Fixture: `specs/2.0.5/fail_20261111_194801.png`.

Suggested fix: after "no free claim" (and after a claim), wait out or tap through the vault cinematic before leaving. If `go_to_lobby` sees this animation, wait for it to finish or tap the center; don't start the four-retry Aventura failure. Still never tap a gem claim.

### Acceptance criteria

- A vault visit with no free claim returns to the lobby without a routine error.
- The cinematic fixture is not a "Could not reach the Aventura lobby" give-up. The bot waits it out or taps the center, then leaves.
- Gem prices stay untapped. Never auto-spend gems or gold.
- Offline tests load the fixture and check that it is recognized as the vault cinematic, not a fatal lobby-recovery failure.

---

## 15. Fight start frames are saved as unknown events; coin flip can tap SHOP or skill-tray labels

Three times overnight, a Round 1/30 fight was not classified as a battle (`world2.py:1178-1184` looks for `round … d+/d+`). OCR turned "Round 1/30" into **"Round 1730"**, or used a pet HP bar as the event title:

- 12:42:06 AM Nov 11: saved as `12.1m(8.7m)` (pet HP under the player), `no safe option; waiting`. Fight ended on its own 14 s later. Fixture: `specs/2.0.5/20261111_004206_12_1m_8_7m.png` (+ `.txt`).
- 12:44:58 AM: saved as `23.6m(9.4m)`; **`COIN FLIP … options ['SHOP'] -> picked SHOP`**, tap `(1019, 2288)` — the SHOP label on the dimmed board behind the skill tray. The fight still ended; a skill pick followed 17 s later. Fixture: `specs/2.0.5/20261111_004457_23_6m_9_4m.png` (+ `.txt`).
- 1:09:04 AM: saved as `Round 1730`; **`COIN FLIP … options ['BOSS in', 'roiis'] -> picked BOSS in`**, tap `(608, 2029)` — garbled names in the skill tray. Won the run shortly after. Fixture: `specs/2.0.5/20261111_010904_round_1730.png` (+ `.txt`).

`is_battle` must not depend on a perfect slash in "Round 1/30". Coin flip should never run on a fight (skill tray, enemy HP, or a SHOP building behind the combat UI).

Suggested fix: treat a fight as a battle when "Round" + a 1/30-style counter is present (including "Round 1730"), or when the player/enemy HP bars and the skill tray are up. Never coin-flip those frames; wait them out. Add "SHOP" (a board label, not a choice) to the HUD / coin-flip blocklist during combat.

### Acceptance criteria

- All three fixtures are classified as a battle, never saved as an unknown event, and never receive a coin-flip tap on SHOP or a skill-tray label.
- "Round 1730" (OCR of "Round 1/30") and pet-HP titles like `12.1m(8.7m)` / `23.6m(9.4m)` are not treated as event titles.
- The bot waits for the fight or the next skill pick.
- Offline tests load all three fixtures and check battle classification plus the SHOP / skill-tray blocklist.

---

### Recurrences of #1–#10 (not new items)

- **#1** Miner icon count still overrides the dig counter. Stuck-at-9 and digging after `0 pickaxes left` again, including the two visits that opened Skill Info and became #6 crashes (10:55–10:56 PM Nov 10; 6:08–6:09 AM Nov 11). The #11 visit is the stuck-at-2 form (icons stayed 2 while the dig counter went 8…2), same as the 5:15 PM Nov 10 visit already noted under #1.
- **#2** Off-board miner tap `dig (2, 6) (2 pickaxes left) -> tap (1303, 1244)` at 4:06:03 PM ET Nov 11. No `grid step off … using fallback` line.
- **#4** Zoomed / mid-walk boards still saved as `after_event` (16 times in this window, 11:39 PM Nov 10 through 12:03 AM Nov 12). Not hangs.
- **#6** Skill Info over "Tap anywhere to claim" after miner, continue `(719, 2380/2381)` misses the ✕, then four Aventura-lobby fails, Run failed. **Twice more:** 10:56:25–10:59:54 PM Nov 10 (Skill Info for **Venom Burst**, `specs/2.0.5/play_20261110_225625.png`; later fail frames `_225718`…`_225954` were not in the capture set) and 6:09:08–6:12:11 AM Nov 11 (Skill Info for **Undying**, `specs/2.0.5/play_20261111_060908.png`; later fail frames `_060953`…`_061211` were not in the capture set). Same close-button miss as before (`close_button` none, `close_button_any_size` finds the ✕).
- **#8** Combo Mastery rerolled four more times: 2:03:06 AM, 2:21:52 AM, 4:19:23 PM, 4:29:13 PM ET Nov 11 (`specs/2.0.5/20261111_020306.png`, `specs/2.0.5/20261111_161923.png`, each + `.txt`). Raid at 7:45:47 PM rerolled an offer that already had PoisonShuriken (same `offer_is_unfavorable` whole-offer rule). Follow-up-Strike (11:41:40 PM Nov 10) and Weapon-Mastery (several, e.g. 10:40 PM, 11:50 PM, 1:02 AM, 3:04 AM, 4:48 PM) are the #5 ranking, not protected core.
- **#9** Dungeon Level Modifiers coin-flip again at 7:33:52 PM (picked HUD **Modifiers**, recovered with Continue 2 s later) and 7:37:33 PM (picked Continue). At 7:35:08 PM a mid-dive board (`Depth: 1/3`, faded Tap To Stop) was saved as `depth_1_3_1_4m` and the flip picked HUD **Level** (`specs/2.0.5/20261111_193352_level_modifiers.png`, `specs/2.0.5/20261111_193508_depth_1_3_1_4m.png`, each + `.txt`). Both dives still won.
- **#10** "Tap To Stop" still unhandled, but this time it was the only coin-flip option and was picked correctly: 2:53:55 AM and 5:55:42 PM (**Elite Enemy incoming** on a star-challenge board — new flavor, `specs/2.0.5/20261111_025355_eliteenemy.png` + `.txt`) and 4:10:02 AM (prize-strip title `MaxHP +11%`, `specs/2.0.5/20261111_041002_maxhp_11.png` + `.txt`).

Minor leftovers: World 2 **DEFEAT** banner with "Chapter 13" and no Continue was saved as unknown at 3:01:37 AM, then correctly finished as defeat 2 s later (`specs/2.0.5/20261111_030137_chapter_13.png` + `.txt`). Bandits "event stuck" at 5:59:39 AM recovered immediately. `New skill: Sern` at 7:46:09 PM (raid fade) and `New skill: Outbreak-Lv-2+` (level suffix kept in the name) are more catalog junk, same family as 2.0.4 #11. Vendor unknown lines are the same five already listed; no new curse/blessing text. Weights still held for Game. Inn / trash / revives-disabled / black-market second sentence / pets-disabled still unweighted.

Trash as a skill already worked on Nov 10 (`Skill: Trash (only choice)`; fixture `specs/2.0.5/20261110_180638_trash.png` + `.txt`). Reference vendor captures from that evening, not new work: `specs/2.0.5/20261110_180607_the_next_mythic_skill_you_learn_becomes.png` and `specs/2.0.5/20261110_184713_revives_are_disabled.png`.

---

## New data to add

For Codex to add to `data/` (curse/blessing **weights stay TODO**, pending Game). No new Cursed Vendor *lines* this window — only recurrences of lines already captured on Nov 10. No `boons/` or `new_cursed_vendor/` files after 9:15 PM Nov 10.

### Skills (add under the clean name)

- **Serpent Stance** (mythic, venom, physical, damage). "Dealing any form of non-poison damage will apply 1 stack of Poison on the enemy." Shop offer at 3:46:25 AM ET Nov 11; not bought (285 coins, 283 on hand). Fixture: `specs/2.0.5/20261111_034625_serpentstance.png` (+ `.txt`).
- **Outbreak** (legendary, venom, physical, damage). "At round 3, apply Poison 15 times on all enemies." Seen as **Outbreak Lv. 2+** on a POWER UP pick at 5:36:04 AM ET Nov 11. Add as `outbreak`, not `Outbreak-Lv-2+`. Fixture: `specs/2.0.5/20261111_053604_outbreaklv.png` (+ `.txt`).

### Cursed Vendor lines already known (recurrence counts in this window only)

Exact text as logged (`W2 cursed vendor unknown line:`):

- `revives are disabled` ×11
- `the next mythic skill you learn becomes trash` ×10
- `every campfire becomes an inn (full heal + upgrade 2 skills)` ×9
- `you always stop at a black market` ×8
- `your pets are disabled for the first 3 rounds in every battle` ×5

One vendor coin flip at 1:41:19 AM ET Nov 11: known weights tied (0 vs 0) on unknown inn vs revives-disabled, picked left. Expected while those lines stay unweighted.

### Other screen text worth teaching (handlers, not weight tables)

- Treasure Miner speech: "Perfect timing. My arms need a break." (see #11; Leave is not on this frame).
- Board event: **"Elite Enemy incoming"** + green **Tap To Stop** (see #10 recurrence).
- Dungeon / board HUD book: "Level" / "Modifiers" (see #9).
- Defeat banner: **"DEFEAT"** with a **"Chapter N"** tag and no Continue button on the first frame.
