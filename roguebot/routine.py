"""Full routine, part 1 and 2: the daily modes (Arena, Tower, Crystal Mines, Pet Kingdom) and the
guild raid. Each part spends its tickets/attempts; a part that gets stuck is reported as failed and
the routine goes on with the next one."""

import logging
import time
from typing import Callable

from roguebot import config, labels as L
from roguebot.device import Device
from roguebot.mode_screens import (FightResult, back_arrow, free_donation, parse_patrol, parse_quick_patrol, guild_hall_donate, in_guild, is_modes_list, mode_closed, mode_entry, parse_arena, parse_arena_opponents,
                                   parse_dungeon_popup, parse_fight_result, parse_raid, parse_skill_choice,
                                   parse_tower, pick_opponent, vip_cards_icon, vip_claim_all)
from roguebot.navigation import NavigationError, Navigator
from roguebot.play import PlayError
from roguebot.screens import close_button, parse_energy, parse_lobby, popup_close
from roguebot.vision import Ocr, Text, find

log = logging.getLogger(__name__)

PARTS = ("vip", "arena", "tower", "mines", "pets", "patrol", "raid", "donate")
MODE_PARTS = ("arena", "tower", "mines", "pets")  # run from the modes list without going back to the lobby
MAX_BACK_STEPS = 8   # screens to back out of (popups, arena panel, mode screen) to reach the modes list
DONE, SKIPPED, FAILED = "done", "skipped", "failed"
LOBBY_RETRIES = 3     # lobby reads before using whatever shows (the game may open a screen by itself)
SCREEN_TIMEOUT = 20  # seconds to wait for an expected screen


class Routine:
    def __init__(self, device: Device, ocr: Ocr, nav: Navigator):
        self.device = device
        self.ocr = ocr
        self.nav = nav
        self.patrol_wait: float | None = None  # set by patrol(): seconds until it is worth opening again

    def run_parts(self) -> list[tuple[str, str]]:
        """Run every part in order; returns (part, status) pairs."""
        steps = {"arena": self.arena, "tower": self.tower, "mines": lambda: self.dungeon(L.MINES),
                 "pets": lambda: self.dungeon(L.PETS), "raid": self.raid, "vip": self.vip, "patrol": self.patrol,
                 "donate": self.donate}
        results = []
        for part, following in zip(PARTS, PARTS[1:] + (None,)):
            log.info("Routine: %s", part)
            try:
                status = steps[part]()
            except (NavigationError, PlayError) as e:
                log.error("Routine: %s failed: %s", part, e)
                status = FAILED
            results.append((part, status))
            # Stay in the modes tab between modes; the lobby after VIP, before the raid and before the levels.
            if not (part in MODE_PARTS and following in MODE_PARTS and self._back_to_modes()):
                try:
                    self.nav.go_to_lobby()
                except NavigationError as e:  # the next part goes back to the lobby itself
                    log.error("Routine: could not get back to the lobby after %s: %s", part, e)
        return results

    # --- parts ---------------------------------------------------------------------------

    def arena(self) -> str:
        """While there are tickets: fight the strongest opponent that is not stronger than us."""
        if not self._open_mode(L.ARENA):
            log.info("Arena: closed for now")
            return SKIPPED
        for _ in range(config.MAX_MODE_ACTIONS):
            screen = self._wait_for(lambda img, texts: self._claim_or(texts, lambda t: parse_arena(img, t, self.ocr)),
                                    "arena screen")
            if screen.tickets < 1:
                log.info("Arena: no tickets left")
                return DONE
            self._tap(screen.challenge)
            panel = self._wait_for(lambda img, texts: self._claim_or(texts, parse_arena_opponents), "arena opponent list")
            choice = pick_opponent(panel.own_power, panel.opponents)
            if choice is None and panel.free_refresh:
                log.info("Arena: every opponent is stronger, using the free refresh")
                self._tap(panel.free_refresh)
                time.sleep(config.UI_SETTLE)
                panel = self._wait_for(lambda img, texts: self._claim_or(texts, parse_arena_opponents), "arena opponent list")
                choice = pick_opponent(panel.own_power, panel.opponents)
            if choice is None:
                if not panel.opponents:
                    self._fail("No arena opponents recognized")
                choice = min(panel.opponents, key=lambda o: o.power)
            log.info("Arena: power %d vs %d (%d tickets)", panel.own_power, choice.power, screen.tickets)
            self._tap(choice.challenge)
            self._fight()
        self._fail("Arena did not run out of tickets")

    def tower(self) -> str:
        """Climb until the first defeat or until no tickets are left."""
        self._open_mode(L.TOWER)
        for _ in range(config.MAX_MODE_ACTIONS):
            screen = self._wait_for(lambda img, texts: self._claim_or(texts, self._tower_or_chest), "tower screen")
            if screen.tickets < 1:
                log.info("Tower: no tickets left")
                return DONE
            self._tap(screen.challenge)
            if not self._fight().victory:
                return DONE
        self._fail("Tower did not finish")

    def dungeon(self, label: L.Label) -> str:
        """Crystal Mines / Pet Kingdom: challenge the shown (highest) difficulty; after a defeat,
        sweep the previous stage. A defeat does not spend the ticket. At 0 tickets, watch the free
        ad for another one while it is offered."""
        self._open_mode(label)
        lost = False
        for _ in range(config.MAX_MODE_ACTIONS):
            popup = self._wait_for(lambda img, texts: self._claim_or(texts, parse_dungeon_popup), "dungeon popup")
            if popup.tickets < 1:
                if not popup.ad:
                    log.info("%s: no tickets left", label.variants[0])
                    return DONE
                log.info("%s: watching an ad for a ticket", label.variants[0])
                self.device.tap(*popup.ad.center, settle=config.VIDEO_SETTLE)
            elif lost:
                if not popup.sweep:
                    self._fail("Sweep button not found")
                log.info("%s: sweeping the previous stage (%d tickets)", label.variants[0], popup.tickets)
                self._tap(popup.sweep)
            else:
                if not popup.challenge:
                    self._fail("Challenge button not found")
                log.info("%s: challenging difficulty %s", label.variants[0], popup.difficulty)
                self._tap(popup.challenge)
                lost = not self._fight().victory
        self._fail("Dungeon did not run out of tickets")

    def raid(self) -> str:
        """Guild raid boss: challenge until no attempts are left. Skipped when not in a guild."""
        texts = self._lobby_texts()
        if not in_guild(texts):
            log.info("Not in a guild, skipping the raid")
            return SKIPPED
        self.device.tap(*config.GUILD_BUTTON)
        self._tap(self._wait_for(lambda img, texts: find(texts, L.RAID_BOSS), "guild map"))
        for _ in range(config.MAX_MODE_ACTIONS):
            screen = self._wait_for(lambda img, texts: parse_raid(texts), "raid screen")
            if screen.attempts < 1:
                log.info("Raid: no attempts left")
                return DONE
            log.info("Raid: %d attempts left", screen.attempts)
            self._tap(screen.challenge)
            self._fight()
        self._fail("Raid did not run out of attempts")

    def patrol(self) -> str:
        """Patrulla (lobby): claim the reward once the counter reaches PATROL_CLAIM_AFTER (it stops at
        8 h), then every quick patrol with uses left: the free video, then energy (only with enough
        energy). Never gems, never the VIP card offer below."""
        texts = self._lobby_texts()
        button = find(texts, L.PATROL)
        if not button:
            self._fail("Patrol button not found in the lobby")
        self._tap(button)
        popup = self._wait_for(lambda img, texts: self._claim_or(texts, parse_patrol), "patrol popup")
        # Seconds until the reward is worth claiming (None: unknown). Quick patrols are used up below.
        self.patrol_wait = None if popup.elapsed is None else max(0, config.PATROL_CLAIM_AFTER - popup.elapsed)
        if popup.elapsed is not None and popup.elapsed >= config.PATROL_CLAIM_AFTER:
            log.info("Patrol: claiming the reward (%d:%02d)", popup.elapsed // 3600, popup.elapsed % 3600 // 60)
            self._tap(popup.claim)
            self.patrol_wait = config.PATROL_CLAIM_AFTER  # the counter starts again from 0
            time.sleep(config.UI_SETTLE)
            popup = self._wait_for(lambda img, texts: self._claim_or(texts, parse_patrol), "patrol popup")
        else:
            log.info("Patrol: not claiming yet (counter %s)",
                     "unreadable" if popup.elapsed is None else f"{popup.elapsed // 3600}:{popup.elapsed % 3600 // 60:02d}")
        self._tap(popup.quick)
        for _ in range(config.MAX_MODE_ACTIONS):
            quick, energy = self._wait_for(lambda img, texts: self._claim_or(
                texts, lambda t: (q := parse_quick_patrol(img, t)) and (q, parse_energy(t) or 0)), "quick patrol popup")
            if quick.video:
                log.info("Patrol: quick patrol with a free video")
                self._tap(quick.video)
                time.sleep(config.VIDEO_SETTLE)
            elif quick.energy and energy >= quick.energy_cost:
                log.info("Patrol: quick patrol for %d energy (%d)", quick.energy_cost, energy)
                self._tap(quick.energy)
                time.sleep(config.UI_SETTLE)
            else:
                log.info("Patrol: no free quick patrol left")
                return DONE
        self._fail("Quick patrol did not run out")

    def donate(self) -> str:
        """Guild hall donation, only the free one(s). Skipped when not in a guild."""
        texts = self._lobby_texts()
        if not in_guild(texts):
            log.info("Not in a guild, skipping the donation")
            return SKIPPED
        self.device.tap(*config.GUILD_BUTTON)
        self._tap(self._wait_for(lambda img, texts: find(texts, L.GUILD_HALL), "guild map"))
        self._tap(self._wait_for(lambda img, texts: guild_hall_donate(texts), "guild hall"))
        self._wait_for(lambda img, texts: find(texts, L.DONATION_TITLE), "donation popup")
        for _ in range(config.DONATE_FREE_MAX):
            # Reward popups ("Tap anywhere to claim") until the donation popup shows again.
            texts = self._wait_for(lambda img, texts: self._claim_or(
                texts, lambda t: find(t, L.DONATION_TITLE) and t), "donation popup")
            free = free_donation(texts)
            if not free:
                log.info("Guild donation: no free donation left")
                return DONE
            log.info("Guild donation: free donation")
            self._tap(free)
            # After the free donation the same button shows a gem price: decide again only on a frame
            # where the free button is gone (reward popup), never on a stale one that still says "Gratis".
            self._wait_change(lambda t: free_donation(t) is None)
        return DONE

    def vip(self) -> str:
        """VIP cards: "Reclamar todo" (daily rewards). A grey button (already claimed) ignores the tap."""
        texts = self._lobby_texts()
        icon = vip_cards_icon(texts)
        if not icon:
            log.info("No VIP cards icon in the lobby, skipping")
            return SKIPPED
        self._tap(icon)
        self._tap(self._wait_for(lambda img, texts: vip_claim_all(texts), "VIP cards screen"))
        log.info("VIP cards: claim all")
        time.sleep(config.UI_SETTLE)
        # Reward popups ("Tap anywhere to claim") until the VIP screen shows again.
        self._wait_for(lambda img, texts: self._claim_or(texts, vip_claim_all), "VIP cards screen")
        return DONE

    # --- steps ---------------------------------------------------------------------------

    def _open_mode(self, label: L.Label) -> bool:
        """Tap the mode's card in the modes list. False (no tap) if the card says it opens later."""
        _, texts = self._capture()
        if not is_modes_list(texts):
            self.nav.go_to_lobby()
            self.device.tap(*config.MODES_BUTTON)
            texts = self._wait_for(lambda img, texts: is_modes_list(texts) and texts, "modes list")
        scrolled = False
        for _ in range(config.MODES_MAX_SCROLLS):  # the list keeps its scroll: back to the top (Arena)
            if find(texts, L.ARENA, exact=True):
                break
            log.info("Modes list scrolled down, scrolling to the top")
            self.device.swipe(*config.MODES_SCROLL_UP, duration=config.SCROLL_DURATION)
            _, texts = self._capture()
            scrolled = True
        entry = mode_entry(texts, label)
        while scrolled and entry:  # inertia: only tap a card seen twice in the same place
            _, texts = self._capture()
            again = mode_entry(texts, label)
            scrolled = not (again and abs(again.center[1] - entry.center[1]) < 20)
            entry = again
        if not entry:
            self._fail(f"{label.variants[0]} not found in the modes list")
        if mode_closed(texts, entry):
            return False
        self._tap(entry)
        return True

    def _back_to_modes(self) -> bool:
        """Back out of a mode (popups, ✕, ← arrows) to the modes list. False if it was not reached."""
        for _ in range(MAX_BACK_STEPS):
            img, texts = self._capture()
            if is_modes_list(texts):
                return True
            close_text, close_x, back = popup_close(texts), close_button(img), back_arrow(img)
            if close_text:
                self._tap(close_text)
            elif close_x:
                self.device.tap(*close_x)
            elif back:
                self.device.tap(*back)
            else:  # loading or an animation: wait, never guess
                time.sleep(config.UI_SETTLE)
        log.info("Could not get back to the modes list")
        return False

    def _fight(self) -> FightResult:
        """Wait out a mode/raid fight, picking raid skills (highest rarity) when asked. Never taps
        "Skip": it opens a paid VIP offer."""
        deadline = time.monotonic() + config.MODE_FIGHT_TIMEOUT
        while time.monotonic() < deadline:
            img, texts = self._capture()
            result = parse_fight_result(texts)
            if result:
                log.info("Fight finished: %s", "victory" if result.victory else "defeat")
                self._tap(result.button)
                return result
            choice = parse_skill_choice(texts)
            if choice and choice.chosen < choice.needed:
                if choice.chosen >= len(choice.cards):
                    self._fail("Skill cards not recognized", img)
                self.device.tap(*choice.cards[choice.chosen])
            elif choice:
                self._tap(choice.learn)
            else:
                time.sleep(config.POLL_INTERVAL)
        self._fail("Fight did not finish", img)

    def _tower_or_chest(self, texts: list[Text]):
        """Tower screen, or (after clearing a whole tower) open the "Congrats" reward chest."""
        if find(texts, L.TOWER_CLEARED):
            log.info("Tower cleared: opening the reward chest")
            self.device.tap(*config.TOWER_CHEST)
            return None
        return parse_tower(texts)

    def _claim_or(self, texts: list[Text], parse: Callable):
        """Tap away reward popups ("Tap anywhere to claim") and popups that close by text (arena season
        promotion: "Felicidades por tu ascenso!"); otherwise parse the screen."""
        away = find(texts, L.TAP_TO_CLAIM) or popup_close(texts)
        if away:
            self._tap(away)
            return None
        return parse(texts)

    def _lobby_texts(self) -> list[Text]:
        """The lobby's texts. The game can open a screen by itself right after the lobby shows (new
        events, "Fondo del Álbum"): read again, and go back to the lobby if it is gone."""
        for _ in range(LOBBY_RETRIES):
            self.nav.go_to_lobby()
            _, texts = self._capture()
            if parse_lobby(texts):
                return texts
        return texts

    def _wait_change(self, changed: Callable[[list[Text]], bool]) -> None:
        """Wait (up to CHANGE_TIMEOUT) until a tap's effect shows, so the next decision is not taken on a
        stale frame."""
        deadline = time.monotonic() + config.CHANGE_TIMEOUT
        while not changed(self._capture()[1]) and time.monotonic() < deadline:
            time.sleep(config.POLL_INTERVAL)

    def _wait_for(self, parse: Callable, what: str):
        deadline = time.monotonic() + SCREEN_TIMEOUT
        while time.monotonic() < deadline:
            img, texts = self._capture()
            found = parse(img, texts)
            if found:
                return found
            time.sleep(config.POLL_INTERVAL)
        self._fail(f"Expected the {what}", img)

    # --- helpers -------------------------------------------------------------------------

    def _capture(self) -> tuple:
        img = self.device.screenshot()
        return img, self.ocr.read(img)

    def _tap(self, t: Text) -> None:
        self.device.tap(*t.center)

    def _fail(self, msg: str, img=None) -> None:
        self.nav._fail(msg, self.device.screenshot() if img is None else img)
