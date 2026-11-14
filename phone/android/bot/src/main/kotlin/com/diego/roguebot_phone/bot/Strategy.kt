package com.diego.roguebot_phone.bot

import kotlin.math.abs

/**
 * Port of roguebot/strategy.py: which fork path, which event option, which shop stat item, which miner
 * tile. Pure: no device, no OCR. See strategy.py for what each rule is based on.
 */
object Strategy {
    private val NOT_LETTERS = Regex("[^a-z]")

    private fun letters(s: String) = NOT_LETTERS.replace(s, "")  // OCR drops or adds spaces and commas ("No,Gracias")

    private fun isLabel(norm: String, label: Label) = letters(norm) in label.variants.map(::letters)

    /** Index of the fork path to take; shops[i] = path i leads to a shop. */
    fun choosePath(shops: List<Boolean>, coins: Int?): Int {
        if (true in shops && coins != null && coins >= Config.PATH_SHOP_COINS) return shops.indexOf(true)
        return if (false in shops) shops.indexOf(false) else 0
    }

    /** Index of the event option to take (options = their normalized labels, left to right), or null when
     *  no rule knows the event (the caller then leaves it, or takes the leftmost option). */
    fun chooseEvent(options: List<String>, hp: Double?): Int? {
        val rest = options.indexOfFirst { isLabel(it, L.EVENT_REST) }
        val train = options.indexOfFirst { isLabel(it, L.EVENT_TRAIN) }
        if (rest >= 0 && train >= 0) return if (hp == null || hp < Config.REST_BELOW_HP) rest else train
        for (label in L.EVENT_PREFER) {
            val i = options.indexOfFirst { isLabel(it, label) }
            if (i >= 0) return i
        }
        return null
    }

    /** Blacksmith's anvil: gamble on the upgrade (true) or take the item. Unreadable chance: take. */
    fun anvilUpgrade(chance: Int?) = chance != null && chance >= Config.ANVIL_MIN_CHANCE

    /** Cursed vendor: index of the contract to sign (terms = each contract's normalized text). The best sum
     *  of the known terms (L.CONTRACT_TERMS); unknown terms count 0, ties go to the first. */
    fun chooseContract(terms: List<String>): Int {
        val scores = terms.map { text -> L.CONTRACT_TERMS.filter { (label, _) -> label.variants.any { it in text } }.sumOf { it.second } }
        return scores.indexOf(scores.max())
    }

    /** The stat item to buy next (Screens.BOOST / HEAL), or null. prices = the items still on sale. */
    fun shopItem(prices: Map<String, Int>, coins: Int, hp: Double?): String? {
        val heal = prices[Screens.HEAL]
        if (heal != null && hp != null && hp < Config.SHOP_HEAL_BELOW_HP && heal <= coins) return Screens.HEAL
        val boost = prices[Screens.BOOST]
        if (boost != null && boost <= coins) return Screens.BOOST
        return null
    }

    /** "Minero de Tesoros": index of the tile to dig, or null (no dirt left). A found piece is followed
     *  first (in line with two pieces when there are two); else diagonals 3 apart, from the center out. */
    fun minerDig(tiles: List<String>, done: Set<Int>): Int? {
        val n = Config.MINER_SIZE
        var best: Int? = null
        var bestScore = 0
        for ((i, tile) in tiles.withIndex()) {
            if (tile != Screens.TREASURE || i in done) continue
            val r = i / n; val c = i % n
            for ((dr, dc) in listOf(0 to 1, 0 to -1, 1 to 0, -1 to 0)) {
                val rr = r + dr; val cc = c + dc
                if (rr !in 0 until n || cc !in 0 until n || tiles[rr * n + cc] != Screens.DIRT) continue
                val br = r - dr; val bc = c - dc  // the tile behind: another piece there means this is the treasure's line
                val inLine = br in 0 until n && bc in 0 until n && tiles[br * n + bc] == Screens.TREASURE && br * n + bc !in done
                val score = if (inLine) 2 else 1
                if (score > bestScore) { best = rr * n + cc; bestScore = score }
            }
        }
        if (best != null) return best
        val center = (n - 1) / 2.0
        return tiles.indices.filter { tiles[it] == Screens.DIRT }
            .minWithOrNull(compareBy({ (it / n + it % n) % 3 != 0 }, { abs(it / n - center) + abs(it % n - center) }, { it }))
    }
}
