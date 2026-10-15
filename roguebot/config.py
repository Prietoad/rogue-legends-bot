"""Static configuration. All coordinates are in device pixels (portrait 1440x2560)."""

ADB_PATH = r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe"
SERIAL = "127.0.0.1:16384"          # default; the real one comes from MuMuManager (adb_host_ip:adb_port)
EMULATOR_BOOT_TIMEOUT = 240          # seconds for MuMu Player to boot Android
EMULATOR_SHUTDOWN_TIMEOUT = 60       # seconds for "shutdown" to close it before its processes are killed
GAME_OPEN_TIMEOUT = 60               # seconds for Rogue Legend to come to the front after launching it
GAME_LOAD_TIMEOUT = 180              # seconds from launching the game to its lobby (splash, loading, popups)
EMULATOR_POLL = 3
ADB_TIMEOUT = 30                     # seconds for one screenshot/tap/swipe; a frozen emulator raises instead of hanging
FREEZE_TIMEOUT = 60                  # no input and the same frame this long: frozen emulator/game -> restart MuMu
FREEZE_THUMB = (36, 64)              # frames are compared at this size (width, height), grey
FREEZE_MIN_DIFF = 0.05               # mean grey difference that counts as a screen change (frozen: 0; sparkles only: ~0.3)
MAX_SAME_ERROR = 3                   # recoveries (MuMu restart) for one error before the bot gives up
PACKAGE = "com.pockethaven.roguelegend"
SCREEN_SIZE = (1440, 2560)  # (width, height) reference resolution; other 9:16 screens are scaled
ASPECT_TOLERANCE = 0.01

# Fixed tap targets (elements without readable text)
AVENTURA_TAB = (720, 2410)   # footer, center tab
ELITE_TOGGLE = (933, 2120)   # skull button right of INICIO/LISTO
LIST_BACK = (120, 2448)      # back arrow at the bottom-left of the star challenge list

# Popups and footer
TUTORIAL_HAND_MIN_SCORE = 0.78  # tutorial hand template: 0.82-0.97 when shown (it blinks), <=0.66 elsewhere
TUTORIAL_TAP_OFFSET = (24, 215)  # from the hand template center to its target ring (the hand bobs ~50 px above it)
TUTORIAL_MAX_STEPS = 8           # hand taps per go_to_lobby (a tutorial chains several steps)
CLOSE_X_MIN_SCORE = 0.9      # template score: ≥0.998 on popups with ✕, ≤0.61 elsewhere
FOOTER_Y = (2380, 2440)
FOOTER_SAMPLES = (((60, 300), (80, 55, 123)), ((330, 570), (107, 80, 74)), ((600, 840), (107, 84, 89)),
                  ((870, 1110), (105, 59, 106)), ((1140, 1380), (95, 86, 91)))  # the 5 tabs when not selected, BGR
FOOTER_MIN_TABS = 4          # the selected tab has another color (Aventura in the lobby, Mascotas, Tienda...)
FOOTER_COLOR_TOLERANCE = 12  # popups darken these to ~(8, 6, 12)

# Top bar
TOP_BAR_MAX_Y = 150
ENERGY_X = (700, 1000)       # x range of the "12/32" energy counter

# Energy popup (top bar energy icon)
ENERGY_ICON = (745, 85)
ENERGY_POPUP_CLOSE = (720, 1947)
CHANCES_NUMBER_BELOW = 70   # Spanish: the count sits on its own line under "Intentos Restantes Hoy:"
CHANCES_NUMBER_DX = 150
VIDEO_BELOW_CHANCES = 103    # video button center, below its "Chances Left Today: N" text
VIDEO_YELLOW_MIN_FRACTION = 0.4  # measured: video button 0.71 yellow, gem button 0.0
ENERGY_WAIT_POLL = 300      # loop mode: seconds between energy checks while waiting for energy
MIN_RUN_ENERGY = 5           # cheapest run (normal, or elite at x5)

# Elite start dialog ("Modo Élite")
STAR_ICONS_X = (1245, 1312, 1379)  # the 3 star icons right of a star list card header (gold = earned)
ELITE_COSTS = (5, 10, 15)    # energy per run; the bot uses the highest affordable one
ELITE_COST_MINUS = (480, 1747)
ELITE_COST_PLUS = (960, 1747)
ELITE_DIALOG_CLOSE = (720, 2027)
COST_BELOW_START_MAX = 120   # "X5" label sits just below the dialog's INICIO

# Star challenge list geometry
LIST_TOP = 290               # below the "Desafio de Estrella" banner
LIST_BOTTOM = 2300           # above the back / Recompensas footer
HEADER_ABOVE_BUTTON = 384    # card header center is this far above its INICIO/LISTO center
HEADER_HALF_HEIGHT = 60
HEADER_X_RANGE = (20, 1150)  # excludes the star icons on the right
CARD_PITCH = 567             # vertical distance between consecutive card headers
TARGET_HEADER_Y = 700        # where scrolling aims to place the wanted card's header
MAX_DRAG = 1100              # longest single list drag
MIN_DRAG = 150
SCROLL_X = 720
SCROLL_DURATION = 1.0        # slow drags keep Unity's scroll inertia low, so the list moves ~1:1

# In-level
DICE_BUTTON = (720, 2150)                # big red roll button
DICE_REGION = (520, 2020, 920, 2280)     # area sampled to tell red (ready) from grey (rolling)
DICE_RED_MIN_FRACTION = 0.4              # measured: 0.70 ready, ~0 otherwise
DICE_GREEN_MIN_FRACTION = 0.4            # auto-play: lime-green dice, measured 0.50-0.66; normal boards <0.03
AUTO_PLAY_HOLD = 2.0                     # holding the dice this long turns auto-play on (verified live at 2 s)
SPEED_BUTTON = (152, 2435)               # bottom-left "» x2" toggle
SPEED_LABEL_X = (60, 280)
SPEED_LABEL_Y = (2390, 2480)
SKILL_RARITY_X = (260, 390)              # x range of a skill card's rarity tag center ("Común"...)
SKILL_TAP_BELOW_RARITY = 125             # card center, below its rarity tag
EVENT_TITLE_Y = (1360, 1440)             # tile event title band, e.g. "Carro de Botín Abandonado"
EVENT_TITLE_CENTER_TOLERANCE = 60
EVENT_LABEL_Y = (1750, 1840)             # option labels ("Salir", "Descansar"...)
EVENT_ICON_BELOW_LABEL = 238             # option icon center, below its label
EVENT_DISABLED_MAX_SATURATION = 70       # mean HSV saturation of a greyed (disabled) option icon: ~34; enabled >=117
FLIP_CARDS = [(x, y) for y in (1280, 1560, 1840) for x in (299, 579, 859, 1139)]  # 4x3 grid centers
FLIP_FACE_DOWN_MIN_FRACTION = 0.25       # measured: 0.39 face down, 0.08 face up
FORTUNE_TELLER_BACK = (293, 2280)        # back arrow, bottom-left
SKILL_TEXT_MIN_X = 380                   # skill card name/description start right of the rarity icon
SHOP_PRICE_MIN_X = 1080                  # shop card price buttons (and "SALE!") are right of this
SKILL_NAME_BELOW_TAG = (-10, 70)         # the name line sits right of the rarity tag, this far below its center
SKILL_CARD_HEIGHT = 330                  # band of the last card (others end at the next card's tag)
REROLL_COUNT_BELOW = 110                 # skill pick "(1)" / shop "FREE" sit this far below their button
MONEY_REGION = (0, 140, 320, 210)        # in-level coins counter, top-left
DUEL_STAND_AT = 15                       # dice duel: stop rolling at this score
SAME_TAP_TOLERANCE = 25                  # taps this close on the same screen kind count as repeats
DOUBLE_REWARD_TRIES = 2                  # x2 rewards taps per level end before just continuing
MAX_REPEATED_TAPS = 6                    # same screen + same tap this many times in a row...
STUCK_TAP_SECONDS = 10                   # ...and for at least this long -> stuck (taps are fast now)
CHANGE_TIMEOUT = 5                       # seconds to see a tap's effect before deciding again

# Timing (seconds)
POLL_INTERVAL = 0.3          # between captures while waiting (one capture + OCR already takes ~0.9 s)
UNKNOWN_SCREEN_TIMEOUT = 20              # unrecognized for this long -> stop and save a screenshot
UI_SETTLE = 0.7              # after taps; every step re-reads the screen, so this only spares a wasted capture
SCROLL_SETTLE = 0.8          # after a list swipe (the star list also waits for the target card to stop moving)
VIDEO_SETTLE = 3             # after starting a reward video (VIP skips the ad itself)

# Full routine: modes (Arena, Dojo, Tower, Dungeon Dive, Crystal Mines, Pet Kingdom), daily rewards, mail, guild raid
BACK_ARROW_MIN_SCORE = 0.85              # back-arrow template: ~1.0 on menus, <=0.68 elsewhere
MODES_BUTTON = (1350, 2130)              # lobby, bottom-right (its Spanish label "Modos" OCRs badly)
LOBBY_LEFT_ICONS_MAX_X = 250            # lobby left column of icons (Paquete Inicial, Tarjetas VIP, ...)
DONATE_FREE_MAX = 5                      # free donations per visit (seen: 1 per day, then a gem price)
PATROL_CLAIM_AFTER = 7 * 3600 + 50 * 60   # claim the patrol reward only near its 8 h cap (the counter stops there)
PATROL_BUTTONS_Y = (1700, 1850)          # patrol popup: Quick Patrol / Claim row
REMAINING_BELOW_BUTTON = (80, 170)        # quick patrol: "Remaining: N" below its button label
QUICK_PATROL_CYAN_MIN = 0.08              # share of cyan (lightning) pixels left of the energy option's "x10"; gem/video: 0
GUILD_BUTTON = (89, 2130)                # lobby, bottom-left book; only tapped when its label is there
ARENA_TICKETS_REGION = (815, 45, 940, 125)  # arena ticket count (top bar); full-frame OCR misses it
ARENA_POWER_Y = (440, 520)               # our power in the opponent panel header
ARENA_ROWS_Y = (550, 1900)               # opponent rows: their "Challenge" buttons
ARENA_ROW_POWER_X = (480, 680)           # opponent power (sword icon value), below the row's name
ARENA_ROW_POWER_BELOW = (30, 130)        # its y offset from the row's "Challenge" button
TOWER_CHEST = (720, 1240)                # "Congrats" screen after clearing a whole tower: the reward chest
DUNGEON_TICKETS_Y = (1650, 1780)         # Crystal Mines / Pet Kingdom popup: tickets "1/2"
SKILL_CARD_TAP_BELOW_RARITY = 90         # raid skill cards: tap point below the rarity tag
SKILL_CARD_TAP_X = 800
MODE_SUBTITLE_BELOW = 150  # px from a mode card title to its subtitle line ("Abre en 4m", "Piso 16-4")
MODES_SCROLL_UP = ((720, 700), (720, 2000))  # finger drags down = list scrolls up
MODES_MAX_SCROLLS = 3
MODE_FIGHT_TIMEOUT = 240                 # one mode/raid fight, seconds
MAX_MODE_ACTIONS = 40                    # taps within one mode before giving up
DOJO_TICKETS_REGION = (1270, 45, 1420, 130)  # dojo ticket count (top-right); full-frame OCR misses it
DOJO_CHEST_Y = (2000, 2250)              # dojo progress chest "RECLAMAR" ("Intenta el Dojo N veces")
DOJO_TITLE_MAX_Y = 400                   # dojo screen title (the modes list card says the same, lower)
MENU_BUTTON = (80, 310)                  # lobby, top-left ≡ (unlabeled): Correo, Recompensas Diarias...
MENU_MAX_X = 700                         # menu panel entries (left of the lobby's level title)
BROWSER_BACK_MAX = 5                     # Back presses to leave the web store and return to the game
OTHER_APP_AD_TAP = (720, 1280)           # an emulator ad for another app that only closes by tapping it
