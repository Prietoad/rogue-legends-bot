package com.diego.roguebot_phone.bot

import java.time.ZoneId

/**
 * Port of roguebot/request.py, report.py and __main__.make_runner: what the user asked for, and the
 * Start action with its recovery. On the phone there is no emulator to restart: a recovery brings the
 * game to the front again and goes on.
 */
data class RunRequest(
    val mode: Mode,
    val level: Int?,                  // null = last unlocked level
    val repeat: Boolean = false,      // replay until out of energy (always, from the UI)
    val full: Boolean = false,
    val build: Build = Build(),
    val lastBeaten: Boolean = false,
    val pendingStars: Boolean = false,
    val loop: Boolean = false,        // keep running: out of energy -> wait for energy -> (routine ->) levels again
    val ads: Boolean = false,
)

const val LATEST = "latest"
const val STARS = "stars"
const val BEATEN = "beaten"
const val PENDING = "pending"

/** Validate the form values. Throws IllegalArgumentException("bad_level") (an i18n key).
 * Levels always run until out of energy; `loop` then waits for energy and starts again. */
fun buildRequest(mode: String, source: String, level: String, full: Boolean = false,
                 build: Build = Build(), loop: Boolean = false, ads: Boolean = false): RunRequest {
    val m = Mode.values().first { it.value == mode }
    if (source == LATEST || source == BEATEN || source == PENDING) {
        return RunRequest(m, null, true, full, build, lastBeaten = source == BEATEN || source == PENDING,
            pendingStars = source == PENDING, loop = loop, ads = ads)
    }
    val n = level.trim().toIntOrNull()
    if (n == null || n < 1 || !level.trim().isDigits()) throw IllegalArgumentException("bad_level")
    return RunRequest(m, n, true, full, build, loop = loop, ads = ads)
}

data class Report(
    val results: List<LevelScreen> = emptyList(),
    val repeat: Boolean = false,
    val dryRun: Boolean = false,
    val parts: List<Pair<String, String>> = emptyList(),
)

class NoEnergyError(msg: String) : NavigationError(msg)

const val ENERGY_READS = 3
const val PATROL_FAILS_TO_BACK_OFF = 2
val PERMANENT_ERRORS = setOf("err_game_update", "err_game_missing", "err_service")

/** Screens only seen inside a level (not "continue"/"leave" buttons: lobby popups have those too). */
fun levelInProgress(img: Frame, texts: List<Text>): Boolean = Screens.classifyLevelScreen(img, texts).kind in setOf(
    LevelScreen.BOARD_READY, LevelScreen.AUTO_PLAY, LevelScreen.FIGHT, LevelScreen.SKILL_PICK, LevelScreen.SHOP,
    LevelScreen.EVENT, LevelScreen.DICE_DUEL, LevelScreen.FLIP_CARDS, LevelScreen.REVIVE, LevelScreen.VICTORY,
    LevelScreen.DEFEAT, LevelScreen.DOUBLE_REWARD, LevelScreen.FORTUNE_TELLER) && !Screens.lobbyBehind(texts)

/** Errors that differ only in numbers or screenshot paths count as the same error. */
fun errorKey(e: Throwable): String =
    Regex("\\(screenshot:.*?\\)|\\d+").replace("${e.javaClass.simpleName}: ${e.message}", "").trim()

/** When the patrol is worth opening again: its reward is due, or local midnight, whichever is first. */
fun patrolNext(wait: Double?, now: Double, zone: ZoneId = ZoneId.systemDefault()): Double {
    if (wait == null) return now
    val today = java.time.Instant.ofEpochMilli((now * 1000).toLong()).atZone(zone).toLocalDate()
    val midnight = today.plusDays(1).atStartOfDay(zone).toEpochSecond().toDouble()
    return minOf(now + wait, midnight)
}

/** The phone's Start action. `wall` is epoch seconds (patrol timing); `clock` measures waits. */
class Runner(
    private val device: Device,
    private val ocr: Ocr,
    private val catalog: Catalog,
    private val clock: Clock = SystemClock,
    private val debug: DebugSink = DebugSink { _, name -> name },
    private val wall: () -> Double = { System.currentTimeMillis() / 1000.0 },
    private val dryRun: Boolean = false,
) {
    private class State(var request: RunRequest) {
        val results = ArrayList<LevelScreen>()
        var progress = RoutineProgress()  // routine parts done: a recovery resumes at the part that broke
        var routineDone = false
        var noStars = false
        var patrolNext = 0.0
        var patrolFails = 0
        var resumed = 0  // interrupted levels played out (progress for the same-error count)
    }

    fun run(request: RunRequest): Report {
        val state = State(request)
        val errors = HashMap<String, Int>()
        var progress = 0
        while (true) {
            try {
                return attempt(state)
            } catch (e: Stopped) {
                throw e
            } catch (e: Exception) {
                if (dryRun || e is NoEnergyError || e is LevelUnavailable || (e is BotError && e.key in PERMANENT_ERRORS)) throw e
                val done = state.results.size + state.progress.parts.size + state.resumed
                if (done > progress) {  // a level or routine part finished since the last error
                    errors.clear()
                    progress = done
                }
                val key = errorKey(e)
                errors[key] = (errors[key] ?: 0) + 1
                if (errors.getValue(key) > Config.MAX_SAME_ERROR) {
                    Log.error("Same error ${errors[key]} times, giving up: ${e.message}")
                    throw e
                }
                Log.error("Error: ${e.message}. Bringing the game back and trying again (${errors[key]}/${Config.MAX_SAME_ERROR})")
            }
        }
    }

    private fun startLevel(nav: Navigator, r: RunRequest): Int? {
        if (r.pendingStars) nav.startPendingStars(r.mode)?.let { return it }
        if (r.lastBeaten) return nav.startLastBeaten(r.mode)
        if (r.level == null) return nav.startLatest(r.mode)
        nav.startStarChallenge(r.mode, r.level)
        return r.level
    }

    private fun energy(nav: Navigator): Int {
        repeat(ENERGY_READS) { nav.goToLobby().energy?.let { return it } }
        throw NavigationError("Could not read the energy counter")
    }

    private fun claimPatrol(routine: Routine, state: State) {
        if (wall() < state.patrolNext) return
        try {
            routine.patrol()
            state.patrolNext = patrolNext(routine.patrolWait, wall())
            state.patrolFails = 0
        } catch (e: RuntimeException) {
            if (e !is NavigationError && e !is PlayError) throw e
            Log.error("Patrol failed: ${e.message}")
            state.patrolFails++
            if (state.patrolFails >= PATROL_FAILS_TO_BACK_OFF) state.patrolNext = patrolNext(Config.PATROL_CLAIM_AFTER.toDouble(), wall())
            routine.nav.goToLobby()
        }
    }

    private fun waitForEnergy(nav: Navigator) {
        while (true) {
            try {
                val e = nav.goToLobby().energy ?: 0
                if (e >= Config.MIN_RUN_ENERGY) return
                Log.info("Waiting for energy ($e/${Config.MIN_RUN_ENERGY})")
            } catch (e: NavigationError) {
                Log.error("Waiting for energy: ${e.message}")
            }
            device.waitFor(Config.ENERGY_WAIT_POLL)
        }
    }

    /** One try: the game in front, then the requested work. `state` keeps results across tries. */
    private fun attempt(state: State): Report {
        var request = state.request
        val nav = Navigator(device, ocr, dryRun, request.ads, clock, debug)
        val playLevel = { Player(device, ocr, request.build, catalog, request.ads, clock, debug).playLevel() }
        nav.resumeLevel = { playLevel().also { state.resumed++ } }
        var opened = false
        if (device.foregroundPackage() != Config.PACKAGE) {
            Log.info("Opening Rogue Legend")
            device.launch(Config.PACKAGE)
            if (device.foregroundPackage() != Config.PACKAGE) throw BotError("err_game_missing")
            opened = true
        }
        // The phone can't restart the game: a level left running (the bot was stopped or crashed mid-level)
        // is still on screen. Play it out first, like the desktop does after its "resume?" prompt.
        val (img, texts) = nav.capture()
        if (levelInProgress(img, texts)) {
            Log.info("A level is in progress: playing it out")
            playLevel()
        } else if (opened) {
            nav.waitForLobby(Config.GAME_LOAD_TIMEOUT)
        }
        nav.detectLanguage()
        if (dryRun) {
            startLevel(nav, request)
            return Report(dryRun = true)
        }
        val results = state.results
        var cycle = 0
        while (true) {
            cycle++
            if (request.full && !state.routineDone) {
                val routine = Routine(device, ocr, nav, request.ads, playLevel, clock, request.build, catalog)
                routine.runParts(state.progress)
                // just opened by the routine: not again before the first level
                routine.patrolWait?.let { state.patrolNext = patrolNext(it, wall()) }
            }
            state.routineDone = true
            while (true) {
                if (!request.repeat && results.isNotEmpty()) return Report(results.toList())
                claimPatrol(Routine(device, ocr, nav, request.ads, clock = clock), state)  // first: its quick patrols spend energy
                if (request.repeat && energy(nav) < Config.MIN_RUN_ENERGY) {
                    if (nav.claimFreeEnergy() < Config.MIN_RUN_ENERGY) break
                }
                val played = try {
                    startLevel(nav, request)
                } catch (e: StarsUnavailable) {
                    Log.warn("${e.message}: playing the last unlocked level instead")
                    state.noStars = true
                    request = request.copy(level = null, lastBeaten = false, pendingStars = false)
                    state.request = request
                    nav.startLatest(request.mode)
                }
                results.add(Player(device, ocr, request.build, catalog, request.ads, clock, debug).playLevel())
                if (request.level == null && !request.lastBeaten && results.last() == LevelScreen.VICTORY && played != null && !state.noStars) {
                    request = request.copy(level = played)  // keep replaying this one from Desafío de Estrellas
                    state.request = request
                }
                nav.goToLobby()
                Log.info("Level finished: ${results.last().value} (run ${results.size})")
                if (!request.repeat) return Report(results.toList())
            }
            if (!request.loop) break
            Log.info("Cycle $cycle finished (${results.size} runs so far), waiting for energy")
            waitForEnergy(nav)
            state.routineDone = false
            state.progress = RoutineProgress()
        }
        if (results.isEmpty() && !request.full) throw NoEnergyError("Not enough energy to start a run, and no free energy to claim")
        return Report(results.toList(), repeat = true, parts = state.progress.parts.toList())
    }
}
