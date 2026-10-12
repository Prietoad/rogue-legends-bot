"""In-level loop: roll dice, let fights play, pick skills, until the level ends.

Mode-agnostic: normal and elite levels share the same gameplay.
"""

import logging
import time
from pathlib import Path

import cv2

from roguebot import config, labels
from roguebot.build import Build, BuildState, choose, shop_order
from roguebot.device import Device
from roguebot.screens import (LevelScreen, LevelState, SkillCard, classify_level_screen, game_speed, parse_shop,
                              parse_skill_cards, skill_reroll)
from roguebot.skills import Catalog, Skill
from roguebot.vision import Ocr, find

log = logging.getLogger(__name__)

DEBUG_DIR = Path("debug")
MAX_SHOP_STEPS = 8  # rerolls + purchases in one shop visit


class PlayError(Exception):
    pass


def _same_tap(a, b) -> bool:
    """Same screen kind and (nearly) the same point: OCR jitters text centers by a few pixels."""
    return (b is not None and a[0] is b[0]
            and abs(a[1][0] - b[1][0]) <= config.SAME_TAP_TOLERANCE and abs(a[1][1] - b[1][1]) <= config.SAME_TAP_TOLERANCE)


class Player:
    def __init__(self, device: Device, ocr: Ocr, build: Build = Build(), catalog: Catalog | None = None):
        self.device = device
        self.ocr = ocr
        self.build = build
        self.catalog = catalog if catalog is not None else Catalog()
        self._state = BuildState()   # skills taken in the current level
        self._rerolled = False       # the skill pick on screen is already the rerolled one
        self._doubles = 0            # x2 rewards taps at this level end
        self._last_offer = None      # names of the last skill pick decided (a repeat = the tap did not land)
        self._speed_tapped = False  # tapped x1 -> x2 and waiting to see the label change
        self._speed_locked = False  # x2 is not unlocked on this account

    def play_level(self) -> LevelScreen:
        """Play until the level ends; returns LevelScreen.VICTORY or LevelScreen.DEFEAT."""
        last_known = time.monotonic()
        last_tap, repeats, first_repeat = None, 0, time.monotonic()
        self._state, self._rerolled, self._doubles, self._last_offer = BuildState(), False, 0, None
        while True:
            img = self.device.screenshot()
            texts = self.ocr.read(img)
            state = classify_level_screen(img, texts)
            log.debug("screen: %s", state.kind.value)

            if state.kind is LevelScreen.SKILL_PICK:
                state = LevelState(state.kind, self._pick_skill(texts) or state.tap)
            elif state.kind is LevelScreen.SHOP:
                self._shop(texts)  # buys what the build wants and the coins allow; then state.tap exits

            if state.kind is LevelScreen.DOUBLE_REWARD:
                self._doubles += 1
                proceed = find(texts, labels.CONTINUE, exact=True)
                if self._doubles > config.DOUBLE_REWARD_TRIES and proceed:  # the x2 button stays: just continue
                    state = LevelState(LevelScreen.CONTINUE, proceed.center)

            if state.kind is LevelScreen.BOARD_READY and self._ensure_double_speed(texts):
                continue

            if state.kind in (LevelScreen.VICTORY, LevelScreen.DEFEAT):
                log.info("Level finished: %s", state.kind.value)
                self.device.tap(*state.tap)
                return state.kind

            if state.kind is LevelScreen.UNKNOWN:
                if time.monotonic() - last_known > config.UNKNOWN_SCREEN_TIMEOUT:
                    self._fail("Stuck on an unknown screen", img)
            else:
                last_known = time.monotonic()

            if state.tap:
                if _same_tap((state.kind, state.tap), last_tap):
                    repeats += 1
                else:
                    repeats, first_repeat = 1, time.monotonic()
                last_tap = (state.kind, state.tap)
                if repeats > config.MAX_REPEATED_TAPS and time.monotonic() - first_repeat > config.STUCK_TAP_SECONDS:
                    self._fail(f"Tapping {state.tap} on {state.kind.value} has no effect", img)
                log.info("%s -> tap %s", state.kind.value, state.tap)
                self.device.tap(*state.tap)
            else:
                last_tap, repeats = None, 0  # screen changed on its own: the last tap worked
                time.sleep(config.POLL_INTERVAL)

    def _skill(self, card: SkillCard) -> Skill:
        return self.catalog.lookup(card.name, card.description, card.rarity, labels.active_language())

    def _pick_skill(self, texts) -> tuple[int, int] | None:
        """Tap point of the card the build wants, or of the reroll button. None if no card was read."""
        cards = parse_skill_cards(texts)
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
        log.info("Skill: %s (%s, %s, %s)", skills[i].name, skills[i].rarity, skills[i].damage_type or "-",
                 skills[i].role)
        return config.SCREEN_SIZE[0] // 2, cards[i].tag.center[1] + config.SKILL_TAP_BELOW_RARITY

    def _shop(self, texts) -> None:
        """Free reroll if nothing is wanted, then buy in the build's order whatever the coins allow."""
        rerolled, tapped = False, set()
        for _ in range(MAX_SHOP_STEPS):
            shop = parse_shop(texts)
            if shop is None or shop.money is None:
                return
            cards = [c for c in shop.cards if not c.sold and c.cost is not None and c.name not in tapped]
            skills = [self._skill(c) for c in cards]
            order = shop_order(skills, self.build, self._state,
                               can_reroll=shop.free_reroll is not None and not rerolled)
            if order is None:
                log.info("Shop: no wanted skill in %s, free reroll", [s.name for s in skills])
                self.device.tap(*shop.free_reroll.center)
                rerolled = True
            else:
                i = next((i for i in order if cards[i].cost <= shop.money), None)
                if i is None:
                    return
                log.info("Shop: buying %s for %d (coins %d)", skills[i].name, cards[i].cost, shop.money)
                self.device.tap(*cards[i].price.center)
                tapped.add(cards[i].name)
                self._state.take(skills[i])
            texts = self.ocr.read(self.device.screenshot())

    def _ensure_double_speed(self, texts) -> bool:
        """Switch the game to x2 speed when it shows x1. Returns True if it tapped."""
        speed = game_speed(texts)
        if speed != 1 or self._speed_locked:
            self._speed_tapped = False
            return False
        if self._speed_tapped:  # tapped last time and still x1
            log.info("x2 speed is not unlocked on this account; playing at x1")
            self._speed_locked = True
            return False
        log.info("Enabling x2 speed")
        self._speed_tapped = True
        self.device.tap(*config.SPEED_BUTTON)
        return True

    def _fail(self, msg: str, img) -> None:
        DEBUG_DIR.mkdir(exist_ok=True)
        path = DEBUG_DIR / f"play_{time.strftime('%Y%m%d_%H%M%S')}.png"
        cv2.imwrite(str(path), img)
        raise PlayError(f"{msg} (screenshot: {path})")
