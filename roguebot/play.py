"""In-level loop: roll dice, let fights play, pick skills, until the level ends.

Mode-agnostic: normal and elite levels share the same gameplay.
"""

import logging
import time
from pathlib import Path

import cv2

from roguebot import config, labels, strategy
from roguebot.build import Build, BuildState, choose, shop_order
from roguebot.device import Device
from roguebot.screens import (TREASURE, LevelScreen, LevelState, SkillCard, classify_level_screen, event_options,
                              event_tap, game_speed, miner_tile, miner_tiles, parse_anvil, parse_contracts, parse_fortune_teller, parse_hp,
                              parse_money,
                              parse_paths, parse_shop, parse_skill_cards, skill_reroll, treasures_left)
from roguebot.skills import Catalog, Skill
from roguebot.vision import Ocr, find

log = logging.getLogger(__name__)

DEBUG_DIR = Path("debug")
MAX_SHOP_STEPS = 12  # rerolls + purchases in one shop visit


class PlayError(Exception):
    pass


def _same_tap(a, b) -> bool:
    """Same screen kind and (nearly) the same point: OCR jitters text centers by a few pixels."""
    return (b is not None and a[0] is b[0]
            and abs(a[1][0] - b[1][0]) <= config.SAME_TAP_TOLERANCE and abs(a[1][1] - b[1][1]) <= config.SAME_TAP_TOLERANCE)


class Player:
    def __init__(self, device: Device, ocr: Ocr, build: Build = Build(), catalog: Catalog | None = None,
                 ads: bool = False):
        self.device = device
        self.ads = ads  # watch ads (x2 rewards, free revive); only with an account that skips them
        self.ocr = ocr
        self.build = build
        self.catalog = catalog if catalog is not None else Catalog()
        self._state = BuildState()   # skills taken in the current level
        self._rerolled = False       # the skill pick on screen is already the rerolled one
        self._doubles = 0            # x2 rewards taps at this level end
        self._last_offer = None      # names of the last skill pick decided (a repeat = the tap did not land)
        self._seen_offer = None      # cards read on the last skill pick frame (they fly in: decide on a settled frame)
        self._offer_frames = 0       # frames in a row whose card count differed from the frame before
        self._miner_done = set()     # treasure miner: tiles of treasures already dug out whole
        self._miner_left = None      # its "Tesoros Restantes" on the last frame
        self._speed_tapped = False  # tapped x1 -> x2 and waiting to see the label change
        self._speed_locked = False  # x2 is not unlocked on this account
        self._auto_held = False     # held the dice for auto-play and not seen it on yet
        self._auto_missing = False  # a hold brought the red dice back: no auto-play here, tap instead
        self._auto_seen = False     # auto-play worked in this level: a hold that brings the red dice back was missed
        self._auto_misses = 0       # such missed holds in a row
        self._fortune_bought = []   # Fortune Teller balls bought this visit (chances)
        self._fortune_tap = None    # (chance, orbs before, time) of the last ball tap, until the orbs drop

    def play_level(self) -> LevelScreen:
        """Play until the level ends; returns LevelScreen.VICTORY or LevelScreen.DEFEAT."""
        last_known = time.monotonic()
        last_tap, repeats, first_repeat = None, 0, time.monotonic()
        waiting, waiting_frames = None, 0  # the screen kind being waited on, and for how many frames
        self._state, self._rerolled, self._doubles, self._last_offer = BuildState(), False, 0, None
        self._fortune_bought, self._fortune_tap = [], None
        while True:
            img = self.device.screenshot()
            texts = self.ocr.read(img)
            state = classify_level_screen(img, texts)
            log.debug("screen: %s", state.kind.value)

            if state.kind is LevelScreen.SKILL_PICK:
                settled = self._offer_settled(texts)
                state = LevelState(state.kind, (self._pick_skill(texts) or state.tap) if settled else None)
            elif state.kind is LevelScreen.PATH_CHOICE:
                state = LevelState(state.kind, self._path(img, texts))
            elif state.kind is LevelScreen.EVENT:
                state = LevelState(state.kind, self._event(img, texts) or state.tap)
            elif state.kind is LevelScreen.MINER:
                state = LevelState(state.kind, self._miner(img, texts))
            elif state.kind is LevelScreen.ANVIL:
                state = LevelState(state.kind, self._anvil(texts))
            elif state.kind is LevelScreen.CONTRACT:
                state = LevelState(state.kind, self._contract(texts))
            elif state.kind is LevelScreen.SHOP:
                self._shop(texts)  # buys what the build wants and the coins allow; then state.tap exits
            elif state.kind is LevelScreen.FORTUNE_TELLER:
                state = LevelState(state.kind, self._fortune(texts))
            elif state.kind in (LevelScreen.BOARD_READY, LevelScreen.AUTO_PLAY):
                self._fortune_bought = []  # back on the board: a later Fortune Teller is a new visit
                self._miner_done, self._miner_left = set(), None

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

            if state.kind in (LevelScreen.VICTORY, LevelScreen.DEFEAT):
                log.info("Level finished: %s", state.kind.value)
                self.device.tap(*state.tap)
                return state.kind

            waiting, waiting_frames = state.kind, waiting_frames + 1 if state.kind is waiting else 0
            if (state.tap is None and state.kind not in (LevelScreen.UNKNOWN, LevelScreen.FIGHT)
                    and waiting_frames > config.WAIT_SCREEN_FRAMES):
                # Auto-play never lasts this long without a fight or an event in between.
                self._fail(f"Waiting on {state.kind.value} for too long", img)

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
                if state.kind is LevelScreen.BOARD_READY and not self._auto_missing:
                    log.info("board_ready -> hold %s for auto-play", state.tap)
                    self.device.hold(*state.tap, config.AUTO_PLAY_HOLD)
                    self._auto_held = True
                else:
                    log.info("%s -> tap %s", state.kind.value, state.tap)
                    self.device.tap(*state.tap)
            else:
                last_tap, repeats = None, 0  # screen changed on its own: the last tap worked
                time.sleep(config.POLL_INTERVAL)

    def _skill(self, card: SkillCard) -> Skill:
        return self.catalog.lookup(card.name, card.description, card.rarity, labels.active_language())

    def _offer_settled(self, texts) -> bool:
        """The skill cards fly in one by one: a frame taken meanwhile once showed a single card and the
        reroll was wasted on it. True once two frames in a row show the same number of cards (or after
        SKILL_PICK_SETTLE_FRAMES changing frames). Not their names: OCR reads those a bit differently each frame."""
        cards = len(parse_skill_cards(texts))
        if cards and cards != self._seen_offer and self._offer_frames < config.SKILL_PICK_SETTLE_FRAMES:
            self._seen_offer, self._offer_frames = cards, self._offer_frames + 1
            return False
        self._seen_offer, self._offer_frames = None, 0
        return True

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

    def _path(self, img, texts) -> tuple[int, int]:
        """Board fork: the path the strategy wants (the shop while the coins are worth it)."""
        paths = parse_paths(texts, img)
        coins = parse_money(texts)
        i = strategy.choose_path([p.shop for p in paths], coins)
        log.info("Fork: %s (coins %s) -> %s", " / ".join(f"{p.label.text}{' = shop' if p.shop else ''}" for p in paths),
                 coins, paths[i].label.text)
        return paths[i].label.center

    def _event(self, img, texts) -> tuple[int, int] | None:
        """Tile event: the option the strategy wants, or None when it has no rule for this event."""
        options = event_options(img, texts)
        hp = parse_hp(texts)
        i = strategy.choose_event([o.norm for o in options], hp)
        if i is None:
            return None
        log.info("Event: %s (HP %s) -> %s", " / ".join(o.text for o in options),
                 "?" if hp is None else f"{hp:.0%}", options[i].text)
        return event_tap(options[i])

    def _anvil(self, texts) -> tuple[int, int]:
        """Blacksmith's anvil: upgrade the item while the odds are good, then take it."""
        take, upgrade, chance = parse_anvil(texts)
        go = strategy.anvil_upgrade(chance)
        log.info("Anvil: %s%% success -> %s", "?" if chance is None else chance, "upgrade" if go else "take")
        return (upgrade if go else take).center

    def _contract(self, texts) -> tuple[int, int]:
        """Cursed vendor: sign the contract the strategy rates best."""
        contracts = parse_contracts(texts)
        i = strategy.choose_contract([c.terms for c in contracts])
        log.info("Cursed vendor: %s -> signing %d", " | ".join(c.terms for c in contracts), i + 1)
        return contracts[i].button.center

    def _miner(self, img, texts) -> tuple[int, int] | None:
        """Treasure miner: the tile to dig. A drop of "Tesoros Restantes" means the treasure pieces on
        screen are dug out whole: they are not followed any more."""
        tiles, left = miner_tiles(img), treasures_left(texts)
        if left is not None and self._miner_left is not None and left < self._miner_left:
            self._miner_done = {i for i, tile in enumerate(tiles) if tile == TREASURE}
        self._miner_left = left if left is not None else self._miner_left
        i = strategy.miner_dig(tiles, self._miner_done)
        return None if i is None else miner_tile(*divmod(i, config.MINER_SIZE))

    def _shop(self, texts) -> None:
        """Stat items first (heal when hurt, then the cheap stat boost), a free reroll if no skill is
        wanted, then skills in the build's order whatever the coins allow."""
        rerolled, tapped = False, set()
        item_buy = None  # (kind, coins before) of the stat item just tapped
        for _ in range(MAX_SHOP_STEPS):
            shop = parse_shop(texts)
            if shop is None or shop.money is None:
                return
            if item_buy and shop.money >= item_buy[1]:  # the coins did not drop: sold out or a missed tap; no more items
                tapped.add("items")
            item = None if "items" in tapped else strategy.shop_item(
                {k: int(t.norm) for k, t in shop.items.items()}, shop.money, parse_hp(texts))
            if item:
                log.info("Shop: buying %s for %s (coins %d)", item, shop.items[item].norm, shop.money)
                self.device.tap(*shop.items[item].center)
                item_buy = item, shop.money
                texts = self.ocr.read(self.device.screenshot())
                continue
            item_buy = None
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
