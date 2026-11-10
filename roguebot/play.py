"""In-level loop: roll dice, let fights play, pick skills, until the level ends.

Mode-agnostic: normal and elite levels share the same gameplay.
"""

import logging
import time
from dataclasses import replace
from pathlib import Path

import cv2

from roguebot import config, labels, settings
from roguebot.build import Build, BuildState, choose, shop_order
from roguebot.device import Device
from roguebot.screens import (LevelScreen, LevelState, SkillCard, campfire_non_heal_tap, classify_level_screen,
                              game_speed, monk_spin_button, parse_fortune_teller, parse_shop, parse_skill_cards,
                              skill_reroll)
from roguebot.skills import Catalog, Skill, infer_tags
from roguebot.vision import Ocr, find
from roguebot import world2

log = logging.getLogger(__name__)

DEBUG_DIR = Path("debug")
MAX_SHOP_STEPS = 16  # refreshes + purchases in one shop visit


def refresh_leaves_a_buy(money: int, cost: int, wanted_costs: list[int],
                         floor: int = config.SHOP_SKILL_FLOOR) -> bool:
    """True when paying `cost` still leaves a wanted skill buyable.

    A free refresh (cost 0) always passes. If a wanted skill is already affordable, the
    coins left must still cover the cheapest of those: refreshing must not spend the
    money that would buy it. If none is affordable yet, keep enough for the cheapest
    skill a shop rolls (`floor`) so a later wanted card can be bought.
    """
    if cost <= 0:
        return money >= 0
    if money < cost:
        return False
    after = money - cost
    affordable = [c for c in wanted_costs if c <= money]
    if affordable:
        return after >= min(affordable)
    return after >= floor


class PlayError(Exception):
    pass


def _same_tap(a, b) -> bool:
    """Same screen kind and (nearly) the same point: OCR jitters text centers by a few pixels."""
    return (b is not None and a[0] is b[0]
            and abs(a[1][0] - b[1][0]) <= config.SAME_TAP_TOLERANCE and abs(a[1][1] - b[1][1]) <= config.SAME_TAP_TOLERANCE)


class Player:
    def __init__(self, device: Device, ocr: Ocr, build: Build = Build(), catalog: Catalog | None = None,
                 ads: bool = False, level_title: str | None = None):
        self.device = device
        self.ads = ads  # watch ads (x2 rewards, free revive); only with an account that skips them
        self.ocr = ocr
        self.build = build
        self.catalog = catalog if catalog is not None else Catalog()
        self._state = BuildState()   # skills taken in the current level
        self._rerolled = False       # the skill pick on screen is already the rerolled one
        self._doubles = 0            # x2 rewards taps at this level end
        self._last_offer = None      # names of the last skill pick decided (a repeat = the tap did not land)
        self._speed_tapped = False  # tapped x1 -> x2 and waiting to see the label change
        self._speed_locked = False  # x2 is not unlocked on this account
        self._auto_held = False     # held the dice for auto-play and not seen it on yet
        self._auto_missing = False  # a hold brought the red dice back: no auto-play here, tap instead
        self._auto_seen = False     # auto-play worked in this level: a hold that brings the red dice back was missed
        self._auto_misses = 0       # such missed holds in a row
        self._fortune_bought = []   # Fortune Teller balls bought this visit (chances)
        self._fortune_tap = None    # (chance, orbs before, time) of the last ball tap, until the orbs drop
        self._monk_spins = 0        # Wise Monk spins whose reward was claimed this visit
        self._monk_armed: float | None = None  # when the current spin was tapped; cleared when its reward is claimed
        self._monk_leave_since: float | None = None  # Salir showed while a spin was still owed
        self._monk_since: float | None = None  # start of the current unresolved Monk wait
        self._monk_retapped = False  # the in-flight spin was tapped a second time (the first one missed)
        self._monk_yielded = False  # timed out: the generic level loop owns this screen
        self._campfire_waits = 0  # frames the upgrade label was missing at HP that must not heal
        self._x4_available = False  # seen x4 this session; a missing badge does not clear it
        self._speed_cycle: list[int] = []
        self._speed_pending: int | None = None  # label we just tapped; unchanged next read = the button did nothing
        self._speed_steps = 0
        self._event_bailed = False
        self._event_stuck_tap = None
        self._event_alts: list[tuple[int, int]] = []
        self._rolls = world2.RollTracker()
        self._board = world2.board_from_title(level_title)
        self._clearing_since: float | None = None  # after an event choice, tap through until the map
        self._miner = None  # 7x7 board, kept for the whole level (later visits refill pickaxes)
        self._miner_centers = None
        self._miner_used = 0
        self._open_chest = False  # goblin raid: the blue chest is still closed
        self._unknown_saved: set[str] = set()
        self._min_skill_price = config.SHOP_SKILL_FLOOR

    def play_level(self) -> LevelScreen:
        """Play until the level ends; returns LevelScreen.VICTORY or LevelScreen.DEFEAT."""
        last_known = time.monotonic()
        last_tap, repeats, first_repeat = None, 0, time.monotonic()
        self._state, self._rerolled, self._doubles, self._last_offer = BuildState(), False, 0, None
        self._fortune_bought, self._fortune_tap = [], None
        self._reset_monk()
        self._campfire_waits = 0
        self._miner, self._miner_centers, self._miner_used = None, None, 0
        self._clearing_since, self._open_chest = None, False
        self._unknown_saved = set()
        # A false "speed is locked" must not stick for the session. x4, once seen, does.
        self._speed_locked = False
        self._speed_cycle = []
        self._speed_pending = None
        self._speed_steps = 0
        self._event_bailed = False
        self._event_stuck_tap = None
        self._event_alts = []
        self._rolls.reset()
        while True:
            img = self.device.screenshot()
            texts = self.ocr.read(img)
            self._rolls.observe(texts)
            state = classify_level_screen(img, texts, self._core_build(), self._board, None,
                                           self._min_skill_price, rolls=self._rolls.cached())
            if world2.vendor_needs_shot(world2.LAST):
                self._save_unknown(img, texts, "cursed_vendor")
            state = self._world2(img, texts, state)
            log.debug("screen: %s", state.kind.value)
            raw_kind = state.kind

            if raw_kind is LevelScreen.SKILL_PICK:
                state = LevelState(state.kind, self._pick_skill(texts) or state.tap)
            elif raw_kind is LevelScreen.SHOP:
                self._shop(texts)  # buys what the build wants and the coins allow; then state.tap exits
            elif raw_kind is LevelScreen.FORTUNE_TELLER:
                state = LevelState(state.kind, self._fortune(texts))
            elif raw_kind is LevelScreen.MONK and not self._monk_yielded:
                tap = self._monk_tap(texts, img)
                if self._monk_yielded and tap is None and state.tap is None:
                    state = LevelState(LevelScreen.UNKNOWN)  # nothing to tap: the unknown-screen guard applies
                elif not (self._monk_yielded and tap is None):
                    state = LevelState(LevelScreen.MONK, tap)
                # yielded with no handler tap but the classifier found SPIN/Leave: that tap is the recovery
            elif raw_kind is LevelScreen.MONK and state.tap is None:
                state = LevelState(LevelScreen.UNKNOWN)
            elif raw_kind in (LevelScreen.BOARD_READY, LevelScreen.AUTO_PLAY):
                self._fortune_bought = []  # back on the board: a later Fortune Teller is a new visit
                self._reset_monk()
            if raw_kind is not LevelScreen.MONK:
                self._monk_yielded = False

            if state.kind is LevelScreen.DOUBLE_REWARD:
                self._doubles += 1
                proceed = find(texts, labels.CONTINUE, exact=True)
                # No ads, or the x2 button stays after the tries: just continue
                if (not self.ads or self._doubles > config.DOUBLE_REWARD_TRIES) and proceed:
                    state = LevelState(LevelScreen.CONTINUE, proceed.center)
                elif not self.ads:  # Continue not read yet: never the ad button. Unknown, so the stuck guard applies
                    state = LevelState(LevelScreen.UNKNOWN)
            elif state.kind is LevelScreen.REVIVE and not self.ads:
                state = LevelState(LevelScreen.UNKNOWN)  # the free revive is a video: let the 10 s countdown run out

            if state.kind in (LevelScreen.BOARD_READY, LevelScreen.AUTO_PLAY) and self._ensure_double_speed(texts):
                continue
            if state.kind is LevelScreen.AUTO_PLAY and self._auto_held:
                log.info("Auto-play on")
                self._auto_held, self._auto_seen, self._auto_misses = False, True, 0
            elif state.kind is LevelScreen.BOARD_READY and self._auto_held:
                self._auto_held, self._auto_misses = False, self._auto_misses + 1
                if self._auto_seen and self._auto_misses < config.AUTO_PLAY_RETRIES:
                    log.info("Holding the dice did not start auto-play this time; holding again")
                else:
                    log.info("Holding the dice did not start auto-play; rolling by taps")
                    self._auto_missing = True

            if state.kind is LevelScreen.EVENT and state.tap is None and not world2.is_miner(texts):
                # The upgrade label was not on this frame. Reading the campfire in the same
                # breath as the previous screen (a skill pick dismissing) used to see only
                # "Descansar" and heal at 100% HP. Wait, then take the non-heal side.
                self._campfire_waits += 1
                if self._campfire_waits <= config.CAMPFIRE_REREADS:
                    log.info("Campfire: skill upgrade not readable, rereading (%d)", self._campfire_waits)
                    time.sleep(config.POLL_INTERVAL)
                    continue
                fallback = campfire_non_heal_tap(img, texts)
                self._campfire_waits = 0
                if fallback is None:
                    log.info("Campfire: no non-heal option; not restoring HP")
                    time.sleep(config.POLL_INTERVAL)
                    continue
                log.info("Campfire: upgrade still unreadable; choosing the non-heal option")
                state = LevelState(LevelScreen.EVENT, fallback)
            else:
                self._campfire_waits = 0

            if state.kind in (LevelScreen.VICTORY, LevelScreen.DEFEAT):
                log.info("Level finished: %s", state.kind.value)
                self.device.tap(*state.tap)
                return state.kind

            if state.kind is LevelScreen.UNKNOWN:
                # After an event choice, keep tapping through dialogue and claim screens.
                # A guild map or anything else with no event behind it still fails closed.
                if (self._clearing_since is not None
                        and time.monotonic() - self._clearing_since >= config.EVENT_CLEAR_TIMEOUT):
                    self._save_unknown(img, texts, "after event")
                    log.warning("Event follow-up still up; tapping through")
                    state = LevelState(LevelScreen.CONTINUE, config.EVENT_CLEAR_TAP)
                    self._clearing_since = time.monotonic()
                elif time.monotonic() - last_known > config.UNKNOWN_SCREEN_TIMEOUT and self._clearing_since is None:
                    self._fail("Stuck on an unknown screen", img)
            else:
                last_known = time.monotonic()

            if state.tap:
                if _same_tap((state.kind, state.tap), last_tap):
                    repeats += 1
                else:
                    repeats, first_repeat = 1, time.monotonic()
                last_tap = (state.kind, state.tap)
                stuck = getattr(self, "_event_stuck_tap", None)
                if (self._event_bailed and state.kind is LevelScreen.EVENT and stuck is not None
                        and _same_tap((state.kind, state.tap), (state.kind, stuck))):
                    point = self._event_alts.pop(0) if self._event_alts else None
                    if point is None:
                        log.info("W2 event still on the tap that did nothing; waiting")
                        last_tap, repeats = None, 0
                        time.sleep(config.POLL_INTERVAL)
                        continue
                    log.info("W2 event still on the tap that did nothing; trying %s", point)
                    state = LevelState(LevelScreen.EVENT, point)
                    repeats, first_repeat = 1, time.monotonic()
                    last_tap = (state.kind, state.tap)
                if state.kind is LevelScreen.EVENT and repeats >= 3 and not self._event_bailed:
                    self._event_bailed = True
                    self._event_stuck_tap = state.tap
                    self._event_alts = world2.recovery_taps(texts, state.tap)
                    self._save_unknown(img, texts, "event stuck")
                    if self._event_alts:
                        point = self._event_alts.pop(0)
                        log.info("W2 event had no effect; trying %s", point)
                        state = LevelState(LevelScreen.EVENT, point)
                        repeats, first_repeat = 1, time.monotonic()
                        last_tap = (state.kind, state.tap)
                    else:
                        log.info("W2 event had no effect; waiting")
                        last_tap, repeats = None, 0
                        time.sleep(config.POLL_INTERVAL)
                        continue
                if repeats > config.MAX_REPEATED_TAPS and time.monotonic() - first_repeat > config.STUCK_TAP_SECONDS:
                    self._fail(f"Tapping {state.tap} on {state.kind.value} has no effect", img)
                if state.kind is LevelScreen.EVENT:
                    self._clearing_since = time.monotonic()
                if state.kind is LevelScreen.BOARD_READY and not self._auto_missing:
                    log.info("board_ready -> hold %s for auto-play", state.tap)
                    self.device.hold(*state.tap, config.AUTO_PLAY_HOLD)
                    self._auto_held = True
                    self._rolls.note_roll()
                else:
                    log.info("%s -> tap %s", state.kind.value, state.tap)
                    self.device.tap(*state.tap)
                    if state.kind is LevelScreen.BOARD_READY:
                        self._rolls.note_roll()
            else:
                last_tap, repeats = None, 0  # screen changed on its own: the last tap worked
                time.sleep(config.POLL_INTERVAL)

    def _skill(self, card: SkillCard) -> Skill:
        """Catalog entry for this card. A user-locked tag (auto false) wins; otherwise a damage type
        read on the card itself wins over a stale saved tag, so a skill named shuriken is shuriken."""
        known = self.catalog.lookup(card.name, card.description, card.rarity, labels.active_language())
        if not known.auto:
            return known
        damage_type, nature, role = infer_tags(card.name, card.description)
        if damage_type and damage_type != known.damage_type:
            log.info("Skill %s read as %s from its card (saved tag %s)", card.name, damage_type,
                     known.damage_type or "-")
            return replace(known, damage_type=damage_type, nature=nature, role=role)
        return known

    def _pick_skill(self, texts) -> tuple[int, int] | None:
        """Tap point of the card the build wants, or of the reroll button. None if no card was read."""
        wide = (80, 720) if find(texts, labels.SKILL_PROMPT) else None
        cards = parse_skill_cards(texts, wide)
        if not cards:
            return None
        skills = [self._skill(c) for c in cards]
        reroll = skill_reroll(texts)
        i = choose(skills, self.build, self._state, can_reroll=reroll is not None and not self._rerolled)
        if i is None:
            log.info("No wanted skill in %s: rerolling", [s.name for s in skills])
            self._rerolled = True
            return reroll.center
        self._rerolled = False
        offer = tuple(s.name for s in skills)
        if offer != self._last_offer:  # the same offer again = the last tap did not land: count it once
            self._state.take(skills[i])
        self._last_offer = offer
        log.info("Skill: %s (%s, %s, %s); cards %s", skills[i].name, skills[i].rarity,
                 skills[i].damage_type or "-", skills[i].role,
                 [f"{s.name}:{s.damage_type or '-'}" for s in skills])
        return config.SCREEN_SIZE[0] // 2, cards[i].tag.center[1] + config.SKILL_TAP_BELOW_RARITY

    def _shop(self, texts) -> None:
        """Buy wanted skills the coins can pay, refreshing to find one while a refresh stays safe.

        An already-affordable wanted skill is bought before any refresh. A refresh (free, then
        paid, more than once) is used only when it leaves enough coins for a wanted skill.
        """
        tapped, free_used = set(), False
        for _ in range(MAX_SHOP_STEPS):
            shop = parse_shop(texts)
            if shop is None or shop.money is None:
                return
            cards = [c for c in shop.cards if not c.sold and c.cost is not None and c.name not in tapped]
            skills = [self._skill(c) for c in cards]
            preferred = shop_order(skills, self.build, self._state, can_reroll=True, fill=False)
            if preferred:
                affordable = [i for i in preferred if cards[i].cost <= shop.money]
                if affordable:
                    self._buy(shop, cards, skills, affordable[0], tapped)
                elif not self._refresh_shop(shop, [cards[i].cost for i in preferred], free_used):
                    return
                else:
                    free_used = free_used or shop.free_reroll is not None
            elif self._refresh_shop(shop, [], free_used):
                free_used = free_used or shop.free_reroll is not None
            else:
                fallback = shop_order(skills, self.build, self._state, can_reroll=False, fill=False) or []
                affordable = [i for i in fallback if cards[i].cost <= shop.money]
                if not affordable:
                    return
                self._buy(shop, cards, skills, affordable[0], tapped)
            texts = self.ocr.read(self.device.screenshot())

    def _buy(self, shop, cards, skills, i: int, tapped: set) -> None:
        log.info("Shop: buying %s (%s) for %d (coins %d)", skills[i].name,
                 skills[i].damage_type or skills[i].role, cards[i].cost, shop.money)
        self.device.tap(*cards[i].price.center)
        tapped.add(cards[i].name)
        self._state.take(skills[i])

    def _refresh_shop(self, shop, wanted_costs: list[int], free_used: bool) -> bool:
        """Tap the reroll when it is free, or when paying for it still leaves a wanted buy."""
        if shop.free_reroll is not None and not free_used:
            log.info("Shop: no affordable wanted skill, free refresh")
            self.device.tap(*shop.free_reroll.center)
            return True
        if shop.reroll is None or shop.reroll_cost is None or shop.money is None:
            return False
        if not refresh_leaves_a_buy(shop.money, shop.reroll_cost, wanted_costs):
            log.info("Shop: refresh (%d) would leave too few coins (have %d)", shop.reroll_cost, shop.money)
            return False
        log.info("Shop: refresh for %d (coins %d)", shop.reroll_cost, shop.money)
        self.device.tap(*shop.reroll.center)
        return True

    def _fortune(self, texts) -> tuple[int, int] | None:
        """Fortune Teller: buy the balls in FORTUNE_BUYS order while the orbs allow, then the back arrow.
        A buy counts once the orb counter drops (a missed tap is tapped again); None = wait for it."""
        teller = parse_fortune_teller(texts)
        if self._fortune_tap:
            chance, orbs, tapped = self._fortune_tap
            if teller.orbs is not None and teller.orbs < orbs:
                self._fortune_bought.append(chance)
            elif time.monotonic() - tapped < config.FORTUNE_RETAP_AFTER:
                return None
            self._fortune_tap = None
        if teller.orbs is not None:
            for chance, times in config.FORTUNE_BUYS:
                if (self._fortune_bought.count(chance) < times and chance in teller.balls
                        and teller.orbs >= config.FORTUNE_COST[chance]):
                    log.info("Fortune Teller: %d%% ball (orbs %d)", chance, teller.orbs)
                    self._fortune_tap = chance, teller.orbs, time.monotonic()
                    return teller.balls[chance]
        return config.FORTUNE_TELLER_BACK

    def _reset_monk(self) -> None:
        self._monk_spins, self._monk_armed, self._monk_leave_since = 0, None, None
        self._monk_since, self._monk_retapped, self._monk_yielded = None, False, False

    def _monk_claim(self, texts) -> tuple[int, int] | None:
        """The reward overlay after a spin ("Tap anywhere to claim" / "You Received")."""
        claim = find(texts, labels.TAP_TO_CLAIM)
        if claim is not None:
            return claim.center
        if find(texts, labels.MONK_REWARD) is not None:
            return config.SCREEN_SIZE[0] // 2, config.SCREEN_SIZE[1] // 2
        return None

    def _monk_wait(self, img, texts, message: str) -> tuple[int, int] | None:
        """One frame of a Monk wait. Past MONK_WAIT_TIMEOUT, recover instead of returning None forever."""
        now = time.monotonic()
        if self._monk_since is None:
            self._monk_since = now
        if now - self._monk_since >= config.MONK_WAIT_TIMEOUT:
            return self._monk_give_up(img, texts)
        log.info(message)
        return None

    def _monk_give_up(self, img, texts) -> tuple[int, int] | None:
        """The wait never ended. Warn, keep a screenshot, tap a reward or Leave if one is readable,
        and hand the screen back to the level loop (unknown-screen / repeated-tap guards)."""
        waited = 0.0 if self._monk_since is None else time.monotonic() - self._monk_since
        log.warning("Wise Monk: timed out after %.0fs with %d/%d spins claimed; recovering",
                    waited, self._monk_spins, config.MONK_SPINS)
        if img is not None:
            DEBUG_DIR.mkdir(exist_ok=True)
            path = DEBUG_DIR / f"monk_{time.strftime('%Y%m%d_%H%M%S')}.png"
            cv2.imwrite(str(path), img)
            log.warning("Wise Monk: saved %s", path)
        self._monk_yielded = True
        self._monk_armed = None
        self._monk_since = None
        self._monk_leave_since = None
        self._monk_retapped = False
        claim = self._monk_claim(texts)
        if claim is not None:
            log.info("Wise Monk: recovery tap on the reward")
            return claim
        cont = find(texts, labels.TAP_TO_CONTINUE) or find(texts, labels.CONTINUE, exact=True)
        if cont is not None:
            log.info("Wise Monk: recovery tap to continue")
            return cont.center
        leave = find(texts, labels.LEAVE, exact=True)
        if leave is not None:
            log.info("Wise Monk: recovery tap on Leave")
            return leave.center
        log.info("Wise Monk: no reward or Leave to tap; back to screen detection")
        return None

    def _monk_tap(self, texts, img=None) -> tuple[int, int] | None:
        """Wise Monk: spin twice, claim each reward, then leave. HP is never a reason to stop early.

        A spin counts only when its reward overlay is tapped, so the next spin cannot start
        on the assumption that the previous one finished. The button still being there after
        MONK_SPIN_SETTLE means the tap missed: it is tapped once more and still not counted.
        The button leaving the screen means the wheel is spinning; that is not a finished spin.
        Salir before both claims is ignored until the spin button fails to come back.
        Every wait is bounded by MONK_WAIT_TIMEOUT.
        """
        claim = self._monk_claim(texts)
        if claim is not None:
            if self._monk_armed is not None:
                self._monk_spins += 1
                self._monk_armed = None
                log.info("Wise Monk: spin %d/%d done", self._monk_spins, config.MONK_SPINS)
            self._monk_leave_since = None
            self._monk_since = None
            self._monk_retapped = False
            log.info("Wise Monk: claiming the reward")
            return claim
        spin = monk_spin_button(texts)
        leave = find(texts, labels.LEAVE, exact=True)
        if spin is not None and self._monk_spins < config.MONK_SPINS:
            self._monk_leave_since = None
            now = time.monotonic()
            if self._monk_armed is None:
                self._monk_armed = now
                self._monk_since = now
                self._monk_retapped = False
                log.info("Wise Monk: spin %d/%d", self._monk_spins + 1, config.MONK_SPINS)
                return spin.center
            if not self._monk_retapped and now - self._monk_armed >= config.MONK_SPIN_SETTLE:
                self._monk_retapped = True
                self._monk_armed = now
                log.info("Wise Monk: spin %d/%d was not claimed; tapping SPIN again",
                         self._monk_spins + 1, config.MONK_SPINS)
                return spin.center
            return self._monk_wait(img, texts, "Wise Monk: waiting for the reward of spin %d/%d"
                                    % (self._monk_spins + 1, config.MONK_SPINS))
        if leave is not None and self._monk_armed is None and self._monk_spins >= config.MONK_SPINS:
            self._monk_since = None
            return leave.center
        if leave is not None and spin is None:
            if self._monk_leave_since is None:
                self._monk_leave_since = time.monotonic()
            if time.monotonic() - self._monk_leave_since >= config.MONK_LEAVE_WAIT:
                log.info("Wise Monk: spin button did not return (%d/%d claimed); leaving",
                         self._monk_spins, config.MONK_SPINS)
                self._monk_armed = None
                self._monk_since = None
                self._monk_retapped = False
                return leave.center
            return self._monk_wait(img, texts, "Wise Monk: waiting to spin again (%d/%d)"
                                    % (self._monk_spins, config.MONK_SPINS))
        if self._monk_armed is not None:
            return self._monk_wait(img, texts, "Wise Monk: waiting for the reward of spin %d/%d"
                                    % (self._monk_spins + 1, config.MONK_SPINS))
        if self._monk_spins >= config.MONK_SPINS:
            return self._monk_wait(img, texts, "Wise Monk: waiting to leave")
        return self._monk_wait(img, texts, "Wise Monk: waiting to spin again (%d/%d)"
                                % (self._monk_spins, config.MONK_SPINS))

    def _ensure_double_speed(self, texts) -> bool:
        """Cycle the speed button to the highest it offers. Returns True if it tapped.

        x4 is VIP and is not shown by a badge while x1 or x2 is selected, so the only way to
        know is to tap and read the label. Stop when the label reads x4, or when it comes back
        to one already seen (x4 is not on this account) and the current label is the highest of
        those. A tap that does not change the label means the button is not usable this level.
        Seeing x4 once is remembered for the session. A missing badge is not "not unlocked".
        """
        speed = game_speed(texts)
        if speed is None or self._speed_locked:
            return False
        if speed == 4:
            arrived = not self._x4_available or self._speed_pending is not None or bool(self._speed_cycle)
            self._x4_available = True
            self._speed_cycle = []
            self._speed_pending = None
            self._speed_steps = 0
            if arrived:
                log.info("Speed is x4")
            return False
        if self._speed_pending is not None and speed == self._speed_pending:
            self._speed_locked = True
            self._speed_pending = None
            log.info("Speed button did not change from x%s", speed)
            return False
        self._speed_pending = None
        if speed not in self._speed_cycle:
            self._speed_cycle.append(speed)
            return self._tap_speed(speed)
        best = max(self._speed_cycle)
        if self._x4_available and self._speed_steps < 4:
            return self._tap_speed(speed)
        if speed != best:
            return self._tap_speed(speed)
        log.info("Highest speed available is x%s", best)
        self._speed_cycle = []
        self._speed_steps = 0
        return False

    def _tap_speed(self, speed: int) -> bool:
        self._speed_steps += 1
        if self._speed_steps > 6:
            self._speed_locked = True
            log.info("Leaving speed at x%s", speed)
            return False
        self._speed_pending = speed
        log.info("Cycling speed from x%s", speed)
        self.device.tap(*config.SPEED_BUTTON)
        return True

    def _core_build(self) -> Build:
        return world2.active_build(self.build, settings.load())

    def _world2(self, img, texts, state: LevelState) -> LevelState:
        """Miner, unknown events, and the goblin chest. Known events are already in `state`."""
        if world2.is_miner(texts):
            return LevelState(LevelScreen.EVENT, self._miner_tap(img, texts))
        if state.kind in (LevelScreen.BOARD_READY, LevelScreen.AUTO_PLAY):
            if self._clearing_since is not None:
                hud = world2.read_hud(texts)
                log.info("W2 back on the map: hp=%s/%s tokens=%s", hud.hp, hud.max_hp, hud.tokens)
            self._clearing_since = None
            self._miner_used = 0
            self._open_chest = False
            self._event_bailed = False
            self._event_stuck_tap = None
            self._event_alts = []
        if world2.is_shop_screen(texts):
            # The greeting and the item lines look like an event title. Buying happens in _shop;
            # do not hand this frame to the unknown-event catcher (it taps Exit).
            if state.kind is LevelScreen.SHOP:
                return state
            leave = find(texts, labels.LEAVE, exact=True)
            return LevelState(LevelScreen.SHOP, leave.center if leave else state.tap)
        if world2.transient_kind(texts):
            return state
        if world2.match_event(texts) == "goblin" and world2.LAST and world2.LAST.choice == "raid":
            self._open_chest = True
        # Fights, skill picks and path forks are not unknown events. Path choice already
        # happened in classify (level_tap). A battle is waited out. A skill pick is the
        # normal picker, which runs after this returns.
        if world2.ordinary_level_screen(texts):
            return state
        title = world2.event_title(texts)
        if title and not world2.is_known_title(title) and world2.looks_like_event(texts):
            self._save_unknown(img, texts, title)
            leave = world2.safe_leave_label(texts)
            if leave is None:
                log.info("Unknown event %s: no safe option; waiting", title)
                return state
            point = world2.choice_tap(leave, texts)
            if world2.tap_forbidden(point):
                log.info("Unknown event %s: safe option sits on the speed button; waiting", title)
                return state
            log.info("Unknown event %s: %s", title, leave.text)
            return LevelState(LevelScreen.EVENT, point)
        if self._open_chest and state.kind is LevelScreen.UNKNOWN:
            chest = world2.find_blue_chest(img)
            if chest:
                self._open_chest = False
                log.info("Goblin raid: opening the chest")
                return LevelState(LevelScreen.EVENT, chest)
        return state

    def _miner_tap(self, img, texts) -> tuple[int, int] | None:
        leave = find(texts, labels.LEAVE, exact=True)
        if world2.miner_out(texts) and leave:
            log.info("Treasure Miner: out of pickaxes")
            return leave.center
        claim = find(texts, labels.TAP_TO_CLAIM)
        if claim:
            return claim.center
        viewed = world2.read_miner_grid(img)
        if viewed is None:
            self._save_unknown(img, texts, "treasure miner")
            return leave.center if leave else None
        board, centers = viewed
        self._miner = world2.merge_board(self._miner, board)
        self._miner_centers = centers
        nxt = world2.next_miner_tap(self._miner, world2.MINER_PICKAXES - self._miner_used)
        if nxt is None:
            return leave.center if leave else None
        r, c = nxt
        self._miner[r][c] = world2.DUG
        self._miner_used += 1
        log.info("Treasure Miner: dig %s (%d pickaxes left)", nxt, world2.MINER_PICKAXES - self._miner_used)
        return centers[r][c]

    def _save_unknown(self, img, texts, title: str) -> None:
        slug = world2.slug(title)
        if slug in self._unknown_saved:
            return
        self._unknown_saved.add(slug)
        folder = DEBUG_DIR / "unknown_events"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        stem = folder / f"{stamp}_{slug}"
        if img is not None:
            cv2.imwrite(str(stem.with_suffix(".png")), img)
        stem.with_suffix(".txt").write_text("\n".join(t.text for t in texts), encoding="utf-8")
        log.info("Unknown event saved: %s", stem)

    def _fail(self, msg: str, img) -> None:
        DEBUG_DIR.mkdir(exist_ok=True)
        path = DEBUG_DIR / f"play_{time.strftime('%Y%m%d_%H%M%S')}.png"
        cv2.imwrite(str(path), img)
        raise PlayError(f"{msg} (screenshot: {path})")
