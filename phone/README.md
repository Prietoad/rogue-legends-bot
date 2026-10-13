# Rogue Legend bot for Android phones

The desktop bot (`roguebot/`, Python) ported to an Android app that runs on the phone where Rogue Legend is
installed: same options, same routine, same rules (never spends gems, ads only with "Watch ads").

## Install and use
1. Install `RogueLegendBot.apk` (from the GitHub release). Android asks to allow installs from that source.
2. Open the app → "Open accessibility settings" → turn on **Rogue Legend bot** (it taps for you and reads which app is in front).
   Android may first ask to allow "restricted settings" for a sideloaded app: App info → ⋮ → Allow restricted settings.
3. Pick the options and press **Start** → allow **screen capture** (the bot needs to see the game; asked on every Start).
4. The game opens and the bot plays. Stop it from the app or from its notification. Don't use the phone meanwhile.

Requirements: Android 11+, the game in Spanish or English, portrait.

## How it works
```
lib/                      Flutter UI (options saved with shared_preferences, log, status, changelog)
android/bot/              the bot engine, plain Kotlin (no Android): a port of roguebot/ module by module
  Vision.kt               Text, label matching, Frame (pixels), OpenCV-compatible HSV and template matching
  Labels.kt Config.kt     labels.py / config.py
  Screens.kt ModeScreens.kt   screens.py / mode_screens.py (pure recognition)
  Navigation.kt Play.kt Routine.kt   navigation.py / play.py / routine.py
  Skills.kt Build.kt      skills.py / build.py
  Runner.kt               request.py, report.py and __main__.make_runner (the Start action and its recovery)
  ScreenMap.kt            phone screen <-> the 1440x2560 reference the bot works in
  PaddleOcr.kt            the desktop bot's OCR: rapidocr's PP-OCRv6 models and pipeline, on ONNX Runtime
android/app/              the Android side
  BotService.kt           AccessibilityService: taps/swipes (gestures), Back, app in front, open the game
  CaptureService.kt       MediaProjection screen capture (foreground service, notification with Stop)
  Engine.kt               runs the bot on a thread; log/status to the UI; DumpReceiver (diagnostics)
  MainActivity.kt         Flutter <-> engine channels
```
The templates (`roguebot/templates`), the skill database (`data/skills.json`) and the OCR models (from the
rapidocr Python package, `tools/ocr_models.py`) are copied from the desktop bot at build time: one source of
truth. **Same OCR on both:** the phone runs the desktop's OCR models with the same pipeline, so it reads the
game like the desktop (Google ML Kit was tried first: it misread the game's font, e.g. "INIIO", "Bxit").

**Screen sizes.** The bot works in 1440x2560 (9:16) reference coordinates. A 9:16 phone is scaled. Taller phones
(20:9…) are mapped in three bands: the top third anchored to the top of the screen, the bottom third to the
bottom, the middle to the center (`ScreenMap`). This is how the game's UI is expected to stretch; it has to be
checked on the first tall phone with a dump (below) and the bands adjusted if needed.

**Recovery.** There is no emulator to restart: after an error the bot brings the game to the front again and
goes on (the same error more than 3 times in a row → it stops with that error).

## Tests (on the PC, no phone)
```
cd phone/android && ./gradlew :bot:test     # engine: parity with the desktop bot + behaviour tests
cd phone && flutter test                     # UI logic
```
- `ParityTest`: every Kotlin parser on every screenshot in `tests/fixtures`, with the OCR boxes the desktop bot
  read, against what the Python parsers return (`bot/src/test/resources/parity.json`). After changing a Python
  parser or adding a fixture: `python phone/tools/export_parity.py`, then make the Kotlin match.
- `OcrParityTest`: the phone's OCR (`PaddleOcr`) on every fixture, then the parsers: same decisions as the
  desktop (its known, harmless differences are listed in the test).
- `DeviceOcrTest`: the OCR on a device reads like on the PC (`python phone/tools/device_ocr.py` records it;
  skipped without a recording).

## Diagnostics
With the phone connected over adb and the accessibility service on:
```
adb shell am broadcast -a com.diego.roguebot_phone.DUMP -n com.diego.roguebot_phone/.DumpReceiver
adb pull /sdcard/Android/data/com.diego.roguebot_phone/files/dumps/
```
saves the raw screen, the mapped 1440x2560 frame and its OCR (read only, never taps). The log is in
`files/bot.log` and failure screenshots in `files/debug/`. While the bot isn't running, the dump uses the
accessibility screenshot (black on MuMu Player; fine on phones).

## Build
```
cd phone && flutter build apk --release      # build/app/outputs/flutter-apk/app-release.apk
```
