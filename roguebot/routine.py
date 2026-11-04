"""Full routine: daily rewards (web claim and free spin), VIP cards, mail, the daily modes
(Arena, Dojo, Tower, Dungeon Dive, Crystal Mines, Pet Kingdom), patrol and the guild
(raid, free donation, personal vault) without leaving the guild map in between.
Each part spends its tickets/attempts; a part that gets stuck is reported as failed and the
routine goes on with the next one."""

import logging
import time
from typing import Callable

from roguebot import config, labels as L
from roguebot.build import Build, BuildState, choose, shop_order
from roguebot.device import Device
from roguebot.mode_screens import (FightResult, back_arrow, daily_claim, fight_skip, free_donation, parse_patrol, parse_quick_patrol, guild_hall, guild_hall_donate, guild_vault, in_guild, is_guild_map, is_modes_list, mail_claim_all, menu_entry, mode_closed, mode_entry, parse_arena, parse_arena_opponents,
                                   parse_dive, parse_dojo, parse_dungeon_popup, parse_fight_result, parse_raid,
                                   parse_skill_choice, parse_tower, personal_vault_claim, pick_opponent,
                                   quick_patrol_close, quick_patrol_open, vip_cards_icon, vip_claim_all,
                                   web_daily_claim, web_free_spin)
from roguebot.navigation import NavigationError, Navigator, _still_there
from roguebot.play import PlayError
from roguebot.screens import (LevelScreen, classify_level_screen, close_button, close_button_any_size, is_loading,
                              parse_energy, parse_lobby, parse_skill_cards, popup_close, rarity_name, skill_reroll)
from roguebot.skills import Catalog, Skill
from roguebot.vision import Ocr, Text, find

log = logging.getLogger(__name__)

PARTS = ("daily", "vip", "mail", "patrol", "arena", "dojo", "tower", "dive", "mines", "pets", "raid", "donate", "vault")
MODE_PARTS = ("arena", "dojo", "tower", "dive", "mines", "pets")  # run from the modes list without going back to the lobby
GUILD_PARTS = ("raid", "donate", "vault")  # stay on the guild map between these
MAX_BACK_STEPS = 8   # screens to back out of (popups, arena panel, mode screen) to reach the modes list
DONE, SKIPPED, FAILED = "done", "skipped", "failed"
LOBBY_RETRIES = 3     # lobby reads before using whatever shows (the game may open a screen by itself)
SCREEN_TIMEOUT = 20  # seconds to wait for an expected screen
PART_RESTARTS = 2    # emulator restarts a part may cause before the routine marks it failed and moves on
PRESS_RETAP_AFTER = 4  # seconds with a pressed button still in place before tapping it again
PRESS_RETAPS = 2


class StuckError(NavigationError):
    """A part failed and the lobby can't be reached: the run restarts the emulator and resumes the
    routine at the next part."""


class Routine:
    def __init__(self, device: Device, ocr: Ocr, nav: Navigator, ads: bool = False,
                 play_level: Callable[[], object] | None = None, build: Build = Build(),
                 catalog: Catalog | None = None, skip_fights: bool = False):
        self.play_level = play_level  # plays a level board to its end (Player.play_level): Dungeon Dive runs
        self.build = build            # skill picks in Dojo / raid fights follow the build, like levels
        self.catalog = catalog
        self.ads = ads  # watch ads (dungeon tickets, quick patrol); only with an account that skips them
        self.skip_fights = skip_fights  # paid green Skip on mode fights; off, and when the button is grey
        self.device = device
        self.ocr = ocr
        self.nav = nav
        self.patrol_wait: float | None = None  # set by patrol(): seconds until it is worth opening again
        self._pushed = None  # one frame put back so a guild-map read can be used twice

    def run_parts(self, progress: dict | None = None) -> list[tuple[str, str]]:
        """Run every part in order; returns (part, status) pairs.

        `progress` outlives an emulator restart (make_runner's state): parts already finished are not
        run again, so the routine resumes at the part that was running. A part that keeps breaking the
        run (more than PART_RESTARTS restarts) is marked failed and skipped."""
        progress = {} if progress is None else progress
        results = progress.setdefault("parts", [])
        tries = progress.setdefault("part_tries", {})
        finished = {part for part, _ in results}
        steps = {"arena": self.arena, "dojo": self.dojo, "dive": self.dive, "daily": self.daily, "mail": self.mail,
                 "tower": self.tower, "mines": lambda: self.dungeon(L.MINES),
                 "pets": lambda: self.dungeon(L.PETS), "raid": self.raid, "vip": self.vip, "patrol": self.patrol,
                 "donate": self.donate, "vault": self.vault}
        for part, following in zip(PARTS, PARTS[1:] + (None,)):
            if part in finished:
                continue
            tries[part] = tries.get(part, 0) + 1
            if tries[part] > PART_RESTARTS + 1:
                log.error("Routine: %s broke the run %d times, skipping it", part, tries[part] - 1)
                results.append((part, FAILED))
                continue
            log.info("Routine: %s%s", part, f" (again after a restart, try {tries[part]})" if tries[part] > 1 else "")
            try:
                status = steps[part]()
            except (NavigationError, PlayError) as e:
                log.error("Routine: %s failed: %s", part, e)
                status = FAILED
            results.append((part, status))
            # Stay in the modes tab between modes, and on the guild map between raid, donation and vault.
            # The lobby otherwise (after daily, before the raid, and before the levels).
            if part in GUILD_PARTS and following in GUILD_PARTS and self._back_to_guild():
                continue
            if not (part in MODE_PARTS and following in MODE_PARTS and self._back_to_modes()):
                try:
                    self.nav.go_to_lobby()
                except NavigationError as e:  # the next part goes back to the lobby itself
                    log.error("Routine: could not get back to the lobby after %s: %s", part, e)
                    if status == FAILED:  # stuck where the part broke: every next part would fail the same way
                        raise StuckError(f"Stuck after {part} failed: {e}") from e
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
            self._press(screen.challenge, lambda texts: parse_arena_opponents(texts) is not None)
            panel = self._wait_for(self._arena_panel, "arena opponent list")
            choice = pick_opponent(panel.own_power, panel.opponents)
            if choice is None and panel.free_refresh:
                log.info("Arena: every opponent is stronger, using the free refresh")
                self._tap(panel.free_refresh)
                time.sleep(config.UI_SETTLE)
                panel = self._wait_for(self._arena_panel, "arena opponent list")
                choice = pick_opponent(panel.own_power, panel.opponents)
            if choice is None:
                if not panel.opponents:
                    self._fail("No arena opponents recognized")
                choice = min(panel.opponents, key=lambda o: o.power)
            log.info("Arena: power %d vs %d of %s (%d tickets)", panel.own_power, choice.power,
                     [o.power for o in panel.opponents], screen.tickets)
            self._tap(choice.challenge)
            self._fight()
        self._fail("Arena did not run out of tickets")

    def _arena_panel(self, img, texts: list[Text]):
        return self._claim_or(texts, lambda t: parse_arena_opponents(t, img, self.ocr))

    def tower(self) -> str:
        """Climb until the first defeat or until no tickets are left.

        Floors 1-9 show Next (or "Próximo piso"): tap it and stay in the fight. The ticket count
        is not what decides that — a wrong count used to tap Okay and bounce back to the tower
        menu. Floor 10 has no Next: Okay, then the chest on the clear screen.
        """
        self._open_mode(L.TOWER)
        climbing = False  # Next was tapped: the next floor follows, the tower menu does not
        for _ in range(config.MAX_MODE_ACTIONS):
            if not climbing:
                screen = self._wait_for(lambda img, texts: self._claim_or(texts, self._tower_or_chest), "tower screen")
                if screen.tickets < 1:
                    log.info("Tower: no tickets left")
                    return DONE
                log.info("Tower: challenge (%d tickets)", screen.tickets)
                self._press(screen.challenge)
            result = self._fight(next_floor=True)
            if not result.victory:
                return DONE
            if result.next_floor:
                log.info("Tower: next floor")
                climbing = True
            else:
                log.info("Tower: floor cleared")  # Okay, then the chest if the tower is done
                climbing = False
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
                if not (popup.ad and self.ads):
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
                self._press(popup.challenge)
                lost = not self._fight().victory
        self._fail("Dungeon did not run out of tickets")

    def dojo(self) -> str:
        """Dojo Battle: fight the training dummy (most damage wins rank) while there are tickets; skills by
        rarity, like the raid. Also claims the free progress chest ("Intenta el Dojo N veces")
        whenever its label is on screen, including while tickets remain (no red-dot required)."""
        if not self._open_mode(L.DOJO):
            log.info("Dojo: closed for now")
            return SKIPPED
        for _ in range(config.MAX_MODE_ACTIONS):
            screen = self._wait_for(lambda img, texts: self._claim_or(texts, lambda t: parse_dojo(img, t, self.ocr)),
                                    "dojo screen")
            if screen.chest:
                log.info("Dojo: claiming the progress chest")
                self._tap(screen.chest)
                time.sleep(config.UI_SETTLE)
            elif screen.tickets < 1 or not screen.challenge:
                log.info("Dojo: no tickets left")
                return DONE
            else:
                log.info("Dojo: challenge (%d tickets)", screen.tickets)
                self._press(screen.challenge)
                self._fight()
        self._fail("Dojo did not run out of tickets")

    def dive(self) -> str:
        """Dungeon Dive: a 3-depth level board, played like a normal level (build, auto-play) while there
        are tickets, whatever the result."""
        if not self._open_mode(L.DIVE):
            log.info("Dungeon Dive: closed for now")
            return SKIPPED
        for _ in range(config.MAX_MODE_ACTIONS):
            screen = self._wait_for(self._dive_screen, "dungeon dive screen")
            if screen.tickets < 1:
                log.info("Dungeon Dive: no tickets left")
                return DONE
            log.info("Dungeon Dive: challenge (%d tickets)", screen.tickets)
            self._press(screen.challenge)
            log.info("Dungeon Dive finished: %s", self.play_level().value)
        self._fail("Dungeon Dive did not run out of tickets")

    def _dive_screen(self, img, texts: list[Text]):
        """The dive screen, after a victory/defeat that is still up has been dismissed."""
        screen = self._claim_or(texts, parse_dive)
        if screen:
            return screen
        if img is None:
            return None
        state = classify_level_screen(img, texts)
        if state.kind in (LevelScreen.VICTORY, LevelScreen.DEFEAT) and state.tap:
            log.info("Dungeon Dive: dismissing %s", state.kind.value)
            self.device.tap(*state.tap)
        return None

    def daily(self) -> str:
        """Lobby ≡ menu → Daily Rewards → the web store.

        Wait until the page is up, claim the daily reward, scroll down and take the free spin,
        then Back to the game. VIP runs after this. The popup is closed (its ✕) before this
        returns, including when the browser never opens.
        """
        if not self._open_menu(L.MENU_DAILY):
            return SKIPPED
        try:
            texts = self._wait_for(lambda img, texts: find(texts, L.DAILY_TITLE) and texts, "daily rewards popup")
            claim = daily_claim(texts)
            if claim is None:
                log.info("Daily rewards: claim unavailable; closing the popup")
                return DONE
            self._tap(claim)
            try:
                self._claim_web_daily()
            except NavigationError:
                log.info("Daily rewards: web claim not finished; returning to the game")
            finally:
                self._back_to_game()
        finally:
            self._close_named_popup(L.DAILY_TITLE)
        return DONE

    def _claim_web_daily(self) -> None:
        """On roguelegend.io: wait for the page, claim the daily reward, scroll to the free spin."""
        self._wait_for(lambda img, texts: (web_daily_claim(texts) or find(texts, L.WEB_STORE)) and texts,
                       "daily reward web page", timeout=config.WEB_PAGE_TIMEOUT)
        # The first paint can show the button before it can take a tap. See it twice.
        page = self._wait_for(lambda img, texts: web_daily_claim(texts), "daily reward claim",
                              timeout=config.WEB_PAGE_TIMEOUT)
        log.info("Daily rewards: claiming the daily reward")
        self._tap(page)
        self._wait_change(lambda t: web_daily_claim(t) is None)
        spun = False
        for i in range(config.WEB_SCROLLS + 1):
            _, texts = self._capture()
            spin = web_free_spin(texts)
            if spin:
                log.info("Daily rewards: free spin")
                self._tap(spin)
                time.sleep(config.UI_SETTLE)
                _, again_texts = self._capture()
                again = web_free_spin(again_texts)
                if again and abs(again.center[1] - spin.center[1]) > 40:
                    log.info("Daily rewards: spinning")
                    self._tap(again)
                spun = True
                break
            if i == config.WEB_SCROLLS:
                break
            log.info("Daily rewards: scrolling for the free spin")
            self.device.swipe(*config.WEB_SCROLL_DOWN, duration=config.SCROLL_DURATION)
            time.sleep(config.SCROLL_SETTLE)
        if not spun:
            log.info("Daily rewards: no free spin found")

    def mail(self) -> str:
        """Lobby ≡ menu → "Correo" → "Reclamar todo" (never "Eliminar todo"); claim popups; ✕."""
        if not self._open_menu(L.MENU_MAIL):
            return SKIPPED
        self._tap(self._wait_for(lambda img, texts: mail_claim_all(texts), "mail popup"))
        log.info("Mail: claim all")
        time.sleep(config.UI_SETTLE)
        # Reward popups ("Tap anywhere to claim") until the mail shows again; go_to_lobby closes it (✕).
        self._wait_for(lambda img, texts: self._claim_or(texts, mail_claim_all), "mail popup")
        return DONE

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
            self._press(screen.challenge)
            self._fight()
        self._fail("Raid did not run out of attempts")

    def patrol(self) -> str:
        """Patrulla (lobby): claim the reward once the counter reaches PATROL_CLAIM_AFTER (2 h; it stops
        at 8 h), then every quick patrol with uses left: the free video, then energy (only with enough
        energy). Never gems, never the VIP card offer below."""
        texts = self._lobby_texts()
        button = find(texts, L.PATROL)
        if not button:
            self._fail("Patrol button not found in the lobby")
        self._tap(button)
        popup = self._wait_for(self._patrol_menu, "patrol popup")
        # Seconds until the reward is worth claiming (None: unknown). Quick patrols are used up below.
        self.patrol_wait = None if popup.elapsed is None else max(0, config.PATROL_CLAIM_AFTER - popup.elapsed)
        if popup.elapsed is not None and popup.elapsed >= config.PATROL_CLAIM_AFTER:
            log.info("Patrol: claiming the reward (%d:%02d)", popup.elapsed // 3600, popup.elapsed % 3600 // 60)
            self._tap(popup.claim)
            self.patrol_wait = config.PATROL_CLAIM_AFTER  # the counter starts again from 0
            time.sleep(config.UI_SETTLE)
            popup = self._wait_for(self._patrol_menu, "patrol popup")
        else:
            log.info("Patrol: not claiming yet (counter %s)",
                     "unreadable" if popup.elapsed is None else f"{popup.elapsed // 3600}:{popup.elapsed % 3600 // 60:02d}")
        self._tap(popup.quick)
        for _ in range(config.MAX_MODE_ACTIONS):
            quick, energy = self._wait_for(lambda img, texts: self._claim_or(
                texts, lambda t: (q := parse_quick_patrol(img, t)) and (q, parse_energy(t) or 0)), "quick patrol popup")
            if quick.video and self.ads:
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
        """Guild hall donation, only the free one(s). Stays on the guild map when the raid just ended."""
        if not self._open_guild():
            log.info("Not in a guild, skipping the donation")
            return SKIPPED
        self._tap(self._wait_for(lambda img, texts: guild_hall(texts), "guild hall"))
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

    def vault(self) -> str:
        """Guild Vault: the free daily personal claim. No gem button. Skipped outside a guild."""
        if not self._open_guild():
            log.info("Guild vault: not in a guild")
            return SKIPPED
        building = guild_vault(self._capture()[1])
        if building is None:
            building = self._wait_for(lambda img, texts: guild_vault(texts), "guild vault")
        log.info("Guild vault: opening")
        self._tap(building)
        claim = None
        deadline = time.monotonic() + SCREEN_TIMEOUT
        while time.monotonic() < deadline:
            _, texts = self._capture()
            claim = personal_vault_claim(texts)
            if claim or (find(texts, L.PERSONAL_VAULT) and not claim):
                break
            if is_loading(texts):
                deadline = max(deadline, time.monotonic() + SCREEN_TIMEOUT)
            time.sleep(config.POLL_INTERVAL)
        if not claim:
            log.info("Guild vault: no free daily personal claim")
            return DONE
        log.info("Guild vault: daily personal claim")
        self._tap(claim)
        self._wait_change(lambda t: personal_vault_claim(t) is None)
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

    def _open_menu(self, label: L.Label) -> bool:
        """Open the lobby's ≡ menu and tap an entry. False (logged) if the menu or the entry isn't there."""
        self._lobby_texts()
        self.device.tap(*config.MENU_BUTTON)
        deadline = time.monotonic() + SCREEN_TIMEOUT
        while time.monotonic() < deadline:
            _, texts = self._capture()
            if menu_entry(texts, L.MENU_MAIL):  # the menu is open
                entry = menu_entry(texts, label)
                if entry:
                    self._tap(entry)
                    return True
                break
            time.sleep(config.POLL_INTERVAL)
        log.info("No %s in the lobby menu, skipping", label.variants[0])
        return False

    def _back_to_game(self) -> None:
        """Back key until the game is in front again (it opened a browser)."""
        for _ in range(config.BROWSER_BACK_MAX):
            if self.device.foreground_package() == config.PACKAGE:
                return
            self.device.back()
        self._fail("Could not get back to the game from the browser")

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

    def _patrol_menu(self, img, texts: list[Text]):
        """The patrol menu. A Quick Patrol sheet on top is closed by its bright ✕ first, so the
        green Reclamar of the timed reward can be read (the sheet used to be the only thing checked)."""
        if quick_patrol_open(texts):
            close = quick_patrol_close(img, texts)
            if close:
                log.info("Closing Quick Patrol")
                self.device.tap(*close)
            return None
        return self._claim_or(texts, parse_patrol)

    def _close_named_popup(self, title: L.Label) -> None:
        """Tap the ✕ while this popup's title is still on screen. A few tries, then give up."""
        for _ in range(6):
            img, texts = self._capture()
            if find(texts, title) is None:
                return
            close = close_button(img) or close_button_any_size(img)
            if close:
                log.info("Closing %s", title.variants[0] if title.variants else "popup")
                self.device.tap(*close)
                time.sleep(config.UI_SETTLE)
            else:
                time.sleep(config.POLL_INTERVAL)

    def _fight(self, next_floor: bool = False) -> FightResult:
        """Wait out a mode/raid fight, picking skills (Dojo, raid) by the build when asked.

        Skip is off unless the run asked for it. Even then only the green Skip is tapped, once,
        and the fight is then allowed to finish: the grey button opens a paid offer, and tapping
        Skip on every frame races the result. With `next_floor`, a tower win taps Next when it
        is on screen (floors 1-9) and Okay otherwise (floor 10). A Loading screen is a
        transition, not a loss: the fight keeps waiting through it and reads the result again.
        An offer with nothing the build wants is rerolled once, the same as a level skill pick.
        """
        deadline = time.monotonic() + config.MODE_FIGHT_TIMEOUT
        state, learned = BuildState(), None  # skills taken in this fight; the last offer learned
        skipped = False
        rerolled = False
        loading_since = None
        img = None
        while True:
            img, texts = self._capture()
            if is_loading(texts):
                if loading_since is None:
                    loading_since = time.monotonic()
                    log.info("Fight: waiting through Loading")
                if time.monotonic() - loading_since > config.FIGHT_LOADING_WAIT:
                    break
                time.sleep(config.POLL_INTERVAL)
                continue
            loading_since = None
            result = parse_fight_result(texts)
            if result:
                log.info("Fight finished: %s", "victory" if result.victory else "defeat")
                use_next = next_floor and result.victory and result.next_floor
                self._tap(result.next_floor if use_next else result.button)
                if use_next:  # the next fight follows: never read this win again on a stale frame
                    self._wait_change(lambda t: parse_fight_result(t) is None)
                else:
                    result = FightResult(result.victory, result.button)
                return result
            if time.monotonic() >= deadline:
                break
            if self.skip_fights and not skipped:
                button = fight_skip(img, texts)
                if button:
                    log.info("Skipping the fight")
                    self._tap(button)
                    skipped = True
                    time.sleep(config.UI_SETTLE)  # one tap, then let the result show
                    continue
            choice = parse_skill_choice(texts)
            if not choice:
                time.sleep(config.POLL_INTERVAL)
                continue
            skills = self._choice_skills(texts, choice)
            reroll = skill_reroll(texts)
            if (choice.chosen == 0 and not rerolled and reroll is not None
                    and choose(skills, self.build, state, can_reroll=True) is None):
                log.info("No wanted skill in %s: rerolling", [s.name for s in skills])
                rerolled = True
                self._tap(reroll)
                continue
            order = shop_order(skills, self.build, state, can_reroll=False)  # wanted first, then rarest
            if choice.chosen < choice.needed:
                if choice.chosen >= len(choice.cards):
                    self._fail("Skill cards not recognized", img)
                skill = skills[order[choice.chosen]]
                log.info("Skill: %s (%s, %s, %s)", skill.name, skill.rarity, skill.damage_type or "-", skill.role or "-")
                self.device.tap(*choice.cards[order[choice.chosen]])
            else:
                offer = tuple(s.name for s in skills)
                if offer != learned:  # the same offer again = the Learn tap did not land: count it once
                    for i in order[:choice.needed]:
                        state.take(skills[i])
                learned = offer
                rerolled = False  # the next skill step can reroll once too
                self._tap(choice.learn)
        self._fail("Fight did not finish", img)

    def _choice_skills(self, texts: list[Text], choice) -> list[Skill]:
        """The skills on a Dojo / raid pick, in the order of choice.cards. A card whose name was not read
        counts by its rarity only (the build never wants it)."""
        below = config.SKILL_CARD_TAP_BELOW_RARITY
        named = {c.tag.center[1] + below: c for c in parse_skill_cards(texts)}
        rarities = {t.center[1] + below: r for t in texts if (r := rarity_name(t))}
        skills = []
        for _, y in choice.cards:
            card = named.get(y)
            if card:
                if self.catalog is None:
                    self.catalog = Catalog()
                skills.append(self.catalog.lookup(card.name, card.description, card.rarity, L.active_language()))
            else:
                skills.append(Skill("?", None, rarities.get(y, ""), None, "", ""))
        return skills

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

    def _wait_for(self, parse: Callable, what: str, timeout: float | None = None):
        timeout = SCREEN_TIMEOUT if timeout is None else timeout
        deadline = time.monotonic() + timeout
        loading_since = None
        img = None
        while True:
            img, texts = self._capture()
            if is_loading(texts):
                if loading_since is None:
                    loading_since = time.monotonic()
                    log.info("Waiting through Loading for the %s", what)
                if time.monotonic() - loading_since > config.FIGHT_LOADING_WAIT:
                    break
                deadline = max(deadline, time.monotonic() + timeout)
                time.sleep(config.POLL_INTERVAL)
                continue
            loading_since = None
            found = parse(img, texts)
            if found:
                return found
            if time.monotonic() >= deadline:
                break
            time.sleep(config.POLL_INTERVAL)
        self._fail(f"Expected the {what}", img)

    # --- helpers -------------------------------------------------------------------------

    def _capture(self) -> tuple:
        if self._pushed is not None:
            frame = self._pushed
            self._pushed = None
            return frame
        img = self.device.screenshot()
        return img, self.ocr.read(img)

    def _push(self, img, texts: list[Text]) -> None:
        self._pushed = (img, texts)

    def _open_guild(self) -> bool:
        """True once the guild map can be read. Already there: the frame is kept for the caller.
        From the lobby: open it. Not in a guild: False."""
        img, texts = self._capture()
        if is_guild_map(texts):
            self._push(img, texts)
            return True
        if parse_lobby(texts):
            if not in_guild(texts):
                return False
            self.device.tap(*config.GUILD_BUTTON)
            return True
        self._push(img, texts)
        if self._back_to_guild():
            return True
        texts = self._lobby_texts()
        if not in_guild(texts):
            return False
        self.device.tap(*config.GUILD_BUTTON)
        return True

    def _back_to_guild(self) -> bool:
        """Back out of the raid or the guild hall onto the guild map. False if it was not reached."""
        for _ in range(MAX_BACK_STEPS):
            img, texts = self._capture()
            if is_guild_map(texts):
                self._push(img, texts)
                return True
            if parse_lobby(texts):
                return False
            close_text = popup_close(texts)
            close_x = close_button(img) if img is not None else None
            back = back_arrow(img) if img is not None else None
            if close_text:
                self._tap(close_text)
            elif close_x:
                self.device.tap(*close_x)
            elif back:
                self.device.tap(*back)
            elif find(texts, L.RAID_TITLE) or find(texts, L.DONATION_TITLE) or guild_hall_donate(texts):
                self.device.tap(*config.LIST_BACK)
            else:
                time.sleep(config.UI_SETTLE)
        return False

    def _tap(self, t: Text) -> None:
        self.device.tap(*t.center)

    def _press(self, button: Text, left: Callable[[list[Text]], bool] | None = None) -> None:
        """Tap a button that leaves the screen (a mode's Challenge). The game sometimes ignores a tap (a
        toast over the screen, still settling): while the button is still in place after
        PRESS_RETAP_AFTER s, tap it again (a tap that registered leaves the screen, so this never spends
        twice). `left(texts)` tells that it worked when the button stays visible under the next screen."""
        self._tap(button)
        for _ in range(PRESS_RETAPS):
            deadline = time.monotonic() + PRESS_RETAP_AFTER
            while True:
                texts = self._capture()[1]
                if left(texts) if left else not _still_there(button, texts):
                    return
                if time.monotonic() > deadline:
                    break
                time.sleep(config.POLL_INTERVAL)
            if not _still_there(button, texts):
                return  # another screen (popup, loading): the caller's wait handles it
            log.info("The tap on %s did not register, tapping again", button.text)
            self._tap(button)

    def _fail(self, msg: str, img=None) -> None:
        self.nav._fail(msg, self.device.screenshot() if img is None else img)
