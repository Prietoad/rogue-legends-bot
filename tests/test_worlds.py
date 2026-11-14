"""Worlds (the "Mapa Mundial": Everdale, Heliora) and what Heliora's levels added: forks, events with
described options, shop stat items, the treasure miner. Real screenshots + fake screens."""

import numpy as np
import pytest

from roguebot import config, labels, navigation, strategy
from roguebot.build import Build
from roguebot.navigation import Navigator
from roguebot.request import RunRequest, build_request
from roguebot.screens import (DIRT, EMPTY, TREASURE, LevelScreen, parse_anvil, parse_contracts, Lobby, Mode, classify_level_screen, event_options,
                              miner_tile, miner_tiles, parse_hp, parse_lobby, parse_money, parse_paths, parse_shop,
                              parse_skill_cards, parse_world_map, treasures_left)
from roguebot.vision import Text, parse_level_number, parse_world_number
from test_logic import _TapLog
from test_screens import load
from test_skill_screens import FIRE_WAVE, card, player, price_at, shop_screen, PROMPT


@pytest.fixture(autouse=True)
def _reset_language():
    yield
    labels.set_language(None)


# --- worlds ------------------------------------------------------------------------------------

def test_level_titles_of_other_worlds():
    assert parse_level_number("2-1. Elysium I") == 1 and parse_world_number("2-1. Elysium I") == 2
    assert parse_level_number("2-14. Elysium (Élite) II") == 14
    assert parse_world_number("81. Picos Helados XII") == 1 and parse_level_number("81. Picos Helados XII") == 81
    assert parse_world_number("Temporada 25") is None


@pytest.mark.parametrize("name, mode, title", [("lobby_heliora_normal.png", Mode.NORMAL, "2-1. Elysium I"),
                                               ("lobby_heliora_elite.png", Mode.ELITE, "2-1. Elysium (Élite) I")])
def test_lobby_of_the_second_world(ocr, name, mode, title):
    _, texts = load(ocr, name)
    lobby = parse_lobby(texts)
    assert lobby.mode is mode and lobby.level_title == title and lobby.world == 2 and lobby.energy == 16
    assert abs(lobby.map_button.center[0] - 430) < 40 and abs(lobby.map_button.center[1] - 1923) < 20  # the compass
    # OCR joined "Patrulla de Estrellas" on the normal lobby: the stars button is still tapped on its own icon.
    assert abs(lobby.stars_button.center[0] - 1000) < 30


def test_first_world_lobby_has_no_prefix(ocr):
    _, texts = load(ocr, "lobby_vip_icon.png")  # from before the worlds update: no compass
    lobby = parse_lobby(texts)
    assert lobby.world == 1 and lobby.map_button is None


@pytest.mark.parametrize("name", ["world_map.png", "world_map_everdale.png"])
def test_world_map(ocr, name):
    """The map is drawn around the current world: the islands move, their name labels are what is tapped."""
    img, texts = load(ocr, name)
    worlds = parse_world_map(texts)
    assert set(worlds) == {"everdale", "heliora"}  # "Portal del Caos" (locked, beta) is not a known world
    assert worlds["heliora"].center[0] < worlds["everdale"].center[0]
    assert parse_lobby(texts) is None and classify_level_screen(img, texts).kind is LevelScreen.UNKNOWN


def test_lobby_is_not_the_world_map(ocr):
    _, texts = load(ocr, "lobby_heliora_normal.png")
    assert parse_world_map(texts) is None


MAP_BUTTON = Text("Mundial", 374, 1904, 522, 1943)
MAP = [Text("Mapa Mundial", 504, 99, 932, 185), Text("Heliora", 460, 1523, 605, 1567),
       Text("Everdale", 690, 2220, 866, 2272), Text("Portal del Caos", 1116, 1344, 1343, 1379)]


def _lobby(title, compass=True):
    return [Text("Patrulla", 739, 1904, 884, 1943), Text("APAGADO", 880, 2064, 987, 2090),
            Text("INICIO", 532, 2047, 785, 2136), Text(title, 415, 540, 1020, 615), Text("16/38", 794, 64, 916, 105),
            *([MAP_BUTTON] if compass else [])]


def _world_nav(monkeypatch, frames, world):
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)
    clock = iter(range(10_000))
    monkeypatch.setattr(navigation.time, "monotonic", lambda: next(clock) * 1.0)
    labels.set_language("es")
    nav = Navigator(_TapLog(), None, world=world)
    frames = iter(frames)
    last = []
    black = np.zeros((2560, 1440, 3), np.uint8)

    def capture():  # the last frame repeats (the screen the navigation ends on)
        last[:] = [next(frames, last[0] if last else None)]
        return black, last[0]
    nav._capture = capture
    nav.saved = []
    nav._save = lambda img, name: nav.saved.append(name) or "debug/x.png"
    return nav


def test_switching_world_goes_through_the_map(monkeypatch):
    everdale, heliora = _lobby("81. Picos Helados XII"), _lobby("2-1. Elysium I")
    nav = _world_nav(monkeypatch, [everdale, MAP, MAP, heliora], "heliora")
    lobby = nav._set_mode(Mode.NORMAL)
    assert lobby.world == 2 and nav.world == "heliora"
    assert nav.device.taps == [MAP_BUTTON.center, MAP[1].center]  # the compass, then the island's name


def test_the_wanted_world_already_showing_needs_no_tap(monkeypatch):
    nav = _world_nav(monkeypatch, [_lobby("2-1. Elysium I")], "heliora")
    assert nav._set_mode(Mode.NORMAL).world == 2 and nav.device.taps == []
    nav = _world_nav(monkeypatch, [_lobby("81. Picos Helados XII")], "everdale")
    assert nav._set_mode(Mode.NORMAL).world == 1 and nav.device.taps == []


def test_no_world_chosen_never_opens_the_map(monkeypatch):
    nav = _world_nav(monkeypatch, [_lobby("81. Picos Helados XII")], None)
    assert nav._set_mode(Mode.NORMAL).world == 1 and nav.device.taps == []


def test_account_without_worlds_plays_where_it_is(monkeypatch, caplog):
    """Missing features never stop the run: no compass -> the current world, and no more tries."""
    nav = _world_nav(monkeypatch, [_lobby("13. Bosque Embrujado II", compass=False)], "heliora")
    assert nav._set_mode(Mode.NORMAL).world == 1
    assert nav.world is None and nav.device.taps == [] and "no World Map" in caplog.text
    nav = _world_nav(monkeypatch, [_lobby("13. Bosque Embrujado II", compass=False)], "everdale")
    assert nav._set_mode(Mode.NORMAL).world == 1 and nav.world == "everdale"  # the first world: nothing to switch


def test_world_missing_from_the_map_is_given_up(monkeypatch, caplog):
    everdale = _lobby("81. Picos Helados XII")
    nav = _world_nav(monkeypatch, [everdale, [MAP[0], MAP[2]], [MAP[0], MAP[2]], everdale], "heliora")
    monkeypatch.setattr(nav, "go_to_lobby", lambda: parse_lobby(everdale))  # (leaves the map by its back arrow)
    assert nav._set_world(parse_lobby(everdale)).world == 1
    assert nav.world is None and nav.device.taps == [MAP_BUTTON.center] and "not on the World Map" in caplog.text


def test_locked_world_leaves_the_map_open_and_is_given_up(monkeypatch, caplog):
    everdale = _lobby("81. Picos Helados XII")
    nav = _world_nav(monkeypatch, [everdale, MAP], "heliora")  # the map stays after tapping the island
    monkeypatch.setattr(nav, "go_to_lobby", lambda: parse_lobby(everdale))
    assert nav._set_world(parse_lobby(everdale)).world == 1
    assert nav.world is None and "locked" in caplog.text


def test_world_option_in_the_request():
    assert build_request("normal", "latest", "", world="heliora").world == "heliora"
    assert build_request("normal", "latest", "").world is None
    assert build_request("normal", "latest", "", world="atlantis").world is None  # an old or broken setting
    assert RunRequest(Mode.NORMAL, None).world is None


def test_runner_gives_the_world_to_the_navigator(monkeypatch):
    from roguebot import __main__ as main
    seen = {}

    class Stop(Exception):
        pass

    def nav(device, ocr, **kwargs):
        seen.update(kwargs)
        raise Stop

    monkeypatch.setattr(main, "Emulator", lambda folder, stop=None: type("E", (), {"start": lambda self: ("s", "adb", False)})())
    monkeypatch.setattr(main, "Device", lambda serial, stop=None, adb=None: object())
    monkeypatch.setattr(main, "Ocr", lambda: object())
    monkeypatch.setattr(main, "Catalog", lambda: object())
    monkeypatch.setattr(main, "Navigator", nav)
    with pytest.raises(Stop):
        main.make_runner(dry_run=True)(RunRequest(Mode.NORMAL, None, world="heliora"))
    assert seen["world"] == "heliora"


# --- forks -------------------------------------------------------------------------------------

def test_fork_cards(ocr):
    img, texts = load(ocr, "level_path_choice.png")
    assert classify_level_screen(img, texts).kind is LevelScreen.PATH_CHOICE
    a, b = parse_paths(texts)
    assert (a.label.text, a.shop, b.label.text, b.shop) == ("Camino A", False, "Camino B", True)  # statue / shop
    assert a.label.center[0] < 720 < b.label.center[0] and parse_money(texts) == 166


def test_board_without_a_fork_has_no_paths(ocr):
    _, texts = load(ocr, "level_shop_atk_boost.png")
    assert parse_paths(texts) == []
    assert parse_paths([Text("Camino A", 360, 2250, 640, 2310)]) == []  # one label alone is not a fork


def test_fork_takes_the_shop_only_with_coins_for_it():
    assert strategy.choose_path([False, True], 166) == 1
    assert strategy.choose_path([True, False], config.PATH_SHOP_COINS) == 0
    assert strategy.choose_path([False, True], config.PATH_SHOP_COINS - 1) == 0
    assert strategy.choose_path([False, True], None) == 0      # coins not read: the free path
    assert strategy.choose_path([True, True], 0) == 0 and strategy.choose_path([False, False], 500) == 0


def test_player_taps_the_chosen_fork_card(tmp_path, ocr):
    img, texts = load(ocr, "level_path_choice.png")
    p = player(tmp_path, Build("magic"))
    labels.set_language("es")
    assert p._path(img, texts) == parse_paths(texts)[1].label.center  # 166 coins: the shop
    poor = [t for t in texts if t.text != "166"] + [Text("12", 120, 145, 223, 203)]
    assert p._path(img, poor) == parse_paths(texts)[0].label.center


def test_shop_card_is_known_by_its_picture(ocr):
    """The phone's OCR does not read the small "SHOP" sign drawn on the card: the wagon is matched instead."""
    img, texts = load(ocr, "level_path_choice.png")
    unsigned = [t for t in texts if t.norm != "shop"]
    assert [p.shop for p in parse_paths(unsigned)] == [False, False]
    assert [p.shop for p in parse_paths(unsigned, img)] == [False, True]
    assert [p.shop for p in parse_paths(unsigned, np.zeros_like(img))] == [False, False]


# --- events ------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, options, taken", [
    ("level_event_statue.png", ["Rezar", "Ofrenda", "Hacer una"], "Rezar"),       # free benefit, no skill forgotten
    ("level_event_two_fight.png", ["Observar", "Robado"], "Observar"),            # not -25% max HP
    ("level_event_rest_hurt.png", ["Descansar", "Entrenar"], "Descansar"),        # HP 49%
    ("level_event_rest_full.png", ["Descansar", "Entrenar"], "Entrenar"),         # HP 100%: resting wasted the tile
])
def test_event_choice(ocr, name, options, taken):
    img, texts = load(ocr, name)
    assert classify_level_screen(img, texts).kind is LevelScreen.EVENT
    found = event_options(img, texts)
    assert [o.text for o in found] == options
    assert found[strategy.choose_event([o.norm for o in found], parse_hp(texts))].text == taken


def test_hp_share(ocr):
    assert parse_hp(load(ocr, "level_event_rest_hurt.png")[1]) == pytest.approx(0.49, abs=0.01)
    assert parse_hp(load(ocr, "level_event_rest_full.png")[1]) == 1.0
    assert parse_hp([Text("0/10,1m", 459, 52, 669, 105)]) == 0.0
    assert parse_hp([Text("12/30", 20, 1340, 140, 1390)]) is None  # the roll counter, not the HP bar
    assert parse_hp(load(ocr, "lobby_heliora_normal.png")[1]) is None


def test_event_rules():
    labels.set_language("es")
    assert strategy.choose_event(["no,gracias", "toma el taxi"], 1.0) == 0   # OCR dropped the space
    assert strategy.choose_event(["indulgencia", "rechazar"], 0.2) == 1      # coins are for the shop
    assert strategy.choose_event(["espiar", "mete el brazo"], 1.0) == 0      # not -50% max HP
    assert strategy.choose_event(["descansar", "entrenar"], None) == 0       # HP not read: rest
    assert strategy.choose_event(["entrenar", "descansar"], 0.9) == 0
    assert strategy.choose_event(["firmar", "salir"], 1.0) is None           # no rule: the old one (leave)
    assert strategy.choose_event([], 1.0) is None


def test_player_event_tap_and_fallback(tmp_path, ocr):
    img, texts = load(ocr, "level_event_rest_full.png")
    p = player(tmp_path, Build("magic"))
    labels.set_language("es")
    train = next(t for t in texts if t.text == "Entrenar")
    assert p._event(img, texts) == (train.center[0], train.center[1] + config.EVENT_ICON_BELOW_LABEL)
    img, texts = load(ocr, "level_event_cart.png")  # an old event without a rule: None -> classify's own tap
    assert p._event(img, texts) is None


# --- shop stat items ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, boost, heal", [
    ("level_shop_hp_boost.png", 38, 95),    # "PS máx. ↑↑"
    ("level_shop_atk_boost.png", 57, 95),   # "ATQ↑↑↑"
    ("level_black_market.png", 57, 48),     # everything at half price
    ("level_shop.png", 19, 95),             # OCR reads only "ATQ"
])
def test_shop_stat_items(ocr, name, boost, heal):
    _, texts = load(ocr, name)
    items = parse_shop(texts).items
    assert {k: int(t.norm) for k, t in items.items()} == {"boost": boost, "heal": heal}
    assert items["boost"].center[0] < items["heal"].center[0] and items["boost"].center[1] < 1020


def test_black_market_is_a_shop(ocr):
    """Seen live 2026-11-14: the same screen as the shop, paid with run coins (never gems), on sale."""
    img, texts = load(ocr, "level_black_market.png")
    shop = parse_shop(texts)
    assert classify_level_screen(img, texts).kind is LevelScreen.SHOP
    assert shop.money == 58 and [c.cost for c in shop.cards] == [48, 48, 48]


def _items(uses="3/3", boost=57, heal=95, sold=False):
    return [Text("AGOTADO" if sold else uses, 807, 707, 902, 765), Text("ATQ↑↑↑", 691, 850, 903, 912),
            Text("Curar 30%", 1017, 856, 1234, 909), Text(str(boost), 792, 947, 874, 1010),
            Text(str(heal), 1121, 947, 1202, 1010)]


def test_used_up_stat_item_is_not_on_sale():
    labels.set_language(None)  # the fake shop is English, the items Spanish
    assert set(parse_shop(shop_screen(100, []) + _items("0/3")).items) == {"heal"}
    assert set(parse_shop(shop_screen(100, []) + _items(sold=True)).items) == {"heal"}
    assert set(parse_shop(shop_screen(100, []) + _items("1/3")).items) == {"boost", "heal"}
    assert parse_shop(shop_screen(100, [])).items == {}


def test_shop_item_rule():
    assert strategy.shop_item({"boost": 57, "heal": 95}, 200, 1.0) == "boost"
    assert strategy.shop_item({"boost": 57, "heal": 95}, 200, 0.3) == "heal"    # hurt: heal first
    assert strategy.shop_item({"boost": 57, "heal": 95}, 60, 0.3) == "boost"    # can't pay the heal
    assert strategy.shop_item({"boost": 57, "heal": 95}, 200, None) == "boost"  # HP not read: no heal
    assert strategy.shop_item({"heal": 95}, 200, 0.9) is None and strategy.shop_item({"boost": 57}, 56, 1.0) is None


HP_FULL, HP_LOW = Text("10m/10m", 408, 54, 725, 109), Text("3m/10m", 408, 54, 725, 109)
BOOST_PRICE, HEAL_PRICE = (833, 978), (1161, 978)


def test_shop_buys_the_stat_boost_before_skills(tmp_path):
    """Three "ATQ ↑↑↑" (1.5m -> 2.0m attack, seen live), then the skill the coins still pay."""
    cards = [(*FIRE_WAVE, False)]
    frames = [shop_screen(193, cards, free=False) + _items("2/3") + [HP_FULL],
              shop_screen(136, cards, free=False) + _items("1/3") + [HP_FULL],
              shop_screen(79, cards, free=False) + _items(sold=True) + [HP_FULL],
              shop_screen(79, [(*FIRE_WAVE, True)], free=False) + _items(sold=True) + [HP_FULL]]
    p = player(tmp_path, Build("magic"), frames)
    labels.set_language(None)  # the fake shop is English, the items Spanish
    p._shop(shop_screen(250, cards, free=False) + _items("3/3") + [HP_FULL])
    assert p.device.taps == [BOOST_PRICE, BOOST_PRICE, BOOST_PRICE]  # Fire Wave costs 95: no coins left for it
    assert p._state.taken == []


def test_shop_heals_first_when_hurt(tmp_path):
    frames = [shop_screen(105, [], free=False) + _items() + [Text("6m/10m", 408, 54, 725, 109)],
              shop_screen(48, [], free=False) + _items("2/3") + [HP_FULL]]
    p = player(tmp_path, Build("magic"), frames)
    labels.set_language(None)
    p._shop(shop_screen(200, [], free=False) + _items() + [HP_LOW])
    assert p.device.taps == [HEAL_PRICE, BOOST_PRICE]


def test_shop_stops_buying_items_when_the_coins_do_not_drop(tmp_path):
    """A buy that does not register (sold out without the label, a missed tap) is not repeated forever."""
    stuck = shop_screen(200, [(*FIRE_WAVE, False)], free=False) + _items(uses="") + [HP_FULL]
    p = player(tmp_path, Build("magic"), [stuck, shop_screen(105, [(*FIRE_WAVE, True)], free=False) + _items(uses="")])
    labels.set_language(None)
    p._shop(stuck)
    assert p.device.taps == [BOOST_PRICE, price_at(0)]  # one try, then on to the skills


# --- skill pick --------------------------------------------------------------------------------

def test_floating_exp_is_not_a_skill_name(ocr):
    """After a fight "EXP" texts float over the level-up pick, between a card's tag and its name."""
    _, texts = load(ocr, "level_skill_pick_exp.png")
    assert [c.name for c in parse_skill_cards(texts)] == ["Alto Voltaje"]
    labels.set_language("en")
    cards = [PROMPT, *card("Common", "Fire Weapon", "Attacks deal additional fire damage.", 928),
             Text("EXP", 520, 930, 600, 960)]
    assert [c.name for c in parse_skill_cards(cards)] == ["Fire Weapon"]


def test_skill_pick_waits_for_every_card(tmp_path):
    """The cards fly in one by one: a frame with one card once wasted the reroll (seen live 2026-11-14)."""
    p = player(tmp_path, Build("magic"))
    one = [PROMPT, *card("Common", "Iron Shield", "Gain a Shield.", 928)]
    three = one + card("Common", "Fire Weapon", "Attacks deal fire damage.", 1236) + card("Common", "Ice Weapon", "Ice.", 1544)
    assert [p._offer_settled(f) for f in (one, three, three)] == [False, False, True]
    assert p._offer_settled([PROMPT]) is True  # no card read: the old fallback (first tag) right away
    assert [p._offer_settled(f) for f in (three, three)] == [False, True]  # the next pick starts over
    flicker = [one, three] * 3  # never the same twice: decide anyway after SKILL_PICK_SETTLE_FRAMES
    assert [p._offer_settled(f) for f in flicker][config.SKILL_PICK_SETTLE_FRAMES] is True


# --- treasure miner ----------------------------------------------------------------------------

def test_treasure_miner_screens(ocr):
    img, texts = load(ocr, "level_treasure_miner.png")
    assert classify_level_screen(img, texts) .kind is LevelScreen.MINER and treasures_left(texts) == 5
    assert miner_tiles(img) == [DIRT] * 49

    img, texts = load(ocr, "level_treasure_miner_found.png")  # 5 digs: 4 empty, 1 piece of a treasure
    tiles = miner_tiles(img)
    assert [i for i, t in enumerate(tiles) if t == EMPTY] == [8, 12, 24, 40]
    assert [i for i, t in enumerate(tiles) if t == TREASURE] == [36] and treasures_left(texts) == 5
    assert strategy.miner_dig(tiles, set()) in (35, 37)  # next to the piece (the bar lies on 35-37)

    img, texts = load(ocr, "level_treasure_miner_done.png")  # the 3-tile bar dug out: it paid a Legendary skill
    tiles = miner_tiles(img)
    assert [i for i, t in enumerate(tiles) if t == TREASURE] == [35, 36, 37] and treasures_left(texts) == 4
    assert strategy.miner_dig(tiles, {35, 36, 37}) not in (28, 29, 30, 34, 38, 42, 43, 44)  # not around it

    img, texts = load(ocr, "level_treasure_miner_end.png")  # out of pickaxes: "Salir"
    assert classify_level_screen(img, texts).kind is LevelScreen.LEAVE


def _grid(**tiles):
    grid = [DIRT] * 49
    for kind, indices in tiles.items():
        for i in indices:
            grid[i] = kind
    return grid


def test_miner_search_and_follow():
    assert strategy.miner_dig(_grid(), set()) == 24                      # the center first
    order = []
    grid = _grid()
    for _ in range(9):
        order.append(strategy.miner_dig(grid, set()))
        grid[order[-1]] = EMPTY
    assert all(sum(divmod(i, 7)) % 3 == 0 for i in order)                # diagonals 3 apart
    assert strategy.miner_dig(_grid(treasure=[10]), set()) == 11         # a piece: the tile next to it
    assert strategy.miner_dig(_grid(treasure=[10], empty=[11]), set()) == 9
    assert strategy.miner_dig(_grid(treasure=[10, 17]), set()) in (3, 24)  # two in a column: along the column
    assert strategy.miner_dig(_grid(treasure=[10, 17], empty=[3, 9, 11, 16, 18]), set()) == 24
    assert strategy.miner_dig(_grid(treasure=[0]), {0}) == 24            # dug out whole: search again
    assert strategy.miner_dig([EMPTY] * 49, set()) is None


def test_player_stops_following_a_treasure_once_it_is_dug_out(tmp_path):
    p = player(tmp_path, Build("magic"))
    labels.set_language("es")

    def frame(tiles, left):
        img = np.zeros((2560, 1440, 3), np.uint8)
        for i, kind in enumerate(tiles):
            x, y = miner_tile(*divmod(i, 7))
            img[y - 60:y + 60, x - 60:x + 60] = {DIRT: config.MINER_DIRT, EMPTY: (8, 16, 24), TREASURE: (26, 148, 249)}[kind]
        return img, [Text(f"Tesoros Restantes: {left}", 468, 2087, 972, 2139)]

    assert p._miner(*frame(_grid(), 5)) == miner_tile(3, 3)
    assert p._miner(*frame(_grid(empty=[24], treasure=[36]), 5)) == miner_tile(5, 2)   # follow the piece
    assert p._miner(*frame(_grid(empty=[24], treasure=[36, 37]), 5)) in (miner_tile(5, 0), miner_tile(5, 3))
    done = _grid(empty=[24], treasure=[35, 36, 37])
    assert p._miner(*frame(done, 4)) == miner_tile(0, 0) or p._miner_done == {35, 36, 37}  # the count dropped
    assert p._miner_done == {35, 36, 37}
    assert p._miner(*frame(done, 4)) not in [miner_tile(*divmod(i, 7)) for i in (28, 29, 30, 34, 38, 42, 43, 44)]


# --- level end ---------------------------------------------------------------------------------

def test_spanish_x2_rewards_button(ocr):
    """"Recompensas x2" next to Continuar (seen 2026-11-14): doubled by the ad before continuing."""
    img, texts = load(ocr, "level_defeat_double_reward.png")
    state = classify_level_screen(img, texts)
    assert state.kind is LevelScreen.DOUBLE_REWARD and state.tap[0] > 720 and state.tap[1] > 2100


# --- cursed vendor -----------------------------------------------------------------------------

def test_cursed_vendor_contracts(ocr, tmp_path):
    """"Vendedor Maldito" (seen 2026-11-14): one of two contracts must be signed; the bot was stuck on it."""
    img, texts = load(ocr, "level_cursed_vendor.png")
    assert classify_level_screen(img, texts).kind is LevelScreen.CONTRACT
    left, right = parse_contracts(texts)
    assert "se renuevan" in left.terms and "actuan primero" in left.terms       # rerolls back / enemies act first
    assert "posada" in right.terms and "se duplican" in right.terms             # campfires become inns / shop prices double
    assert left.button.center[0] < 720 < right.button.center[0] and left.button.center[1] > 2300
    p = player(tmp_path, Build("magic"))
    labels.set_language("es")
    assert p._contract(texts) == right.button.center  # +3 -2 beats +1 -1


def test_contract_rule():
    labels.set_language("es")
    inn, rerolls = "cada fogata se convierte en una posada. los precios de la tienda se duplican.", "se renuevan. actuan primero"
    assert strategy.choose_contract([rerolls, inn]) == 1 and strategy.choose_contract([inn, rerolls]) == 0
    assert strategy.choose_contract(["algo nuevo", "otra cosa"]) == 0            # unknown terms: the first
    assert strategy.choose_contract(["los precios de la tienda se duplican.", "algo nuevo"]) == 1
    assert parse_contracts([Text("Firmar", 420, 1765, 600, 1824), Text("Salir", 850, 1765, 1000, 1824)]) == []  # the devil's deal event
    tiles = "todas las casillas de debuff se convierten en casillas de buff. se eliminan todas las fogatas."
    half = "quita la mitad de las casillas enemigas del tablero. la mitad de tus habilidades quedan desactivadas."
    assert strategy.choose_contract([half, tiles]) == 1  # seen live 2026-11-14: 0 beats -2


def test_trained_skill_result_is_left_by_its_next_button(ocr):
    """"¡SUBIDA DE PODER!" + one upgraded skill + a green NEXT where the dice is: the bot took it for
    auto-play and waited there for hours (seen 2026-11-14)."""
    img, texts = load(ocr, "level_skill_upgraded_next.png")
    state = classify_level_screen(img, texts)
    assert state.kind is LevelScreen.CONTINUE and abs(state.tap[0] - 720) < 20 and abs(state.tap[1] - 2155) < 20


def test_auto_play_that_never_ends_stops_the_level(monkeypatch, tmp_path):
    """A screen that only looks like auto-play (green button) must not be waited on forever."""
    from roguebot import play
    from test_logic import _play
    monkeypatch.setattr(play, "DEBUG_DIR", tmp_path)
    with pytest.raises(play.PlayError, match="Waiting on auto_play for too long"):
        _play(monkeypatch, [(LevelScreen.AUTO_PLAY, None)] * (config.WAIT_SCREEN_FRAMES + 5))
    fights = [(LevelScreen.AUTO_PLAY, None), (LevelScreen.FIGHT, None)] * 100 + [(LevelScreen.FIGHT, None)] * 300
    _play(monkeypatch, fights + [(LevelScreen.VICTORY, (720, 2220))])  # fights and auto-play in turns, a long fight: fine


def test_patrol_button_when_ocr_joins_it_with_the_stars_button(ocr):
    """Seen live 2026-11-14: "Patrulla de Estrellas" read as one text; its middle opened the star list."""
    from roguebot.mode_screens import patrol_button
    _, texts = load(ocr, "lobby_heliora_normal.png")
    joined = patrol_button(texts)
    assert joined.text == "Patrulla de Estrellas" and abs(joined.center[0] - 825) < 30   # on the patrol bag
    assert abs(parse_lobby(texts).stars_button.center[0] - 1000) < 30                    # the star on its right
    _, texts = load(ocr, "lobby_heliora_elite.png")                                      # read apart: unchanged
    assert patrol_button(texts).text == "Patrulla" and abs(patrol_button(texts).center[0] - 812) < 20
    assert patrol_button([]) is None


def test_blacksmith_anvil(ocr, tmp_path):
    """"Yunque del Herrero" (seen 2026-11-14): take the item or gamble on upgrading it; the bot was stuck on it."""
    labels.set_language("es")
    p = player(tmp_path, Build("magic"))
    img, texts = load(ocr, "level_anvil.png")                 # ATQ Pequeño, 70%
    assert classify_level_screen(img, texts).kind is LevelScreen.ANVIL
    take, upgrade, chance = parse_anvil(texts)
    assert chance == 70 and take.center[0] < 720 < upgrade.center[0] and take.center[1] > 2200
    assert p._anvil(texts) == upgrade.center
    img, texts = load(ocr, "level_anvil_legendary.png")       # after two upgrades: a legendary skill, 10%
    take, upgrade, chance = parse_anvil(texts)
    assert chance == 10 and p._anvil(texts) == take.center
    img, texts = load(ocr, "level_anvil_received.png")        # the reward banner over the anvil: claim it
    state = classify_level_screen(img, texts)
    assert state.kind is LevelScreen.CONTINUE and state.tap[1] > 2300


def test_anvil_rule():
    assert strategy.anvil_upgrade(70) and strategy.anvil_upgrade(40)
    assert not strategy.anvil_upgrade(10) and not strategy.anvil_upgrade(None)  # unreadable chance: take
    assert LevelScreen.ANVIL in navigation.ON_BOARD and LevelScreen.ANVIL in navigation.IN_LEVEL
    assert parse_anvil([Text("Recibes", 353, 2219, 659, 2312), Text("Reforzar", 765, 2219, 1100, 2312)]) is None  # no anvil title
