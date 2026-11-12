# 2.0.5 bug list

From Brian's 2.0.4 live tests on Nov 10, 2026 (America/New_York). Source baseline is `main` at `91a01cdf` (release 2.0.4). Fixtures in this folder are referenced as `specs/2.0.5/<file>`. Afternoon session 3:35–5:36 PM: 15 runs, no hangs, no gem/gold spend, no core skill rerolled away. Evening sessions 5:50–9:18 PM added items #6–#10. Daily Rewards worked in the evening (Claim Now → Collect → free spin → "you won" → Android back ×2).

This list may still grow from later 2.0.4 logs before implementation starts. Implement every numbered item, including §5a. Leftovers at the end are reference only: do not invent curse/blessing weights, and do not treat them as in-scope work.

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

## Leftovers (not in-scope items)

Zooms / mid-walk boards still saved as `after_event` in later evening captures (`20261110_175334_after_event`, `20261110_184247_after_event`) are the same class as #4, not a hang. Follow-up Strike / Weapon Mastery rerolls wait on the #5 poison ranking. `New skill: Wean` at 7:17:55 PM (dojo fade) is more catalog junk, same family as 2.0.4 #11. Inn / "revives are disabled" / "always stop at a black market" / "next Mythic becomes Trash" still log as unknown vendor lines; curse/blessing weights stay held — do not invent weights.

Trash as a skill already worked (`Skill: Trash (only choice)` at 6:06:38, 7:57:49, and 9:07:17 PM; fixture `specs/2.0.5/20261110_180638_trash.png` + `.txt`). Reference vendor captures, not new work: `specs/2.0.5/20261110_180607_the_next_mythic_skill_you_learn_becomes.png` (signed the trash-curse / black-market card) and `specs/2.0.5/20261110_184713_revives_are_disabled.png` (signed left: elite HP down + revives disabled, vs inn + half skills disabled).
