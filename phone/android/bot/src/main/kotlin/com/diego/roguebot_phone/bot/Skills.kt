package com.diego.roguebot_phone.bot

import org.json.JSONObject
import java.io.File

/**
 * Port of roguebot/skills.py: skill database (skills.json), with tags inferred for new skills.
 * The phone keeps its own copy (seeded from the desktop bot's data/skills.json).
 */
object Skills {
    val DAMAGE_TYPES = listOf("ice", "lightning", "fire", "shuriken", "venom", "bleed")
    val MAGIC_TYPES = listOf("ice", "lightning", "fire")
    const val PHYSICAL = "physical"
    const val MAGIC = "magic"
    const val DAMAGE = "damage"
    const val SUPPORT = "support"
    val RARITY_NAMES = listOf("mythic", "legendary", "epic", "rare", "common")

    private val TYPE_WORDS = linkedMapOf(
        "ice" to listOf("ice", "icicle", "chill", "frost", "freez", "frozen", "snow", "hielo", "carambano", "escalofrio",
            "frio", "escarcha", "congel", "nieve"),
        "lightning" to listOf("lightning", "bolt", "thunder", "shock", "electr", "spark", "rayo", "relampago", "trueno",
            "descarga", "chispa"),
        "fire" to listOf("fire", "burn", "flame", "blaze", "ignit", "inferno", "fuego", "quema", "llama", "ardiente",
            "incendi", "ascua"),
        "shuriken" to listOf("shuriken"),
        "venom" to listOf("poison", "venom", "toxic", "veneno", "venen", "toxic"),
        "bleed" to listOf("bleed", "sangr", "wound", "herida"),
    )
    private val DAMAGE_WORDS = listOf("atk", "atq", "damage", "dmg", "dano", "attack", "ataque", "crit", "execut", "ejecut",
        "counter", "contraataque", "strike", "golpe")
    private val SUPPORT_WORDS = listOf("shield", "escudo", "dodge", "evasion", "evade", "heal", "cura", "recover", "recupera",
        "restor", "restaura", "regenera", "def$", "max hp", "hp max", "lifesteal", "robo de vida", "revive", "revivir")

    /** Stems match at a word start; a trailing "$" makes it a whole word. The text is normalized (no accents), so
     * a plain \b works (Android's regex engine rejects the (?U) flag). */
    private fun regex(stems: List<String>): Regex = Regex(
        "\\b(" + stems.joinToString("|") { if (it.endsWith("$")) Regex.escape(it.dropLast(1)) + "\\b" else Regex.escape(it) } + ")")

    private val TYPE_RE = TYPE_WORDS.mapValues { regex(it.value) }
    private val NATURE_RE = linkedMapOf(MAGIC to regex(listOf("magic", "magia")), PHYSICAL to regex(listOf("physical", "fisic")))
    private val DAMAGE_RE = regex(DAMAGE_WORDS)
    private val SUPPORT_RE = regex(SUPPORT_WORDS)

    /** Letters only, so OCR variants share a key. */
    fun skillKey(name: String): String = normalize(name).filter { it in 'a'..'z' }

    data class Tags(val damageType: String?, val nature: String, val role: String)

    fun inferTags(name: String, description: String): Tags {
        val text = normalize("$name . $description")
        val found = TYPE_RE.mapNotNull { (t, rx) -> rx.find(text)?.let { it.range.first to t } }
        val damageType = found.minWithOrNull(compareBy<Pair<Int, String>> { it.first }.thenBy { it.second })?.second
        var nature = if (damageType in MAGIC_TYPES) MAGIC else PHYSICAL
        if (damageType == null) {
            val mentions = NATURE_RE.mapNotNull { (n, rx) -> rx.find(text)?.let { it.range.first to n } }
            nature = mentions.minWithOrNull(compareBy<Pair<Int, String>> { it.first }.thenBy { it.second })?.second ?: PHYSICAL
        }
        val role = when {
            damageType != null -> DAMAGE
            SUPPORT_RE.containsMatchIn(normalize(name)) -> SUPPORT
            else -> {
                val f = listOf(DAMAGE to DAMAGE_RE, SUPPORT to SUPPORT_RE).mapNotNull { (r, rx) -> rx.find(text)?.let { it.range.first to r } }
                f.minWithOrNull(compareBy<Pair<Int, String>> { it.first }.thenBy { it.second })?.second ?: DAMAGE
            }
        }
        return Tags(damageType, nature, role)
    }
}

data class Skill(
    val name: String,
    val lang: String?,
    val rarity: String,
    val damageType: String?,
    val nature: String,
    val role: String,
    val description: String = "",
    val auto: Boolean = true,
)

class Catalog(private val file: File?) {
    val skills = LinkedHashMap<String, Skill>()

    init {
        if (file != null && file.exists()) {
            val data = JSONObject(file.readText(Charsets.UTF_8))
            for (key in data.keys()) {
                val v = data.getJSONObject(key)
                skills[key] = Skill(v.getString("name"), v.optString("lang").ifEmpty { null }.takeUnless { v.isNull("lang") },
                    v.getString("rarity"), if (v.isNull("damage_type")) null else v.getString("damage_type"),
                    v.getString("nature"), v.getString("role"), v.optString("description", ""), v.optBoolean("auto", true))
            }
        }
    }

    /** The known skill with this name (tolerating small OCR differences), or a new one, saved. */
    fun lookup(name: String, description: String, rarity: String, lang: String?): Skill {
        val key = Skills.skillKey(name)
        skills[key]?.let { return it }
        val close = skills.keys.map { it to ratio(key, it) }.filter { it.second >= 0.85 }.maxByOrNull { it.second }
        if (close != null) return skills.getValue(close.first)
        val t = Skills.inferTags(name, description)
        val skill = Skill(name, lang, rarity, t.damageType, t.nature, t.role, description)
        skills[key] = skill
        Log.info("New skill: $name ($rarity, ${t.damageType ?: "-"}, ${t.nature}, ${t.role})")
        save()
        return skill
    }

    fun save() {
        val f = file ?: return
        val root = JSONObject()
        for (k in skills.keys.sorted()) {
            val s = skills.getValue(k)
            root.put(k, JSONObject().apply {
                put("name", s.name); put("lang", s.lang ?: JSONObject.NULL); put("rarity", s.rarity)
                put("damage_type", s.damageType ?: JSONObject.NULL); put("nature", s.nature); put("role", s.role)
                put("description", s.description); put("auto", s.auto)
            })
        }
        f.parentFile?.mkdirs()
        f.writeText(root.toString(1), Charsets.UTF_8)
    }

    companion object {
        /** difflib.SequenceMatcher(None, a, b).ratio(): 2 * matched / total (Ratcliff/Obershelp). */
        fun ratio(a: String, b: String): Double {
            if (a.isEmpty() && b.isEmpty()) return 1.0
            return 2.0 * matched(a, 0, a.length, b, 0, b.length) / (a.length + b.length)
        }

        private fun matched(a: String, alo: Int, ahi: Int, b: String, blo: Int, bhi: Int): Int {
            var bestI = alo; var bestJ = blo; var bestK = 0
            for (i in alo until ahi) for (j in blo until bhi) {
                var k = 0
                while (i + k < ahi && j + k < bhi && a[i + k] == b[j + k]) k++
                if (k > bestK) { bestI = i; bestJ = j; bestK = k }
            }
            if (bestK == 0) return 0
            return bestK + matched(a, alo, bestI, b, blo, bestJ) + matched(a, bestI + bestK, ahi, b, bestJ + bestK, bhi)
        }
    }
}
