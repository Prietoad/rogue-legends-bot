"""What the user asked to run, validated from the UI form values."""

from dataclasses import dataclass

from roguebot.build import Build
from roguebot.screens import Mode

LATEST = "latest"
STARS = "stars"
BEATEN = "beaten"
PENDING = "pending"  # beaten levels that still miss stars, then the last beaten one


@dataclass(frozen=True)
class RunRequest:
    mode: Mode
    level: int | None  # None = last unlocked level (lobby INICIO/LISTO)
    repeat: bool = False  # replay the same level until energy runs out
    full: bool = False    # full routine first: modes, guild raid (then levels, always repeating)
    build: Build = Build()  # skill preferences for level skill picks and shops
    last_beaten: bool = False  # the level before the last unlocked one (from Desafío de Estrellas)
    pending_stars: bool = False  # levels with missing stars first (star rewards), then the last beaten
    mumu_folder: str = ""  # MuMu Player installation folder (started and Rogue Legend opened on Start)
    loop: bool = False    # full routine forever: modes -> levels until out of energy -> wait for energy -> again


def build_request(mode: str, source: str, level: str, repeat: bool = False, full: bool = False,
                  build: Build = Build(), loop: bool = False, mumu_folder: str = "") -> RunRequest:
    """Validate the form values. Raises ValueError with a user-facing message."""
    full = full or loop  # looping repeats the full routine
    repeat = repeat or full  # the full routine ends by clearing levels until out of energy
    common = dict(repeat=repeat, full=full, build=build, mumu_folder=mumu_folder, loop=loop)
    if source in (LATEST, BEATEN, PENDING):
        return RunRequest(Mode(mode), None, last_beaten=source in (BEATEN, PENDING),
                          pending_stars=source == PENDING, **common)
    if not level.strip().isdigit() or int(level) < 1:
        raise ValueError("bad_level")  # i18n key
    return RunRequest(Mode(mode), int(level), **common)
