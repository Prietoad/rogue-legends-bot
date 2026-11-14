"""Level strategy: which fork path, which event option, which shop stat items. Pure: no device, no OCR.

From Heliora (the second world), where the two scheduled elite enemies and the boss kill a hero that
only rolls the dice. What is known to help, cheapest first:
- Shop stat boosts ("ATQ ↑↑↑" 57 coins, "PS máx. ↑↑" 38; 3 per visit): three ATQ buys took the attack from
  1.5m to 2.0m for the rest of the run, more than any common skill does. Bought before the skills.
- Forks: the path to the shop while the coins pay for at least PATH_SHOP_COINS of it; else the other
  path (statue of the gods: a free benefit).
- "Un Momento de Descanso": train (a skill upgrade for the whole run) unless the HP is low; resting at
  full HP wasted the tile.
- Cursed vendor: the contract whose known terms add up best (labels.CONTRACT_TERMS): campfires turned
  into inns (full heal + 2 upgrades, ~6 per run) outweigh doubled shop prices.
- Free options over paid or risky ones (see labels.EVENT_PREFER): coins are for the shop, and max HP is
  what the elites take.
"""

import re

from roguebot import config, labels as L


def _letters(s: str) -> str:
    return re.sub(r"[^a-z]", "", s)  # OCR drops or adds spaces and commas ("No,Gracias")


def _is(norm: str, label: L.Label) -> bool:
    return _letters(norm) in {_letters(v) for v in label.variants}


def choose_path(shops: list[bool], coins: int | None) -> int:
    """Index of the fork path to take; shops[i] = path i leads to a shop."""
    if True in shops and coins is not None and coins >= config.PATH_SHOP_COINS:
        return shops.index(True)
    return shops.index(False) if False in shops else 0


def choose_event(options: list[str], hp: float | None) -> int | None:
    """Index of the event option to take (options = their normalized labels, left to right), or None when
    no rule knows the event (the caller then leaves it, or takes the leftmost option)."""
    rest = next((i for i, o in enumerate(options) if _is(o, L.EVENT_REST)), None)
    train = next((i for i, o in enumerate(options) if _is(o, L.EVENT_TRAIN)), None)
    if rest is not None and train is not None:
        return rest if hp is None or hp < config.REST_BELOW_HP else train
    for label in L.EVENT_PREFER:
        for i, option in enumerate(options):
            if _is(option, label):
                return i
    return None


def choose_contract(terms: list[str]) -> int:
    """Cursed vendor: index of the contract to sign (terms = each contract's normalized text). The best
    sum of the known terms; unknown terms count 0, ties go to the first."""
    scores = [sum(weight for label, weight in L.CONTRACT_TERMS if any(v in text for v in label.variants))
              for text in terms]
    return scores.index(max(scores))


def shop_item(prices: dict[str, int], coins: int, hp: float | None) -> str | None:
    """The stat item to buy next (screens.BOOST / HEAL), or None. prices = the items still on sale."""
    if "heal" in prices and hp is not None and hp < config.SHOP_HEAL_BELOW_HP and prices["heal"] <= coins:
        return "heal"
    if "boost" in prices and prices["boost"] <= coins:
        return "boost"
    return None


def miner_dig(tiles: list[str], done: set[int]) -> int | None:
    """"Minero de Tesoros": index of the tile to dig, or None (no dirt left). tiles = screens.miner_tiles;
    done = treasure tiles already dug out whole. A treasure spans several tiles in a line and only pays
    (a skill) once all of it is dug out, so a found piece is followed first: the dirt next to it, in line
    with two pieces when there are two. Otherwise search on diagonals 3 apart (every 3-tile treasure
    crosses one), from the center out."""
    n = config.MINER_SIZE
    best, best_score = None, 0
    for i, tile in enumerate(tiles):
        if tile != "treasure" or i in done:
            continue
        r, c = divmod(i, n)
        for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            rr, cc = r + dr, c + dc
            if not (0 <= rr < n and 0 <= cc < n) or tiles[rr * n + cc] != "dirt":
                continue
            br, bc = r - dr, c - dc  # the tile behind: another piece there means this is the treasure's line
            in_line = 0 <= br < n and 0 <= bc < n and tiles[br * n + bc] == "treasure" and br * n + bc not in done
            score = 2 if in_line else 1
            if score > best_score:
                best, best_score = rr * n + cc, score
    if best is not None:
        return best
    dirt = [i for i, tile in enumerate(tiles) if tile == "dirt"]
    center = (n - 1) / 2
    return min(dirt, key=lambda i: (sum(divmod(i, n)) % 3 != 0, abs(i // n - center) + abs(i % n - center), i),
               default=None)
