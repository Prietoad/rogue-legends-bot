"""Skill cards, reroll, coins and shop on real screenshots; Player skill/shop decisions on fake screens."""

from pathlib import Path

import cv2
import pytest

from roguebot import config, labels
from roguebot.build import Build
from roguebot.play import Player
from roguebot.screens import (LevelScreen, classify_level_screen, parse_money, parse_shop, parse_skill_cards,
                              skill_reroll)
from roguebot.skills import Catalog
from roguebot.vision import Ocr, Text

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def ocr():
    return Ocr()


@pytest.fixture(autouse=True)
def _reset_language():
    yield
    labels.set_language(None)


def load(ocr, name):
    labels.set_language("en" if name.startswith("en_") else "es")
    img = cv2.imread(str(FIXTURES / name))
    return img, ocr.read(img)


@pytest.mark.parametrize("name, cards, reroll, money", [
    ("level_skill_levelup.png", [("common", "Shuriken-Curativo"), ("common", "Escudo enfurecido"),
                                 ("common", "Carámbano de Contraataque")], True, 154),
    ("level_skill_power.png", [("legendary", "Estrellas-Mortales"), ("legendary", "Disipar"),
                               ("legendary", "Dominio de Contraataque")], False, None),
    ("en_level_skill_levelup.png", [("common", "Special-Experiment"), ("common", "Sneaky Poison"),
                                    ("common", "Fire Weapon")], True, 158),
])
def test_skill_cards(ocr, name, cards, reroll, money):
    _, texts = load(ocr, name)
    parsed = parse_skill_cards(texts)
    assert [(c.rarity, c.name) for c in parsed] == cards
    assert all(c.description for c in parsed)
    assert (skill_reroll(texts) is not None) == reroll
    assert parse_money(texts) == money


@pytest.mark.parametrize("name, money, cards, free_reroll", [
    ("level_shop.png", 154, [("Golpe Venenoso", 48, False), ("Aumento de Tasa de Contraataque", 95, False),
                             ("Descarga Definitiva", 95, False)], True),
    ("en_level_shop.png", 216, [("Recovery", 48, False), ("Executioner", 190, False), ("Glass Cannon", 190, False)],
     True),
    ("en_level_shop_sale.png", 205, [("Fire Wave", 48, False), ("Special-Experiment", 95, False),
                                     ("Lifesteal", 95, False)], True),  # sale: the lower (current) price
    ("en_level_shop_sold.png", 157, [("Fire Wave", 48, True), ("Special-Experiment", 95, False),
                                     ("Lifesteal", 95, False)], True),
    ("en_level_shop_rerolled.png", 157, [("Critical Mastery", 95, False), ("Recovery", 95, False),
                                         ("Executioner", 190, False)], False),  # the reroll now costs 10
])
def test_shop(ocr, name, money, cards, free_reroll):
    img, texts = load(ocr, name)
    shop = parse_shop(texts)
    assert shop is not None and shop.money == money
    assert [(c.name, c.cost, c.sold) for c in shop.cards] == cards
    assert (shop.free_reroll is not None) == free_reroll
    assert classify_level_screen(img, texts).kind is LevelScreen.SHOP


# --- Player decisions on fake screens -------------------------------------------------------

class TapLog:
    def __init__(self):
        self.taps = []

    def tap(self, x, y, settle=0):
        self.taps.append((x, y))

    def screenshot(self):
        return None


class Frames:
    def __init__(self, frames):
        self.frames = iter(frames)

    def read(self, img):
        return next(self.frames)


def player(tmp_path, build, frames=()):
    labels.set_language("en")
    return Player(TapLog(), Frames(frames), build, Catalog(tmp_path / "skills.json"))


def card(rarity, name, description, y, price=None):
    texts = [Text(rarity, 280, y - 15, 360, y + 15), Text(name, 450, y + 20, 800, y + 60),
             Text(description, 450, y + 100, 1000, y + 140)]
    if price is not None:
        texts.append(Text(str(price), 1130, y + 180, 1200, y + 220))
    return texts


PROMPT = Text("Select a Skill to learn!", 400, 830, 1040, 870)
REROLL = [Text("Reroll", 650, 2100, 790, 2140), Text("(1)", 690, 2170, 750, 2210)]


def test_player_picks_the_build_skill_and_records_it(tmp_path):
    p = player(tmp_path, Build("magic"))
    screen = [PROMPT, *card("Common", "Sneaky Poison", "When you dodge, apply Poison.", 928),
              *card("Common", "Fire Weapon", "Attacks deal additional fire damage.", 1236), *REROLL]
    assert p._pick_skill(screen) == (720, 1236 + config.SKILL_TAP_BELOW_RARITY)
    assert p._state.taken == ["Fire Weapon"]
    assert set(p.catalog.skills) == {"sneakypoison", "fireweapon"}  # both new skills saved


def test_player_rerolls_once_when_nothing_fits(tmp_path):
    p = player(tmp_path, Build("magic"))
    shield_only = [PROMPT, *card("Common", "Iron Shield", "Gain a Shield.", 928), *REROLL]
    assert p._pick_skill(shield_only) == (720, 2120)  # the reroll button
    assert p._pick_skill(shield_only) == (720, 928 + config.SKILL_TAP_BELOW_RARITY)  # rerolled: take it anyway


def shop_screen(money, cards, free=True):
    texts = [Text("SHOP", 640, 340, 800, 390), Text(str(money), 140, 155, 200, 190),
             Text("Reroll", 780, 2365, 930, 2405), Text("Exit", 380, 2395, 470, 2440),
             Text("FREE" if free else "10", 840, 2435, 930, 2475)]
    for i, (rarity, name, description, price, sold) in enumerate(cards):
        y = 1086 + 334 * i
        texts += card(rarity, name, description, y, price)
        if sold:
            texts.append(Text("SOLD OUT", 500, y + 110, 900, y + 140))
    return texts


RECOVERY = ("Common", "Recovery", "Restore 5% HP.", 48)
FIRE_WAVE = ("Common", "Fire Wave", "Cast Fire Wave.", 95)
EXECUTIONER = ("Legendary", "Executioner", "Execute the enemy.", 190)


def price_at(i):
    return 1165, 1086 + 334 * i + 200


def test_shop_buys_wanted_first_then_what_coins_allow(tmp_path):
    frames = [shop_screen(155, [(*RECOVERY, False), (*FIRE_WAVE, True), (*EXECUTIONER, False)], free=False),
              shop_screen(107, [(*RECOVERY, True), (*FIRE_WAVE, True), (*EXECUTIONER, False)], free=False)]
    p = player(tmp_path, Build("magic"), frames)
    p._shop(shop_screen(250, [(*RECOVERY, False), (*FIRE_WAVE, False), (*EXECUTIONER, False)]))
    # Fire Wave (wanted) first; then 155 coins: Executioner (190) is too expensive, Recovery (48) fits.
    assert p.device.taps == [price_at(1), price_at(0)]
    assert p._state.taken == ["Fire Wave", "Recovery"]


def test_shop_uses_the_free_reroll_when_nothing_fits(tmp_path):
    frames = [shop_screen(100, [(*FIRE_WAVE, False)], free=False), shop_screen(5, [(*FIRE_WAVE, True)], free=False)]
    p = player(tmp_path, Build("magic"), frames)
    p._shop(shop_screen(100, [(*RECOVERY, False)]))
    assert p.device.taps == [(855, 2385), price_at(0)]  # free reroll, then the fire skill


def test_shop_without_coins_buys_nothing(tmp_path):
    p = player(tmp_path, Build("magic"))
    p._shop(shop_screen(20, [(*FIRE_WAVE, False)], free=False))
    assert p.device.taps == []


def test_card_without_a_readable_name_is_skipped():
    """OCR missed the name: the first description line must not be taken as the name."""
    labels.set_language("en")
    texts = [PROMPT, Text("Mythic", 280, 913, 360, 943), Text("after your first death.", 450, 1040, 900, 1080),
             *card("Common", "Fire Wave", "Every turn cast Fire Wave.", 1236)]
    assert [c.name for c in parse_skill_cards(texts)] == ["Fire Wave"]


def test_x2_rewards_button_that_stays_is_given_up_for_continue(monkeypatch):
    """Review: if the x2 button stays after the ad, the bot tapped it until the stuck guard fired."""
    import numpy as np
    from roguebot import play
    from roguebot.screens import LevelScreen, LevelState
    from roguebot.vision import Text
    monkeypatch.setattr(play.time, "sleep", lambda s: None)
    end = [Text("Continuar", 600, 2360, 840, 2400), Text("x2 Recompensas", 1000, 2200, 1300, 2240)]
    states = iter([LevelState(LevelScreen.DOUBLE_REWARD, (1150, 2220))] * 3 + [LevelState(LevelScreen.VICTORY, (720, 2380))])
    monkeypatch.setattr(play, "classify_level_screen", lambda img, texts: next(states))
    taps = []

    class Dev:
        def screenshot(self):
            return np.zeros((10, 10, 3), np.uint8)

        def tap(self, x, y, settle=0):
            taps.append((x, y))

    class Ocr:
        def read(self, img):
            return end
    labels.set_language("es")
    try:
        assert play.Player(Dev(), Ocr(), catalog=object()).play_level() is LevelScreen.VICTORY
    finally:
        labels.set_language(None)
    assert taps == [(1150, 2220), (1150, 2220), (720, 2380), (720, 2380)]  # 2 tries, then Continue
