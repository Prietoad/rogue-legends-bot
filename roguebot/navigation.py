"""Menu navigation: from anywhere in the main UI to the start of the requested level."""

import logging
import time
from typing import Callable
from pathlib import Path

import cv2

from roguebot import config, labels
from roguebot.device import Device
from roguebot.mode_screens import back_arrow, parse_fight_result
from roguebot.screens import (Card, LevelScreen, Lobby, Mode, classify_level_screen, close_button, close_button_any_size,
                              footer_visible, is_loading, is_star_list, lobby_behind, outside_tap_clear,
                              parse_elite_dialog, parse_energy, parse_energy_popup, parse_lobby, parse_star_list, popup_close,
                              resume_prompt, tutorial_hand, update_required)
from roguebot.vision import Ocr, Text, find, parse_level_number

log = logging.getLogger(__name__)

DEBUG_DIR = Path("debug")
MAX_SCROLLS = 15
MAX_LOBBY_ATTEMPTS = 16  # popups chain after returning from a level (a new chapter: 6+ in a row)
MAX_ENERGY_CLAIMS = 15  # popup reads while claiming: Daily Pack + up to 3 videos, with screens in between
FEATURE_READS = 3  # lobby reads before deciding a button is missing (not unlocked), not just missed by OCR
VIDEO_COOLDOWN_REREADS = 3  # chances left but no yellow button (just after a video): re-read before giving up
MAX_ENERGY_REOPENS = 2  # a lobby promo can cover the energy popup: close it and open the energy popup again
LEVEL_LOAD_TIMEOUT = 20  # seconds
START_RETAP_AFTER = 4    # seconds with the start button still in place before tapping it again
START_RETAPS = 2
LANGUAGE_ATTEMPTS = 3


IN_LEVEL = (LevelScreen.BOARD_READY, LevelScreen.AUTO_PLAY, LevelScreen.FIGHT, LevelScreen.SKILL_PICK, LevelScreen.SHOP,
            LevelScreen.EVENT, LevelScreen.DICE_DUEL, LevelScreen.FLIP_CARDS, LevelScreen.REVIVE, LevelScreen.VICTORY,
            LevelScreen.DEFEAT, LevelScreen.DOUBLE_REWARD, LevelScreen.FORTUNE_TELLER)  # only seen inside a level (not Continue/Leave buttons)
# A level board found by go_to_lobby, played out instead of failing (the level is lost on a restart). Not
# fights or skill picks alone: dojo and raid fights have them too.
ON_BOARD = (LevelScreen.BOARD_READY, LevelScreen.AUTO_PLAY, LevelScreen.SHOP, LevelScreen.EVENT,
            LevelScreen.DICE_DUEL, LevelScreen.FLIP_CARDS, LevelScreen.REVIVE, LevelScreen.FORTUNE_TELLER)


class NavigationError(Exception):
    pass


class LevelUnavailable(NavigationError):
    """The requested level is locked or does not exist: restarting cannot fix it."""


class StarsUnavailable(LevelUnavailable):
    """No Desafío de Estrellas (not unlocked on this account) or no beaten level to replay yet."""


class EliteUnavailable(LevelUnavailable):
    """Elite mode is not unlocked on this account."""


def _same_place(a: Text, b: Text) -> bool:
    return abs(a.center[0] - b.center[0]) < 20 and abs(a.center[1] - b.center[1]) < 20


def _still_there(button: Text, texts: list[Text]) -> bool:
    """The same button text is still shown at the same place."""
    return any(t.norm == button.norm and abs(t.center[0] - button.center[0]) < 40
               and abs(t.center[1] - button.center[1]) < 40 for t in texts)


class Navigator:
    def __init__(self, device: Device, ocr: Ocr, dry_run: bool = False, ads: bool = False):
        self.device = device
        self.ocr = ocr
        self.dry_run = dry_run
        self.ads = ads  # watch ads (energy videos); only with an account that skips them
        self.resume_level: Callable[[], object] | None = None  # plays an interrupted run to its end

    # --- public API -------------------------------------------------------------------

    def start_latest(self, mode: Mode) -> int | None:
        """Start the last unlocked level of the mode (lobby INICIO/LISTO button); returns its number."""
        lobby = self._set_mode(mode)
        log.info("Starting latest %s level: %s", mode.value, lobby.level_title)
        self._press_start(lobby.start_button, mode)
        return parse_level_number(lobby.level_title or "")

    def start_last_beaten(self, mode: Mode) -> int:
        """Start the last beaten level: the one before the lobby's (last unlocked) level, from
        Desafío de Estrellas. Returns its number."""
        lobby = self._set_mode(mode)
        latest = parse_level_number(lobby.level_title or "")
        if latest is None or latest < 2:
            self._fail(f"No beaten {mode.value} level (lobby level: {lobby.level_title})", self.device.screenshot(),
                       StarsUnavailable)
        self.start_star_challenge(mode, latest - 1)
        return latest - 1

    def start_star_challenge(self, mode: Mode, level: int) -> None:
        """Start an already beaten level from the Desafio de Estrellas list."""
        self._open_star_list(mode)
        card = self._scroll_to(level)
        log.info("Starting %s star challenge: %s", mode.value, card.header.text)
        self._press_start(card.button, mode)

    def start_pending_stars(self, mode: Mode) -> int | None:
        """Start a beaten level that still misses stars (each star gives rewards, diamonds included).
        The list opens near its end: scan upwards, page by page. Returns the level, or None if every
        beaten level has 3 stars (nothing started)."""
        self._open_star_list(mode)
        prev = None
        for _ in range(MAX_SCROLLS):
            img, texts = self._capture()
            cards = parse_star_list(img, texts, self.ocr)
            pending = [c for c in cards if c.button and c.stars < 3]
            if pending:
                card = max(pending, key=lambda c: c.number)  # nearest to the end: fewest scrolls
                card = self._scroll_to(card.number)  # settled position (scroll inertia)
                log.info("Starting %s star challenge for missing stars: %s (%d/3)", mode.value, card.header.text,
                         card.stars)
                self._press_start(card.button, mode)
                return card.number
            numbers = [c.number for c in cards]
            if not numbers or numbers == prev or numbers[0] == 1:
                break
            prev = numbers
            self._drag_list(-config.MAX_DRAG)  # towards lower levels
        log.info("Every beaten %s level has 3 stars", mode.value)
        return None

    def _open_star_list(self, mode: Mode) -> None:
        lobby = self._set_mode(mode)
        if lobby.stars_button is None:
            lobby = self._lobby_until(lambda lobby: lobby.stars_button is not None)
        if lobby.stars_button is None:
            self._fail("Desafio de Estrellas is not unlocked on this account", self.device.screenshot(), StarsUnavailable)
        self._tap_text(lobby.stars_button)
        img, texts = self._capture_change(is_star_list)
        if not is_star_list(texts):
            self._fail("Desafio de Estrellas list did not open", img)

    def level_in_progress(self) -> bool:
        """A level is on screen: the bot was stopped or restarted mid-level while the game kept running
        (go_to_lobby can't leave a level board)."""
        img, texts = self._capture()
        return classify_level_screen(img, texts).kind in IN_LEVEL and not lobby_behind(texts)

    def wait_for_lobby(self, timeout: float) -> Lobby:
        """Just after opening the game (splash, loading, login popups): retry until the lobby shows."""
        from roguebot.emulator import EmulatorError
        deadline = time.monotonic() + timeout
        while True:
            try:
                return self.go_to_lobby()
            except NavigationError:
                if time.monotonic() > deadline:
                    raise EmulatorError("err_game_load", seconds=round(timeout))

    def detect_language(self) -> str:
        """Read the game language from the lobby and match only its labels from then on."""
        labels.set_language(None)
        for _ in range(LANGUAGE_ATTEMPTS):
            # The game can leave the lobby on its own (a new event opens after the daily reset): retry.
            self.go_to_lobby()
            img, texts = self._capture()
            lang = labels.detect_language(texts)
            if lang:
                break
        else:
            self._fail("Could not detect the game language in the lobby", img)
        labels.set_language(lang)
        log.info("Game language: %s", lang)
        return lang

    def claim_free_energy(self) -> int:
        """Open the energy popup and take every free option (Daily Pack, videos).

        Never taps the gem-priced button. Returns the energy in the lobby afterwards.
        """
        self.go_to_lobby()
        self.device.tap(*config.ENERGY_ICON)
        reopened = rereads = 0
        for _ in range(MAX_ENERGY_CLAIMS):
            img, texts = self._capture()
            reward = None if popup_close(texts) else find(texts, labels.TAP_TO_CLAIM)
            if reward:  # the claimed energy shows over the popup and hides its video button and counter
                self._tap_text(reward)
                continue
            offers = parse_energy_popup(img, texts)
            if offers is None:
                close = popup_close(texts)
                if close:  # a lobby promo popped up late, over or instead of the energy popup
                    log.info("Closing popup")
                    self._tap_text(close)
                    if reopened < MAX_ENERGY_REOPENS and parse_lobby(self._capture()[1]):
                        self.device.tap(*config.ENERGY_ICON)
                        reopened += 1
                else:  # an ad or a reward screen in between: let it finish
                    time.sleep(config.UI_SETTLE)
                continue
            if offers.free_pack:
                log.info("Claiming free Daily Pack energy")
                self._tap_text(offers.free_pack)
            elif offers.video and self.ads:
                log.info("Watching a video for energy")
                self.device.tap(*offers.video, settle=config.VIDEO_SETTLE)
            elif offers.videos_left and self.ads and rereads < VIDEO_COOLDOWN_REREADS:
                if rereads == 0:  # backlog: the cooldown state was never captured; keep it for a fixture
                    self._save(img, "energy_cooldown")
                log.info("Videos left (%d) but no video button yet, waiting", offers.videos_left)
                rereads += 1
                time.sleep(config.VIDEO_SETTLE)
            elif offers.videos_left and not self.ads:  # only videos left, and ads are off
                log.info("No free energy left to claim (videos are off)")
                self.device.tap(*config.ENERGY_POPUP_CLOSE)
                return self.go_to_lobby().energy or 0
            else:
                log.info("No free energy left to claim (screenshot: %s)", self._save(img, "energy_none"))
                self.device.tap(*config.ENERGY_POPUP_CLOSE)
                return self.go_to_lobby().energy or 0
        self._fail("Energy popup did not settle", img)

    # --- steps --------------------------------------------------------------------------

    def go_to_lobby(self) -> Lobby:
        hand_taps = 0
        unknown = 0  # frames in a row on a popup over the lobby that nothing below recognized
        for _ in range(MAX_LOBBY_ATTEMPTS + config.TUTORIAL_MAX_STEPS):
            img, texts = self._capture()
            hand = tutorial_hand(img) if hand_taps < config.TUTORIAL_MAX_STEPS else None
            if hand:  # a forced tutorial blocks every other tap: follow it, then back out of what it opened
                log.info("Following the tutorial hand")
                self.device.tap(*hand)
                hand_taps += 1
                continue
            if update_required(texts):  # the bot never drives Google Play: the user updates the game
                from roguebot.emulator import EmulatorError
                raise EmulatorError("err_game_update")
            resume = resume_prompt(texts)
            if resume:  # an interrupted run: its energy is spent, so play it out instead of abandoning it
                if self.resume_level is None:
                    self._fail("An interrupted level is waiting to be resumed", img)
                log.info("Resuming the interrupted level")
                self._tap_text(resume)
                self.resume_level()
                continue
            lobby = parse_lobby(texts)
            if lobby:
                return lobby
            # Never tap blindly: popups can hold purchase buttons.
            close_text, close_x = popup_close(texts), close_button(img)
            end = self._end_button(img, texts)
            if is_loading(texts):
                time.sleep(config.UI_SETTLE)
            elif close_text:
                log.info("Closing popup")
                self._tap_text(close_text)
            elif close_x:
                log.info("Closing popup (✕)")
                self.device.tap(*close_x)
            elif end:  # a level or mode fight ended and nothing took its result (a part that failed in it)
                log.info("Leaving a result screen")
                self.device.tap(*end)
            elif self.resume_level and self._on_board(img, texts):  # a level is still running (go_to_lobby can't leave it)
                log.info("A level is on screen: playing it out")
                self.resume_level()
            elif is_star_list(texts):
                log.info("In star challenge list, going back")
                self.device.tap(*config.LIST_BACK)
            elif back := back_arrow(img):  # modes, arena, tower, guild screens
                # Before the footer check: on mode screens the footer tab spot is their Challenge button.
                log.info("In a menu, going back")
                self.device.tap(*back)
            elif footer_visible(img):
                log.info("Not in Aventura lobby, tapping footer tab")
                self.device.tap(*config.AVENTURA_TAB)
            elif lobby_behind(texts):  # a popup we don't know (new seasonal events): improvise after a few frames
                unknown += 1
                if unknown >= config.UNKNOWN_POPUP_PATIENCE:  # its "para cerrar" text may blink: give it time first
                    self._improvise_close(img, texts)
                    unknown = 0
                else:
                    time.sleep(config.UI_SETTLE)
            elif not self._leave_other_app():  # loading, animation or a screen we don't know: wait, never guess
                time.sleep(config.UI_SETTLE)
        self._fail("Could not reach the Aventura lobby", img)

    def _improvise_close(self, img, texts: list[Text]) -> None:
        """An unknown popup over the lobby: its ✕ at another size, else a tap outside it (the dimmed
        footer), never inside it (popups hold purchase buttons). The frame is saved to add it later."""
        path = self._save(img, "popup_unknown")
        if close_x := close_button_any_size(img):
            log.info("Unknown popup: closing its ✕ (screenshot: %s)", path)
            self.device.tap(*close_x)
        elif outside_tap_clear(texts):
            log.info("Unknown popup: tapping outside it (screenshot: %s)", path)
            self.device.tap(*config.POPUP_OUTSIDE_TAP)
        else:
            log.info("Unknown popup with text where the bot would tap outside it: waiting (screenshot: %s)", path)
            time.sleep(config.UI_SETTLE)

    @staticmethod
    def _end_button(img, texts: list[Text]) -> tuple[int, int] | None:
        """The button of a level end (VICTORIA/DERROTA + Continuar/Confirmar) or mode fight result screen."""
        state = classify_level_screen(img, texts)
        if state.kind in (LevelScreen.VICTORY, LevelScreen.DEFEAT):
            return state.tap
        result = parse_fight_result(texts)
        return result.button.center if result else None

    @staticmethod
    def _on_board(img, texts: list[Text]) -> bool:
        if lobby_behind(texts):  # a popup over the lobby, whatever it looks like
            return False
        kind = classify_level_screen(img, texts).kind
        if kind is LevelScreen.SKILL_PICK:  # a level's level-up pick, not the dojo/raid skill step
            return find(texts, labels.LEARN_SKILLS) is None
        return kind in ON_BOARD

    def _leave_other_app(self) -> bool:
        """Another app is in front of the game: an ad the emulator shows for other apps, or the page such
        an ad opened. Back, then bring the game to the front; an ad that only closes by tapping it is
        tapped (it opens another app or tab) and left the same way. True if another app was in front."""
        package = self.device.foreground_package()
        if package == config.PACKAGE:
            return False
        log.info("Another app is in front (%s), going back to the game", package)
        for tap_ad in (False, True):
            if tap_ad:
                log.info("Tapping the ad to close it")
                self.device.tap(*config.OTHER_APP_AD_TAP, settle=config.VIDEO_SETTLE)
            for _ in range(config.BROWSER_BACK_MAX):
                if self.device.foreground_package() == config.PACKAGE:
                    return True
                self.device.back()
            self.device.launch(config.PACKAGE)
            if self.device.foreground_package() == config.PACKAGE:
                return True
        return True  # go_to_lobby keeps trying and fails with a screenshot

    def _set_mode(self, mode: Mode) -> Lobby:
        lobby = self._lobby_until(lambda lobby: lobby.mode == mode or lobby.has_elite)
        if lobby.mode != mode and not lobby.has_elite:
            self._fail("Elite mode is not unlocked on this account", self.device.screenshot(), EliteUnavailable)
        if lobby.mode != mode:
            log.info("Switching mode %s -> %s", lobby.mode.value, mode.value)
            self.device.tap(*config.ELITE_TOGGLE)
            deadline = time.monotonic() + config.CHANGE_TIMEOUT
            while (lobby := self.go_to_lobby()).mode != mode:  # the first frames can still show the old mode
                if time.monotonic() > deadline:
                    self._fail(f"Mode toggle did not switch to {mode.value}", self.device.screenshot())
                time.sleep(config.POLL_INTERVAL)
        return lobby

    def _lobby_until(self, ok: Callable[[Lobby], bool]) -> Lobby:
        """OCR can miss a button on one frame: read the lobby again before deciding it is not there."""
        for _ in range(FEATURE_READS):
            lobby = self.go_to_lobby()
            if ok(lobby):
                break
        return lobby

    def _scroll_to(self, level: int) -> Card:
        prev_numbers, prev_target = None, None
        for _ in range(MAX_SCROLLS):
            img, texts = self._capture()
            cards = parse_star_list(img, texts, self.ocr)
            numbers = [c.number for c in cards]
            log.debug("Visible cards: %s", numbers)
            if not cards:
                self._fail("No level cards recognized in the list", img)

            target = next((c for c in cards if c.number == level), None)
            if target and target.button:
                if prev_target and _same_place(prev_target.button, target.button):
                    return target
                # The list may still be gliding (inertia): only tap a button seen twice in the same place.
                prev_target = target
                time.sleep(config.SCROLL_SETTLE)
                continue
            if target and target.header.center[1] < config.LIST_BOTTOM - config.HEADER_ABOVE_BUTTON:
                # Header well inside the view but no start button below it.
                self._fail(f"Level {level} is locked", img, LevelUnavailable)
            if numbers == prev_numbers:
                self._fail(f"Level {level} not found (list ends at {numbers[-1]})", img, LevelUnavailable)
            prev_numbers = numbers
            self._drag_list(self._scroll_delta(cards, level))
        self._fail(f"Level {level} not reached after {MAX_SCROLLS} scrolls", img)

    @staticmethod
    def _scroll_delta(cards: list[Card], level: int) -> int:
        """Pixels to scroll (positive = down) to bring the level's header to TARGET_HEADER_Y."""
        ref = min(cards, key=lambda c: abs(c.number - level))
        target_y = ref.header.center[1] + (level - ref.number) * config.CARD_PITCH
        delta = target_y - config.TARGET_HEADER_Y
        if abs(delta) < config.MIN_DRAG:  # a too-short swipe can register as a tap
            delta = config.MIN_DRAG if delta >= 0 else -config.MIN_DRAG
        return max(-config.MAX_DRAG, min(config.MAX_DRAG, delta))

    def _drag_list(self, delta: int) -> None:
        # Finger moves opposite to the scroll direction; keep the whole path inside the list.
        start_y = config.LIST_BOTTOM - 100 if delta > 0 else config.LIST_TOP + 100
        self.device.swipe((config.SCROLL_X, start_y), (config.SCROLL_X, start_y - delta),
                          duration=config.SCROLL_DURATION)

    def _press_start(self, button: Text, mode: Mode) -> None:
        if mode is Mode.ELITE:
            self._tap_text(button)  # opens the "Modo Élite" dialog; nothing is spent yet
            button = self._set_elite_cost()
            if self.dry_run:
                log.info("[dry-run] would tap '%s' at %s", button.text, button.center)
                self.device.tap(*config.ELITE_DIALOG_CLOSE)
                return
        elif self.dry_run:
            log.info("[dry-run] would tap '%s' at %s", button.text, button.center)
            return
        self._tap_text(button)
        deadline = time.monotonic() + LEVEL_LOAD_TIMEOUT
        last_tap, retaps = time.monotonic(), 0
        while time.monotonic() < deadline:
            img, texts = self._capture()
            if classify_level_screen(img, texts).kind is not LevelScreen.UNKNOWN:
                log.info("Level started")
                return
            if (_still_there(button, texts) and retaps < START_RETAPS
                    and time.monotonic() - last_tap > START_RETAP_AFTER):
                # The tap did not register (screen still settling): the button is still in place, and
                # a start that registered would have left this screen, so tapping again is safe.
                log.info("Start tap did not register, tapping again")
                self._tap_text(button)
                last_tap, retaps = time.monotonic(), retaps + 1
                deadline = max(deadline, last_tap + LEVEL_LOAD_TIMEOUT)
            time.sleep(1)
        self._fail("Level did not start (no in-level screen detected)", img)

    def _set_elite_cost(self) -> Text:
        """Set the elite run cost to the highest of ELITE_COSTS the current energy allows.

        The +/- buttons go up to 15 regardless of energy, so the cap is computed here.
        Returns the dialog's INICIO button.
        """
        img, texts = self._capture()
        energy = parse_energy(texts)
        if energy is None:
            self._fail("Could not read the energy counter", img)
        affordable = [c for c in config.ELITE_COSTS if c <= energy]
        if not affordable:
            self._fail(f"Not enough energy for an elite run ({energy})", img)
        target = max(affordable)
        for _ in range(2 * len(config.ELITE_COSTS)):
            dialog = parse_elite_dialog(texts)
            if not dialog:
                self._fail("Elite dialog not recognized", img)
            if dialog.cost == target:
                log.info("Elite cost set to %d (energy %d)", target, energy)
                return dialog.start_button
            self.device.tap(*(config.ELITE_COST_PLUS if dialog.cost < target else config.ELITE_COST_MINUS))
            img, texts = self._capture_change(lambda t: (d := parse_elite_dialog(t)) is None or d.cost != dialog.cost)
        self._fail(f"Could not set elite cost to {target}", img)

    # --- helpers ------------------------------------------------------------------------

    def _capture(self) -> tuple:
        img = self.device.screenshot()
        return img, self.ocr.read(img)

    def _capture_change(self, changed: Callable[[list[Text]], bool]) -> tuple:
        """Capture until changed(texts) (a tap's effect is visible) or CHANGE_TIMEOUT; returns the last
        capture. Deciding on a frame from before the change would repeat the tap."""
        deadline = time.monotonic() + config.CHANGE_TIMEOUT
        while True:
            img, texts = self._capture()
            if changed(texts) or time.monotonic() > deadline:
                return img, texts
            time.sleep(config.POLL_INTERVAL)

    def _tap_text(self, t: Text) -> None:
        self.device.tap(*t.center)

    def _save(self, img, name: str) -> Path:
        DEBUG_DIR.mkdir(exist_ok=True)
        path = DEBUG_DIR / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        cv2.imwrite(str(path), img)
        return path

    def _fail(self, msg: str, img, error: type[NavigationError] = NavigationError) -> None:
        path = self._save(img, "fail")
        raise error(f"{msg} (screenshot: {path})")
