"""What a run produced, and how the UI words it in each language."""

from dataclasses import dataclass, field

from roguebot.i18n import tr
from roguebot.screens import LevelScreen

RESULT_KEY = {LevelScreen.VICTORY: "victory", LevelScreen.DEFEAT: "defeat"}


@dataclass
class Report:
    results: list[LevelScreen] = field(default_factory=list)
    repeat: bool = False
    dry_run: bool = False
    parts: list[tuple[str, str]] = field(default_factory=list)  # full routine: (part, status), see routine.PARTS


def render(report: Report, lang: str) -> str:
    if report.dry_run:
        return tr(lang, "dry_run")
    if not report.repeat:
        return tr(lang, "level_finished", result=tr(lang, RESULT_KEY[report.results[0]]))
    wins = report.results.count(LevelScreen.VICTORY)
    levels = tr(lang, "out_of_energy", runs=len(report.results), wins=wins, losses=len(report.results) - wins)
    if not report.parts:
        return levels
    parts = ", ".join(f"{tr(lang, 'part_' + part)}: {tr(lang, 'status_' + status)}" for part, status in report.parts)
    return parts + "\n" + levels
