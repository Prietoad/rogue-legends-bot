package com.diego.roguebot_phone.bot

/**
 * Port of roguebot/config.py. All coordinates are reference pixels (portrait 1440x2560); the phone's
 * screen is mapped to it by [ScreenMap]. Keep the values in sync with config.py.
 */
object Config {
    const val PACKAGE = "com.pockethaven.roguelegend"
    const val SCREEN_W = 1440
    const val SCREEN_H = 2560
    const val GAME_LOAD_TIMEOUT = 180.0     // seconds from opening the game to its lobby
    const val MAX_SAME_ERROR = 3            // recoveries for one error before the bot gives up

    // Fixed tap targets (elements without readable text)
    val AVENTURA_TAB = P(720, 2410)
    val ELITE_TOGGLE = P(933, 2120)
    val LIST_BACK = P(120, 2448)

    // Popups and footer
    const val TUTORIAL_HAND_MIN_SCORE = 0.78
    val TUTORIAL_TAP_OFFSET = P(24, 215)
    const val TUTORIAL_MAX_STEPS = 8
    const val CLOSE_X_MIN_SCORE = 0.9
    val FOOTER_Y = 2380 until 2440
    val FOOTER_SAMPLES = listOf((60 until 300) to intArrayOf(80, 55, 123), (330 until 570) to intArrayOf(107, 80, 74),
        (600 until 840) to intArrayOf(107, 84, 89), (870 until 1110) to intArrayOf(105, 59, 106),
        (1140 until 1380) to intArrayOf(95, 86, 91))  // the 5 tabs when not selected, BGR
    const val FOOTER_MIN_TABS = 4  // the selected tab has another color
    const val FOOTER_COLOR_TOLERANCE = 12

    // Top bar
    const val TOP_BAR_MAX_Y = 150
    val ENERGY_X = 700..1000

    // Energy popup
    val ENERGY_ICON = P(745, 85)
    val ENERGY_POPUP_CLOSE = P(720, 1947)
    const val CHANCES_NUMBER_BELOW = 70
    const val CHANCES_NUMBER_DX = 150
    const val VIDEO_BELOW_CHANCES = 103
    const val VIDEO_YELLOW_MIN_FRACTION = 0.4
    const val ENERGY_WAIT_POLL = 300.0
    const val MIN_RUN_ENERGY = 5

    // Elite start dialog
    val STAR_ICONS_X = listOf(1245, 1312, 1379)
    val ELITE_COSTS = listOf(5, 10, 15)
    val ELITE_COST_MINUS = P(480, 1747)
    val ELITE_COST_PLUS = P(960, 1747)
    val ELITE_DIALOG_CLOSE = P(720, 2027)
    const val COST_BELOW_START_MAX = 120

    // Star challenge list geometry
    const val LIST_TOP = 290
    const val LIST_BOTTOM = 2300
    const val HEADER_ABOVE_BUTTON = 384
    const val HEADER_HALF_HEIGHT = 60
    val HEADER_X_RANGE = 20 to 1150
    const val CARD_PITCH = 567
    const val TARGET_HEADER_Y = 700
    const val MAX_DRAG = 1100
    const val MIN_DRAG = 150
    const val SCROLL_X = 720
    const val SCROLL_DURATION = 1.0

    // In-level
    val DICE_BUTTON = P(720, 2150)
    val DICE_REGION = Region(520, 2020, 920, 2280)
    const val DICE_RED_MIN_FRACTION = 0.4
    const val DICE_GREEN_MIN_FRACTION = 0.4
    const val AUTO_PLAY_HOLD = 2.0
    val SPEED_BUTTON = P(152, 2435)
    val SPEED_LABEL_X = 60..280
    val SPEED_LABEL_Y = 2390..2480
    val SKILL_RARITY_X = 260..390
    const val SKILL_TAP_BELOW_RARITY = 125
    val EVENT_TITLE_Y = 1360..1440
    const val EVENT_TITLE_CENTER_TOLERANCE = 60
    val EVENT_LABEL_Y = 1750..1840
    const val EVENT_ICON_BELOW_LABEL = 238
    const val EVENT_DISABLED_MAX_SATURATION = 70
    val FLIP_CARDS = listOf(1280, 1560, 1840).flatMap { y -> listOf(299, 579, 859, 1139).map { x -> P(x, y) } }
    const val FLIP_FACE_DOWN_MIN_FRACTION = 0.25
    val FORTUNE_TELLER_BACK = P(293, 2280)
    const val SKILL_TEXT_MIN_X = 380
    const val SHOP_PRICE_MIN_X = 1080
    val SKILL_NAME_BELOW_TAG = -10..70
    const val SKILL_CARD_HEIGHT = 330
    const val REROLL_COUNT_BELOW = 110
    val MONEY_REGION = Region(0, 140, 320, 210)
    const val DUEL_STAND_AT = 15
    const val SAME_TAP_TOLERANCE = 25
    const val DOUBLE_REWARD_TRIES = 2
    const val MAX_REPEATED_TAPS = 6
    const val STUCK_TAP_SECONDS = 10.0
    const val CHANGE_TIMEOUT = 5.0

    // Timing (seconds)
    const val POLL_INTERVAL = 0.3
    const val UNKNOWN_SCREEN_TIMEOUT = 20.0
    const val UI_SETTLE = 0.7
    const val SCROLL_SETTLE = 0.8
    const val VIDEO_SETTLE = 3.0

    // Full routine
    const val BACK_ARROW_MIN_SCORE = 0.85
    val MODES_BUTTON = P(1350, 2130)
    const val LOBBY_LEFT_ICONS_MAX_X = 250
    const val DONATE_FREE_MAX = 5
    const val PATROL_CLAIM_AFTER = 7 * 3600 + 50 * 60
    val PATROL_BUTTONS_Y = 1700..1850
    val REMAINING_BELOW_BUTTON = 80 to 170
    const val QUICK_PATROL_CYAN_MIN = 0.08
    val GUILD_BUTTON = P(89, 2130)
    val ARENA_TICKETS_REGION = Region(815, 45, 940, 125)
    val ARENA_POWER_Y = 440 to 520
    val ARENA_ROWS_Y = 550 to 1900
    val ARENA_ROW_POWER_X = 480 to 680
    val ARENA_ROW_POWER_BELOW = 30 to 130
    val TOWER_CHEST = P(720, 1240)
    val DUNGEON_TICKETS_Y = 1650 to 1780
    const val SKILL_CARD_TAP_BELOW_RARITY = 90
    const val SKILL_CARD_TAP_X = 800
    const val MODE_SUBTITLE_BELOW = 150
    val MODES_SCROLL_UP = P(720, 700) to P(720, 2000)
    const val MODES_MAX_SCROLLS = 3
    const val MODE_FIGHT_TIMEOUT = 240.0
    const val MAX_MODE_ACTIONS = 40
    val DOJO_TICKETS_REGION = Region(1270, 45, 1420, 130)
    val DOJO_CHEST_Y = 2000 to 2250
    const val DOJO_TITLE_MAX_Y = 400
    val MENU_BUTTON = P(80, 310)
    const val MENU_MAX_X = 700
    const val BROWSER_BACK_MAX = 5
    val OTHER_APP_AD_TAP = P(720, 1280)
}
