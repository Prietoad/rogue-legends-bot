"""Every game text the bot matches, per language.

Values are normalized (lowercase, no accents; see vision.normalize). A label matches if any of
its variants for the active language matches. The language is detected once per run from the
lobby (`detect_language`) and set with `set_language`; before that, both languages are tried.

Only texts actually seen on screen are listed. When a screen shows up in a language that has no
variant yet, the bot stops with a screenshot: add the variant here, plus a fixture test.
"""

from dataclasses import dataclass

from roguebot.vision import normalize

LANGUAGES = ("es", "en")
_active: str | None = None  # None = not detected yet: match every language


@dataclass(frozen=True)
class Label:
    es: tuple[str, ...] = ()
    en: tuple[str, ...] = ()

    @property
    def variants(self) -> tuple[str, ...]:
        if _active is None:
            return self.es + self.en
        return getattr(self, _active)


def _l(es: str | tuple[str, ...] = (), en: str | tuple[str, ...] = ()) -> Label:
    def norm(v):
        return tuple(normalize(x) for x in ((v,) if isinstance(v, str) else v))
    return Label(norm(es), norm(en))


def set_language(lang: str | None) -> None:
    global _active
    assert lang is None or lang in LANGUAGES
    _active = lang


def active_language() -> str | None:
    return _active


# Lobby (Aventura / Adventure tab)
PATROL = _l("patrulla", "patrol")                    # also used to detect the language
STARS_BUTTON = _l("de estrellas", "challenge")       # "Desafío de Estrellas" / "Star Challenge"
ELITE_ON = _l("activado", "on")                      # exact
ELITE_OFF = _l("apagado", "off")                     # exact
START_NORMAL = _l("inicio", "start")                 # exact; also the elite dialog's start button
START_ELITE = _l("listo", "ready")                   # exact
LOADING = _l("cargando")
POPUP_CLOSE = _l("para cerrar", "to close")          # "Toca (en cualquier lugar) para cerrar" / "Tap anywhere to close"
WORLD_MAP_BUTTON = _l("mundial", ("world map", "world"))  # lobby "Mapa / Mundial" compass, left of the chapter chest; en guessed
WORLD_MAP_TITLE = _l("mapa mundial", "world map")    # the map screen: one island per world (name + progress %); en guessed
LOBBY_TAB = _l("aventura", "adventure")              # exact; footer tab label, dimmed under lobby popups
MODES_BUTTON = _l("modos", "modes")                  # exact; lobby bottom-right (OCR often garbles it)

# Star challenge list
STAR_LIST_TITLE = _l("desafio de", "star challenge")
LIST_REWARDS = _l("recompensas", "rewards")

# Elite start dialog
ELITE_DIALOG_TITLE = _l("modo elite", "elite mode")

# Energy popup ("Purchase")
ENERGY_POPUP_TITLE = _l("comprar", "purchase")
ENERGY_CHANCES = _l("intentos restantes", "chances left")               # above the video button (and the gem one); OCR may misread "Today"
ENERGY_FREE = _l("gratis", "free")                          # exact; Daily Pack button
DAILY_PACK_CLAIMED = _l("se actualiza en", "refresh in")             # timer once the Daily Pack was taken (button still says "Free")

# Level end
CONTINUE = _l("continuar", "continue")               # exact
CONFIRM = _l("confirmar", "confirm")                 # exact; Dungeon Dive end screen button (English guessed)
DEFEAT = _l("derrota", "defeat")                     # English inferred from "VICTORY!", not seen yet
VICTORY = _l("victoria", "victory")
DOUBLE_REWARD = _l(("recompensas x2", "recompensasx2"), "x2 rewards")  # ad button, bottom-right of the end screen (some runs)

# In level
SKILL_PROMPT = _l("selecciona una habilidad", "select a skill")
EXACT_BUTTONS = _l(                                  # buttons that just advance the game, matched exactly
    ("girar", "girar!", "reclamar", "next"),         # wheels (exact: their bubble says "One spin! ...")
    ("spin", "spin!", "claim", "next"),              # + dice duel won: CLAIM (not "Challenge Again"); "NEXT" (not translated): a trained skill's result
)
CONTINUE_BUTTONS = (                                 # buttons that just advance the game (substring)
    _l("toca en cualquier lugar", "tap anywhere"),   # reward popups: "...para reclamar", "...to open!"
    _l("toca para continuar", "tap to continue"),    # event outcome
)
DUEL_ROLL = _l("tirar", "roll")                      # exact
DUEL_STAND = _l("resistir", "stand")                 # exact
DUEL_SCORE_PREFIX = _l("yo", "me")                   # "Yo 12 / 21"
FLIP_CARDS_PROMPT = _l("voltea 3 de las mismas", "flip 3 identical cards")
SHOP_REROLL = _l("nueva tirada", "reroll")
SKILL_REROLL = _l("volver a tirar", "reroll")        # skill pick, with "(1)" uses left below it
PATROL_TIME = _l("tiempo de patrulla", "patrol time")   # patrol popup: "Tiempo de patrulla: 28:13"
PATROL_CLAIM = _l("reclamar", "claim")                 # exact; patrol popup green button
QUICK_PATROL = _l("patrulla rapid", ("quick patro", "quickpatro"))  # patrol popup yellow button (OCR cuts the end)
QUICK_PATROL_TEXT = _l("reclama de inmediato", "immediately claim")  # quick patrol popup: "...las recompensas de 2 h"
REMAINING = _l("cantidad restante", "remaining")       # quick patrol: "Cantidad restante: 0" under each option
FREE = _l("gratis", "free")                          # exact; shop reroll price when free
SOLD_OUT = _l(("agotado", "vendido"), ("sold out", "soldout"))  # bought shop card (Spanish guessed)
LEAVE = _l("salir", ("exit", "leave", "walk away"))  # exact
FORTUNE_TELLER = _l("adivino", "fortune teller")             # balls that may give a skill, paid with run orbs
FIGHT_ROUND = _l("ronda", "round")                   # "Ronda 3/30" / "Round 4/30"
REVIVE_PROMPT = _l("revivir ahora", "revive")        # "¡Revivir ahora!" on death, 10 s countdown (English guessed)
REVIVE_FREE = _l("gratis", "free")                   # exact; yellow video button (the green one costs 60 gems)
PATH_OPTION = _l("camino", "path")                   # board fork cards "Camino A" / "Camino B" (Heliora); en guessed
PATH_SHOP = _l(("shop", "market"), ("shop", "market"))  # exact; the sign drawn on a fork card when the path leads to a shop ("SHOP", "BLACK / MARKET")
EVENT_REST = _l("descansar", "rest")                 # "Un Momento de Descanso": restores 48% HP; en guessed
EVENT_TRAIN = _l("entrenar", "train")                # ...or upgrades 1 skill; en guessed
EVENT_PREFER = (                                     # event options taken when offered, first match wins (en guessed)
    _l("no, gracias", "no, thanks"),                 # magic taxi: a free +15% heal (the taxi costs 75 coins)
    _l("rechazar", ("decline", "refuse")),           # slime chef: 75 coins for a random reward; the shop uses them better
    _l("rezar", "pray"),                             # statue of the gods: a free benefit (the offering forgets a skill)
    _l("espiar", "peek"),                            # dark fissure: a free common skill (the mythic one costs 50% max HP)
    _l("observar", "observe"),                       # two monsters fight: a free common skill (the legendary one costs 25% max HP)
)
SHOP_HEAL = _l("curar", "heal")                      # shop stat item "Curar 30%" (starts with); en guessed
CURSED_VENDOR = _l("vendedor maldito", ("cursed vendor", "cursed merchant"))  # two contracts (a boon + a curse each): one must be signed; en guessed
SIGN = _l("firmar", "sign")                          # exact; a contract's button (also the devil's deal event option)
CONTRACT_TERMS = (                                   # what a contract's text is worth (see strategy.choose_contract); en guessed
    (_l("posada", "inn"), 3),                        # every campfire becomes an inn: full heal + 2 skill upgrades (a run has ~6 campfires)
    (_l("se renuevan", "refresh"), 1),               # the skill pick reroll comes back at every pick
    (_l("actuan primero", "act first"), -1),         # enemies always act first
    (_l("se duplican", "double"), -2),               # shop prices double
    (_l("casillas de buff", "buff tiles"), 2),       # every debuff tile becomes a buff tile for the rest of the run
    (_l("se eliminan todas las fogatas", "campfires are removed"), -2),
    (_l("casillas enemigas", "enemy tiles"), 1),     # half the enemy tiles removed, for EXP and shop coins
    (_l("quedan desactivadas", "are disabled"), -3),  # half the skills disabled for the next 5 fights (the elites)
)
TREASURE_MINER = _l("minero de tesoros", "treasure miner")  # minigame: dig a 7x7 grid for treasures (skills); en guessed
TREASURES_LEFT = _l("tesoros restantes", "treasures left")  # "Tesoros Restantes: 5"; en guessed
LEVEL_MODIFIERS = _l("modificadores de nivel", "level modifiers")  # elite level intro panel (+ Continue)

# Full routine. Spanish variants marked (?) are the user's names or guesses, not seen on screen yet.
GUILD_BUTTON = _l("gremio", ("guild", "guiid"))      # exact; lobby, bottom-left; absent when not in a guild
ARENA = _l("arena", "arena")                         # exact; modes list card title / arena screen title
ARENA_CLOSED = _l("abre en", "opens in")             # (? en) under the Arena card around the daily reset: "Abre en 4m"
TOWER = _l("desafio de torre", "tower challenge")
MINES = _l("minas de cristal", ("crystal mines", "crystalmines"))
PETS = _l(("reino de las mascotas", "reino de mascotas"), ("pet kingdom", "petkingdom"))
CHALLENGE = _l(("desafiar", "desafio"), "challenge")  # exact (arena/tower/mines/raid button; tower: "Desafío")
ARENA_PANEL = _l("desafio de la arena", "arena challenge")  # opponent list title
FREE_REFRESH = _l("recarga gratis", "free refresh")  # opponent list refresh, only when free
TOWER_TITLE = _l("torre de los heroes", "tower of heroes")
TOWER_NEXT_FLOOR = _l("proximo piso", "next floor")  # tower victory: starts the next floor (one more ticket); en guessed
TOWER_CLEARED = _l(("felicidades", "enhorabuena"), "congratulations on clearing")  # whole tower done: chest (es guessed)
DIFFICULTY = _l("dificultad", "difficulty")          # mines / pet popup
SWEEP = _l("barrer", "sweep previous")               # "Barrer etapa anterior" / "Sweep previous stage"
AD_TICKETS = _l("boletos de mazmorra", "dungeon tickets")  # watch-ad button, shown at 0 tickets (?)
DOJO = _l("batalla de dojo", "dojo battle")          # modes list card / dojo screen title; en (?)
DIVE = _l("descenso a", "dungeon dive")              # modes list card "Descenso a la Mazmorra" (OCR: "ala"); en (?)
DIVE_REWARDS = _l("recompensas", "rewards")          # exact; dungeon dive screen, above the rewards
DOJO_CHEST = _l("reclamar", "claim")                 # exact; dojo progress chest ("Intenta el Dojo N veces")
MENU_DAILY = _l(("diarias", "recompensas diarias"), ("daily", "daily rewards"))  # exact; top-left menu, wraps "Recompensas / Diarias"; en (?)
MENU_MAIL = _l("correo", "mail")                     # exact; top-left menu; en (?)
DAILY_TITLE = _l("recompensas diarias", "daily rewards")  # daily rewards popup; en (?)
DAILY_CLAIM = _l("reclamar", "claim")                # exact; daily rewards popup: opens the game's web store
DAILY_WEB_CLAIM = _l("reclamar ahora", "claim now")  # web store page (browser) "Reclamar ahora!"; en (?)
MAIL_TITLE = _l("correo", "mail")                    # exact; mail popup title; en (?)
VIP_CARDS = _l(("tarjetas vip", "tarjetas", "vip"), ("vip cards", "cards", "vip"))  # exact; lobby left column icon; OCR splits it ("Tarjetas / VIP", "VIP / Cards") and garbles "VIP" in English ("VIPS", "LVIP")
CLAIM_ALL = _l("reclamar todo", "claim all")         # exact; VIP cards screen bottom (grey once claimed today), mail; en (?)
GUILD_HALL = _l("sala de", ("guildhall", "guild hall"))  # guild map castle; Spanish wraps "Sala de / Gremio"
GUILD_HALL_LOWER = _l("gremio", "guild hall")       # exact; its second line (the flag over "Sala de" garbles it: "Sa Slde")
DONATE = _l("donar", "donate")                       # exact; guild hall bottom button; en (?)
DONATION_TITLE = _l("donacion de gremio", "guild donation")  # donation popup; en (?)
RAID_BOSS = _l("incursion", "raid boss")            # guild map; Spanish wraps "Jefe de / Incursión"
RAID_TITLE = _l("asalto de gremio", "guild raid")
RAID_ATTEMPTS = _l("intentos diarios", "daily attempts left")  # "Daily Attempts Left: 1" (?)
LEARN_SKILLS = _l("aprender habilidades", "learn skills")  # raid skill pick: "Learn Skills (0/2)"; not just "aprender" (the prompt has it)
UPDATE_REQUIRED = _l("nueva actualizacion", "new update")  # game start: "Nueva Actualización" + ACTUALIZAR (Google Play); en (?)
RESUME_ADVENTURE = _l(("continuar la aventura", "aventura en curso"), ("continue adventure", "ongoing adventure"))  # buttons: Abandonar / Confirmar
OK = _l(("ok", "aceptar", "confirmar"), ("ok", "confirm"))  # exact; fight results (tower victory: "Confirmar")
TAP_TO_CONTINUE = CONTINUE_BUTTONS[1]                  # tower / mines / pets result
TAP_TO_CLAIM = CONTINUE_BUTTONS[0]                     # reward popups ("Tap anywhere to claim")
RARITIES = (                                         # best first; exact match on the card's tag
    _l(("mitico", "mitica"), "mythic"),              # (?)
    _l(("legendario", "legendaria"), "legendary"),
    _l(("epico", "epica"), "epic"),                  # (?)
    _l(("raro", "rara"), "rare"),                    # (?)
    _l("comun", "common"),
)


def detect_language(texts) -> str | None:
    """Language of a lobby screen, from its "Patrulla"/"Patrol" button."""
    norms = [normalize(t.text) for t in texts]
    for lang in LANGUAGES:
        if any(v in n for v in getattr(PATROL, lang) for n in norms):
            return lang
    return None
