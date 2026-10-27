package com.diego.roguebot_phone.bot

/**
 * Port of roguebot/labels.py: every game text the bot matches, per language. Values are normalized.
 * A label matches if any of its variants for the active language matches. The language is detected
 * once per run from the lobby; before that, both languages are tried. Keep in sync with labels.py.
 */
class Label(es: List<String>, en: List<String>) {
    val es = es.map(::normalize)
    val en = en.map(::normalize)
    val variants: List<String>
        get() = when (L.active) {
            null -> es + en
            "es" -> es
            else -> en
        }
}

private fun l(es: Any = emptyList<String>(), en: Any = emptyList<String>()): Label {
    @Suppress("UNCHECKED_CAST")
    fun list(v: Any) = if (v is String) listOf(v) else v as List<String>
    return Label(list(es), list(en))
}

object L {
    val LANGUAGES = listOf("es", "en")

    @Volatile
    var active: String? = null  // null = not detected yet: match every language

    fun setLanguage(lang: String?) {
        require(lang == null || lang in LANGUAGES)
        active = lang
    }

    // Lobby (Aventura / Adventure tab)
    val PATROL = l("patrulla", "patrol")
    val STARS_BUTTON = l("de estrellas", "challenge")
    val ELITE_ON = l("activado", "on")
    val ELITE_OFF = l("apagado", "off")
    val START_NORMAL = l("inicio", "start")
    val START_ELITE = l("listo", "ready")
    val LOADING = l("cargando")
    val POPUP_CLOSE = l("para cerrar", "to close")
    val LOBBY_TAB = l("aventura", "adventure")  // exact; footer tab label, dimmed under lobby popups
    val MODES_BUTTON = l("modos", "modes")      // exact; lobby bottom-right (OCR often garbles it)

    // Star challenge list
    val STAR_LIST_TITLE = l("desafio de", "star challenge")
    val LIST_REWARDS = l("recompensas", "rewards")

    val ELITE_DIALOG_TITLE = l("modo elite", "elite mode")

    // Energy popup
    val ENERGY_POPUP_TITLE = l("comprar", "purchase")
    val ENERGY_CHANCES = l("intentos restantes", "chances left")
    val ENERGY_FREE = l("gratis", "free")
    val DAILY_PACK_CLAIMED = l("se actualiza en", "refresh in")

    // Level end
    val CONTINUE = l("continuar", "continue")
    val CONFIRM = l("confirmar", "confirm")  // Dungeon Dive end screen button (English guessed)
    val DEFEAT = l("derrota", "defeat")
    val VICTORY = l("victoria", "victory")
    val DOUBLE_REWARD = l(en = "x2 rewards")

    // In level
    val SKILL_PROMPT = l("selecciona una habilidad", "select a skill")
    val EXACT_BUTTONS = l(listOf("girar", "girar!", "reclamar"), listOf("spin", "spin!", "claim"))
    val CONTINUE_BUTTONS = listOf(l("toca en cualquier lugar", "tap anywhere"), l("toca para continuar", "tap to continue"))
    val DUEL_ROLL = l("tirar", "roll")
    val DUEL_STAND = l("resistir", "stand")
    val DUEL_SCORE_PREFIX = l("yo", "me")
    val FLIP_CARDS_PROMPT = l("voltea 3 de las mismas", "flip 3 identical cards")
    val SHOP_REROLL = l("nueva tirada", "reroll")
    val SKILL_REROLL = l("volver a tirar", "reroll")
    val PATROL_TIME = l("tiempo de patrulla", "patrol time")
    val PATROL_CLAIM = l("reclamar", "claim")
    val QUICK_PATROL = l("patrulla rapid", listOf("quick patro", "quickpatro"))
    val QUICK_PATROL_TEXT = l("reclama de inmediato", "immediately claim")
    val REMAINING = l("cantidad restante", "remaining")
    val FREE = l("gratis", "free")
    val SOLD_OUT = l(listOf("agotado", "vendido"), listOf("sold out", "soldout"))
    val BLACK_MARKET = l("mercado negro", "black market")
    val LEAVE = l("salir", listOf("exit", "leave", "walk away"))
    val FORTUNE_TELLER = l("adivino", "fortune teller")
    val FIGHT_ROUND = l("ronda", "round")
    val REVIVE_PROMPT = l("revivir ahora", "revive")
    val REVIVE_FREE = l("gratis", "free")
    val LEVEL_MODIFIERS = l("modificadores de nivel", "level modifiers")

    // Full routine
    val GUILD_BUTTON = l("gremio", listOf("guild", "guiid"))
    val ARENA = l("arena", "arena")
    val ARENA_CLOSED = l("abre en", "opens in")
    val TOWER = l("desafio de torre", "tower challenge")
    val MINES = l("minas de cristal", listOf("crystal mines", "crystalmines"))
    val PETS = l(listOf("reino de las mascotas", "reino de mascotas"), listOf("pet kingdom", "petkingdom"))
    val CHALLENGE = l(listOf("desafiar", "desafio"), "challenge")
    val ARENA_PANEL = l("desafio de la arena", "arena challenge")
    val FREE_REFRESH = l("recarga gratis", "free refresh")
    val TOWER_TITLE = l("torre de los heroes", "tower of heroes")
    val TOWER_NEXT_FLOOR = l("proximo piso", "next floor")  // tower victory: the next floor right away; en guessed
    val TOWER_CLEARED = l(listOf("felicidades", "enhorabuena"), "congratulations on clearing")
    val DIFFICULTY = l("dificultad", "difficulty")
    val SWEEP = l("barrer", "sweep previous")
    val AD_TICKETS = l("boletos de mazmorra", "dungeon tickets")
    val DOJO = l("batalla de dojo", "dojo battle")
    val DIVE = l("descenso a", "dungeon dive")
    val DIVE_REWARDS = l("recompensas", "rewards")
    val DOJO_CHEST = l("reclamar", "claim")
    val MENU_DAILY = l(listOf("diarias", "recompensas diarias"), listOf("daily", "daily rewards"))
    val MENU_MAIL = l("correo", "mail")
    val DAILY_TITLE = l("recompensas diarias", "daily rewards")
    val DAILY_CLAIM = l("reclamar", "claim")
    val DAILY_WEB_CLAIM = l("reclamar ahora", "claim now")
    val MAIL_TITLE = l("correo", "mail")
    val VIP_CARDS = l(listOf("tarjetas vip", "tarjetas", "vip"), listOf("vip cards", "cards", "vip"))
    val CLAIM_ALL = l("reclamar todo", "claim all")
    val GUILD_HALL = l("sala de", listOf("guildhall", "guild hall"))
    val GUILD_HALL_LOWER = l("gremio", "guild hall")  // exact; its second line (the flag over "Sala de" garbles it)
    val DONATE = l("donar", "donate")
    val DONATION_TITLE = l("donacion de gremio", "guild donation")
    val RAID_BOSS = l("incursion", "raid boss")
    val RAID_TITLE = l("asalto de gremio", "guild raid")
    val RAID_ATTEMPTS = l("intentos diarios", "daily attempts left")
    val LEARN_SKILLS = l("aprender habilidades", "learn skills")
    val UPDATE_REQUIRED = l("nueva actualizacion", "new update")
    val RESUME_ADVENTURE = l(listOf("continuar la aventura", "aventura en curso"), listOf("continue adventure", "ongoing adventure"))  // buttons: Abandonar / Confirmar
    val OK = l(listOf("ok", "aceptar", "confirmar"), listOf("ok", "confirm"))
    val TAP_TO_CONTINUE = CONTINUE_BUTTONS[1]
    val TAP_TO_CLAIM = CONTINUE_BUTTONS[0]
    val RARITIES = listOf(  // best first; exact match on the card's tag
        l(listOf("mitico", "mitica"), "mythic"),
        l(listOf("legendario", "legendaria"), "legendary"),
        l(listOf("epico", "epica"), "epic"),
        l(listOf("raro", "rara"), "rare"),
        l("comun", "common"),
    )

    /** Language of a lobby screen, from its "Patrulla"/"Patrol" button. */
    fun detectLanguage(texts: List<Text>): String? {
        val norms = texts.map { it.norm }
        return LANGUAGES.firstOrNull { lang ->
            val vs = if (lang == "es") PATROL.es else PATROL.en
            vs.any { v -> norms.any { v in it } }
        }
    }
}
