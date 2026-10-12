"""Skill database, tag inference and the build's choice rules (no device)."""

import json

import pytest

from roguebot.build import Build, BuildState, choose, shop_order
from roguebot.skills import Catalog, Skill, infer_tags, skill_key


@pytest.mark.parametrize("name, description, tags", [
    ("Fire Weapon", "Your Weapon Attacks deal additional fire damage and have a chance to cast Fireball.",
     ("fire", "magic", "damage")),
    ("Carámbano de Contraataque", "Cada vez que haces un Contraataque, lanza Carámbano.", ("ice", "magic", "damage")),
    ("Descarga Definitiva", "Lanza 2 Descargas después de usar tu Definitiva.", ("lightning", "magic", "damage")),
    ("Shuriken-Curativo", "Cada 2 rondas, lanza 1 Shuriken. Todos los Shurikens tienen probabilidad de curarte.",
     ("shuriken", "physical", "damage")),
    ("Sneaky Poison", "When you dodge, apply Poison to a random enemy 2 times.", ("venom", "physical", "damage")),
    ("Golpe Venenoso", "Los Ataques del arma aplicarán 1 acumulación de Veneno.", ("venom", "physical", "damage")),
    ("Glass Cannon", "ATK ↑↑↑↑, Max HP ↓↓↓", (None, "physical", "damage")),
    ("Executioner", "When the enemy has less than 50% HP, immediately execute them.", (None, "physical", "damage")),
    ("Escudo enfurecido", "La primera vez que tu HP <40%, obtienes un Escudo igual al 25% de HP.",
     (None, "physical", "support")),
    ("Recovery", "Chance to restore 5% HP every turn.", (None, "physical", "support")),
    ("Lifesteal", "Weapon Attacks have a chance to Lifesteal", (None, "physical", "support")),  # name wins
    ("Evasión-Enfurecida", "Cuando el HP <40%, Tasa de evasión", (None, "physical", "support")),
    ("Twice the Price", "Cast twice.", (None, "physical", "damage")),
    ("Wizard", "Magical DMG ↑, Physical DMG ↓↓", (None, "magic", "damage")),
    ("Lanzamiento Doble", "Después de usar tu Definitiva, encadena otra Definitiva.", (None, "physical", "damage")),
    ("Defensa Creciente", "Cada ronda, DEF ↑", (None, "physical", "support")),  # DEF as a whole word
    ("Macizo", "HP Máx. ↑↑↑↑, ATQ ↓↓↓", (None, "physical", "support")),  # first-listed stat is the boosted one
    ("Fuerza-Enfurecida", "Cuando el HP <40%, ATQ y DEF", (None, "physical", "damage")),
    ("Warrior", "Physical DMG ↑, Magical DMG ↓", (None, "physical", "damage")),
    ("Mago", "Daño Mágico ↑, Daño Físico ↓↓", (None, "magic", "damage")),
    ("Wound Strike", "Weapon Attacks will apply 1 stack of Wound.", ("bleed", "physical", "damage")),  # Wound = bleed  # "ice" inside words is not ice
])
def test_infer_tags(name, description, tags):
    assert infer_tags(name, description) == tags


def test_skill_key_ignores_ocr_spacing():
    assert skill_key("Ultimate-Bolt") == skill_key("Ultimate Bolt") == skill_key("UltimateBolt") == "ultimatebolt"
    assert skill_key("Carámbano") == "carambano"


def test_catalog_adds_new_skills_and_saves(tmp_path):
    path = tmp_path / "skills.json"
    catalog = Catalog(path)
    skill = catalog.lookup("Fire Wave", "Every turn cast Fire Wave.", "common", "en")
    assert (skill.damage_type, skill.nature, skill.role, skill.auto) == ("fire", "magic", "damage", True)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["firewave"]["rarity"] == "common"
    assert Catalog(path).skills["firewave"].name == "Fire Wave"  # reloads


def test_catalog_keeps_user_edits_and_tolerates_ocr_typos(tmp_path):
    path = tmp_path / "skills.json"
    path.write_text(json.dumps({"lifesteal": {
        "name": "Lifesteal", "lang": "en", "rarity": "common", "damage_type": "bleed", "nature": "physical",
        "role": "damage", "description": "", "auto": False}}), encoding="utf-8")
    catalog = Catalog(path)
    assert catalog.lookup("Lifesteal", "whatever", "common", "en").damage_type == "bleed"  # user's tag
    assert catalog.lookup("Lifesteai", "", "common", "en").name == "Lifesteal"  # OCR typo -> same skill
    assert len(catalog.skills) == 1


def sk(name, damage_type=None, role="damage", rarity="common"):
    nature = "magic" if damage_type in ("ice", "lightning", "fire") else "physical"
    return Skill(name, "en", rarity, damage_type, nature, role)


FIRE, ICE, VENOM = sk("fire", "fire"), sk("ice", "ice"), sk("venom", "venom")
SHIELD = sk("shield", role="support")
ATK = sk("atk")  # untyped physical damage


def test_magic_build_follows_the_type_order():
    build = Build("magic", ("ice", "fire", "lightning", "shuriken", "venom", "bleed"))
    assert choose([FIRE, VENOM, ICE], build, BuildState(), can_reroll=True) == 2


def test_physical_build_prefers_listed_types_over_untyped_damage():
    build = Build("physical", ("venom", "bleed", "shuriken", "ice", "fire", "lightning"))
    assert choose([ATK, FIRE, VENOM], build, BuildState(), can_reroll=False) == 2
    assert choose([ATK, FIRE, SHIELD], build, BuildState(), can_reroll=False) == 0


def test_type_beats_rarity_and_rarity_breaks_ties():
    build = Build("magic", ("fire", "ice", "lightning", "shuriken", "venom", "bleed"))
    legendary_ice = sk("big ice", "ice", rarity="legendary")
    assert choose([legendary_ice, FIRE], build, BuildState(), can_reroll=False) == 1
    legendary_fire = sk("big fire", "fire", rarity="legendary")
    assert choose([FIRE, legendary_fire], build, BuildState(), can_reroll=False) == 1


def test_nothing_wanted_rerolls_then_takes_the_rarest_then_the_first():
    build = Build("magic")
    offer = [VENOM, sk("rare venom", "venom", rarity="legendary"), SHIELD]
    assert choose(offer, build, BuildState(), can_reroll=True) is None
    assert choose(offer, build, BuildState(), can_reroll=False) == 1
    assert choose([VENOM, ATK], build, BuildState(), can_reroll=False) == 0


def test_support_after_n_damage_skills():
    build = Build("magic", support_every=2)
    state = BuildState()
    assert choose([SHIELD, FIRE], build, state, can_reroll=False) == 1  # 0 damage taken: damage
    state.take(FIRE)
    assert choose([SHIELD, FIRE], build, state, can_reroll=False) == 1  # 1 damage taken
    state.take(FIRE)
    assert choose([FIRE, SHIELD], build, state, can_reroll=False) == 1  # 2 damage taken: support
    assert choose([FIRE, ICE], build, state, can_reroll=True) == 1  # no support: the best damage (ice)...
    state.take(FIRE)
    assert state.wants_support(build)  # ...and keep wanting support
    state.take(SHIELD)
    assert not state.wants_support(build) and state.damage_since_support == 0


def test_without_support_option_support_is_never_wanted():
    state = BuildState(damage_since_support=10)
    assert choose([SHIELD, FIRE], Build("magic"), state, can_reroll=False) == 1


def test_shop_order_rerolls_when_free_and_nothing_fits():
    build = Build("magic")
    assert shop_order([VENOM, SHIELD], build, BuildState(), can_reroll=True) is None
    assert shop_order([VENOM, SHIELD, FIRE], build, BuildState(), can_reroll=True)[0] == 2
    # Not free: wanted first, then the rest (rarest first) so leftover coins still buy something.
    assert shop_order([VENOM, sk("l", "venom", rarity="legendary"), FIRE], build, BuildState(), False) == [2, 1, 0]
