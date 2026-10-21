"""Export the desktop bot's recognition results for the phone app's parity tests.

For every tests/fixtures/*.png: the OCR boxes (full frame and the region crops the parsers ask for)
and what every Python parser returns. The Kotlin tests (ParityTest) feed the same OCR boxes and the
same image to the Kotlin parsers and must get the same results. Run after changing a parser or adding
a fixture:  python phone/tools/export_parity.py
"""

import dataclasses
import enum
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from roguebot import labels as L  # noqa: E402
from roguebot import mode_screens as M  # noqa: E402
from roguebot import screens as S  # noqa: E402
from roguebot.navigation import Navigator  # noqa: E402
from roguebot.vision import Ocr, Text  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
OUT = ROOT / "phone" / "android" / "bot" / "src" / "test" / "resources" / "parity.json"


def ser(v):
    if isinstance(v, Text):
        return [v.text, v.x1, v.y1, v.x2, v.y2]
    if isinstance(v, enum.Enum):
        return v.value
    if dataclasses.is_dataclass(v):
        return {f.name: ser(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, (list, tuple)):
        return [ser(x) for x in v]
    if hasattr(v, "item"):  # numpy scalars
        return v.item()
    return v


class RecordingOcr:
    def __init__(self, ocr: Ocr):
        self.ocr = ocr
        self.regions: dict[str, list] = {}

    def read(self, img, region=None):
        texts = self.ocr.read(img, region)
        if region is not None:
            self.regions[",".join(map(str, region))] = [ser(t) for t in texts]
        return texts


def outputs(img, texts, ocr) -> dict:
    out = {
        "parse_lobby": S.parse_lobby(texts),
        "is_star_list": S.is_star_list(texts),
        "parse_energy": S.parse_energy(texts),
        "parse_elite_dialog": S.parse_elite_dialog(texts),
        "parse_energy_popup": S.parse_energy_popup(img, texts),
        "update_required": S.update_required(texts),
        "resume_prompt": S.resume_prompt(texts),
        "on_board": Navigator._on_board(img, texts),
        "is_loading": S.is_loading(texts),
        "close_button": S.close_button(img),
        "tutorial_hand": S.tutorial_hand(img),
        "footer_visible": S.footer_visible(img),
        "popup_close": S.popup_close(texts),
        "classify_level_screen": S.classify_level_screen(img, texts),
        "game_speed": S.game_speed(texts),
        "dice_ready": S.dice_ready(img),
        "dice_auto": S.dice_auto(img),
        "parse_star_list": S.parse_star_list(img, texts, ocr) if S.is_star_list(texts) else None,
        "parse_skill_cards": S.parse_skill_cards(texts),
        "skill_reroll": S.skill_reroll(texts),
        "parse_money": S.parse_money(texts),
        "parse_shop": S.parse_shop(texts),
        "parse_fortune_teller": S.parse_fortune_teller(texts),
        "back_arrow": M.back_arrow(img),
        "in_guild": M.in_guild(texts),
        "vip_cards_icon": M.vip_cards_icon(texts),
        "vip_claim_all": M.vip_claim_all(texts),
        "guild_hall": M.guild_hall(texts),
        "guild_hall_donate": M.guild_hall_donate(texts),
        "free_donation": M.free_donation(texts),
        "parse_patrol": M.parse_patrol(texts),
        "parse_quick_patrol": M.parse_quick_patrol(img, texts),
        "is_modes_list": M.is_modes_list(texts),
        "parse_arena": M.parse_arena(img, texts, ocr),
        "parse_arena_opponents": M.parse_arena_opponents(texts),
        "parse_tower": M.parse_tower(texts),
        "parse_dojo": M.parse_dojo(img, texts, ocr),
        "parse_dive": M.parse_dive(texts),
        "menu_daily": M.menu_entry(texts, L.MENU_DAILY),
        "menu_mail": M.menu_entry(texts, L.MENU_MAIL),
        "daily_claim": M.daily_claim(texts),
        "mail_claim_all": M.mail_claim_all(texts),
        "parse_dungeon_popup": M.parse_dungeon_popup(texts),
        "parse_raid": M.parse_raid(texts),
        "parse_skill_choice": M.parse_skill_choice(texts),
        "parse_fight_result": M.parse_fight_result(texts),
    }
    for name in ("ARENA", "DOJO", "TOWER", "DIVE", "MINES", "PETS"):
        entry = M.mode_entry(texts, getattr(L, name))
        out[f"mode_entry_{name}"] = entry
        out[f"mode_closed_{name}"] = M.mode_closed(texts, entry) if entry else None
    return {k: ser(v) for k, v in out.items()}


def main() -> None:
    ocr = RecordingOcr(Ocr())
    cases = {}
    for path in sorted(FIXTURES.glob("*.png")):
        img = cv2.imread(str(path))
        L.set_language(None)
        texts = ocr.ocr.read(img)
        detected = L.detect_language(texts)
        lang = "en" if path.name.startswith("en_") else "es"
        L.set_language(lang)
        ocr.regions = {}
        out = outputs(img, texts, ocr)
        out["detect_language"] = detected
        cases[path.name] = {"lang": lang, "texts": [ser(t) for t in texts], "regions": ocr.regions, "out": out}
        print(path.name, flush=True)
    L.set_language(None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cases, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{len(cases)} fixtures -> {OUT}")


if __name__ == "__main__":
    main()
