"""Tkinter window: Run / Routines / Build / Settings, status, and a color-coded log."""

import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import replace
from tkinter import filedialog, ttk
from pathlib import Path
from typing import Callable

from roguebot import __version__, config, emulator, settings
from roguebot.build import PRESETS, Build
from roguebot.i18n import UI_LANGUAGES, tr
from roguebot.report import Report, render
from roguebot.request import BEATEN, LATEST, PENDING, STARS, RunRequest, build_request
from roguebot.screens import Mode
from roguebot.skills import DAMAGE_TYPES, MAGIC, PHYSICAL

log = logging.getLogger("roguebot")
ICON = Path(__file__).parent / "assets" / "icon.png"
CHANGELOG = Path(__file__).parent.parent / "CHANGELOG.md"  # the exe bundles it at its root
ICON_HEADER_SHRINK = 3  # 192 px icon -> 64 px in the header
LOG_VIEW_LINES = 2000   # lines kept in the window's log
DEBUG_DIR = Path("debug")

# Game purple and gold on a dark ground. Buttons are flat and padded (Tk has no corner radius).
_BG = "#161022"
_CARD = "#261838"
_TEXT = "#f4efe6"
_MUTED = "#b7adc8"
_PURPLE = "#7b4dff"
_GOLD = "#e4b54a"
_GREEN = "#3ddc97"
_RED = "#ff5d73"
_AMBER = "#ffb020"
_FIELD = "#120c1c"


class _QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        self.q.put(self.format(record))


def _font_family(root) -> str:
    have = set(tkfont.families(root))
    for name in ("Segoe UI", "Ubuntu", "DejaVu Sans", "Liberation Sans"):
        if name in have:
            return name
    return "TkDefaultFont"


class App:
    def __init__(self, run: Callable[[RunRequest], Report], lang: str | None = None,
                 stop: Callable[[], None] | None = None, settings_path: Path = settings.SETTINGS_PATH,
                 pause: Callable[[bool], None] | None = None):
        """run(request) does the whole job and returns a Report; it raises on failure.
        stop() asks a running job to end (it then raises from run).
        pause(True/False) holds the run at the next screenshot or tap, then continues the same run.
        Every option is saved to settings_path (on Start, language change and close) and restored here."""
        self.run = run
        self.stop = stop
        self.pause = pause
        self._stopping = False
        self._paused = False
        self._running = False
        self._seen_help = False
        self._run_started: float | None = None
        self._levels = self._wins = self._losses = 0
        self.settings_path = settings_path
        saved = settings.load(settings_path)
        lang = lang or (saved.get("lang") if saved.get("lang") in UI_LANGUAGES else "es")
        self.lang = lang
        self._preset_lock = False
        self.logs: queue.Queue = queue.Queue()
        self._status: tuple[str, dict, str] = ("idle", {}, "black")  # i18n key, args, color
        self._texts: list[tuple[ttk.Widget, str]] = []                 # widgets to retranslate
        self._help = None

        if sys.platform == "win32":  # own taskbar entry (and icon) instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("roguebot.RogueLegendBot")
        self.root = tk.Tk()
        self.colors = {"bg": _BG, "card": _CARD, "text": _TEXT, "muted": _MUTED, "purple": _PURPLE,
                       "gold": _GOLD, "green": _GREEN, "red": _RED, "amber": _AMBER}
        self.family = _font_family(self.root)
        self._apply_theme()
        self.icon = tk.PhotoImage(file=ICON)
        self.root.iconphoto(True, self.icon)  # title bar and taskbar
        self.root.geometry("980x900")
        self.root.minsize(820, 720)
        frame = ttk.Frame(self.root, padding=14)
        frame.pack(fill="both", expand=True)

        header = ttk.Frame(frame)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        self.header_icon = self.icon.subsample(ICON_HEADER_SHRINK)
        ttk.Label(header, image=self.header_icon).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        self.header_title = ttk.Label(header, style="Title.TLabel")
        self.header_title.grid(row=0, column=1, sticky="w")
        tools = ttk.Frame(header)
        tools.grid(row=0, column=2, sticky="e")
        self.help_button = ttk.Button(tools, text="?", width=3, command=self._show_help, style="Gold.TButton")
        self.help_button.pack(side="left", padx=(0, 8))
        self.changelog_toggle = ttk.Button(tools, command=self._toggle_changelog)
        self.changelog_toggle.pack(side="left")
        self.changelog = tk.Text(header, height=8, width=80, wrap="word", bg=_FIELD, fg=_TEXT,
                                 insertbackground=_GOLD, relief="flat", font=(self.family, 10))
        self.changelog.insert("1.0", CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else "")
        self.changelog.configure(state="disabled")
        self.changelog_shown = False
        # Kept for the requirements test. The window shows this from the ? button, not as a block.
        self.info = self._text(ttk.Label(header, justify="left", wraplength=860), "info")

        self._status_bar(frame).grid(row=1, column=0, sticky="ew", pady=(10, 8))

        self.notebook = ttk.Notebook(frame)
        self.notebook.grid(row=2, column=0, sticky="nsew")
        run_tab = ttk.Frame(self.notebook, padding=12)
        routines_tab = ttk.Frame(self.notebook, padding=12)
        build_tab = ttk.Frame(self.notebook, padding=12)
        settings_tab = ttk.Frame(self.notebook, padding=12)
        self._tabs = ((run_tab, "tab_run"), (routines_tab, "tab_routines"),
                      (build_tab, "tab_build"), (settings_tab, "tab_settings"))
        for tab, key in self._tabs:
            self.notebook.add(tab, text=key)
        self._run_tab(run_tab)
        self._routines_tab(routines_tab)
        self._build_section(build_tab).pack(fill="x")
        self._settings_tab(settings_tab)

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, sticky="ew", pady=(10, 6))
        buttons.columnconfigure((0, 1, 2), weight=1)
        self.start = ttk.Button(buttons, command=self._start, style="Start.TButton")
        self.start.grid(row=0, column=0, sticky="ew", padx=(0, 6), ipady=4)
        self.pause_button = ttk.Button(buttons, command=self._pause, style="Pause.TButton")
        self.pause_button.grid(row=0, column=1, sticky="ew", padx=6, ipady=4)
        self.stop_button = ttk.Button(buttons, command=self._stop, style="Stop.TButton")
        self.stop_button.grid(row=0, column=2, sticky="ew", padx=(6, 0), ipady=4)

        log_tools = ttk.Frame(frame)
        log_tools.grid(row=4, column=0, sticky="ew", pady=(0, 4))
        self._text(ttk.Button(log_tools, command=self._open_debug, style="Gold.TButton"), "open_debug").pack(side="left")
        self._text(ttk.Button(log_tools, command=self._copy_log), "copy_log").pack(side="left", padx=(8, 0))

        self.log_view = tk.Text(frame, height=14, width=80, state="disabled", bg=_FIELD, fg=_TEXT,
                                 insertbackground=_GOLD, relief="flat", font=(self.family, 10), padx=8, pady=6)
        self.log_view.tag_configure("info", foreground=_TEXT)
        self.log_view.tag_configure("error", foreground=_RED)
        self.log_view.tag_configure("win", foreground=_GREEN)
        self.log_view.tag_configure("w2", foreground="#c9a6ff")
        self.log_view.grid(row=5, column=0, sticky="nsew")
        frame.rowconfigure(5, weight=1)
        frame.columnconfigure(0, weight=1)

        handler = _QueueHandler(self.logs)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        log.addHandler(handler)
        self._restore_options(saved)
        if isinstance(saved.get("seen_help"), bool):
            self._seen_help = saved["seen_help"]
        self.set_language(lang)
        self.source.trace_add("write", lambda *_: self._refresh_actions())
        self.level.trace_add("write", lambda *_: self._refresh_actions())
        self._refresh_actions()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(500, self._tick)

    def _apply_theme(self) -> None:
        self.root.configure(bg=_BG)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        family = self.family
        style.configure(".", background=_BG, foreground=_TEXT, font=(family, 10))
        style.configure("TFrame", background=_BG)
        style.configure("TLabel", background=_BG, foreground=_TEXT, font=(family, 10))
        style.configure("Title.TLabel", background=_BG, foreground=_GOLD, font=(family, 16, "bold"))
        style.configure("Muted.TLabel", background=_BG, foreground=_MUTED, font=(family, 9))
        style.configure("Card.TLabel", background=_CARD, foreground=_TEXT)
        style.configure("TLabelframe", background=_CARD, foreground=_GOLD, bordercolor=_PURPLE)
        style.configure("TLabelframe.Label", background=_CARD, foreground=_GOLD, font=(family, 10, "bold"))
        style.configure("TRadiobutton", background=_BG, foreground=_TEXT, font=(family, 10))
        style.map("TRadiobutton", background=[("active", _BG)])
        style.configure("TCheckbutton", background=_BG, foreground=_TEXT, font=(family, 10))
        style.map("TCheckbutton", background=[("active", _BG)])
        style.configure("TNotebook", background=_BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=_CARD, foreground=_MUTED, padding=(16, 8),
                        font=(family, 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", _PURPLE)], foreground=[("selected", "#ffffff")])
        style.configure("TButton", background=_CARD, foreground=_TEXT, padding=(12, 8), font=(family, 10),
                        borderwidth=0)
        style.map("TButton", background=[("active", _PURPLE), ("disabled", "#2a2438")],
                  foreground=[("disabled", "#6e6880")])
        style.configure("Start.TButton", background=_GREEN, foreground="#062216", font=(family, 13, "bold"),
                        padding=(18, 12))
        style.map("Start.TButton", background=[("active", "#5ae0a4"), ("disabled", "#1d3d30")],
                  foreground=[("disabled", "#6e6880")])
        style.configure("Pause.TButton", background=_AMBER, foreground="#2a1c04", font=(family, 13, "bold"),
                        padding=(18, 12))
        style.map("Pause.TButton", background=[("active", "#ffc85a"), ("disabled", "#3a3018")],
                  foreground=[("disabled", "#6e6880")])
        style.configure("Stop.TButton", background=_RED, foreground="#2a0610", font=(family, 13, "bold"),
                        padding=(18, 12))
        style.map("Stop.TButton", background=[("active", "#ff8fa0"), ("disabled", "#3a1820")],
                  foreground=[("disabled", "#6e6880")])
        style.configure("Gold.TButton", background=_GOLD, foreground="#2a1c04", padding=(10, 6),
                        font=(family, 10, "bold"))
        style.map("Gold.TButton", background=[("active", "#f0cb78")])
        style.configure("TEntry", fieldbackground=_FIELD, foreground=_TEXT, insertcolor=_GOLD)
        style.configure("TCombobox", fieldbackground=_FIELD, foreground=_TEXT, background=_CARD,
                        arrowcolor=_GOLD)
        style.configure("TSpinbox", fieldbackground=_FIELD, foreground=_TEXT, background=_CARD, arrowcolor=_GOLD)
        style.configure("Status.TFrame", background=_CARD)

    def _status_bar(self, parent) -> ttk.Frame:
        bar = ttk.Frame(parent, style="Status.TFrame", padding=(10, 8))
        top = ttk.Frame(bar, style="Status.TFrame")
        top.pack(fill="x")
        self.dot = tk.Label(top, text="●", font=(self.family, 16), bg=_CARD, fg=_MUTED)
        self.dot.pack(side="left", padx=(0, 8))
        self.status = ttk.Label(top, style="Card.TLabel", font=(self.family, 12, "bold"))
        self.status.pack(side="left")
        self.elapsed = ttk.Label(top, style="Card.TLabel", text="00:00:00")
        self.elapsed.pack(side="right")
        task = ttk.Frame(bar, style="Status.TFrame")
        task.pack(fill="x", pady=(2, 0))
        self._text(ttk.Label(task, style="Card.TLabel"), "task_label").pack(side="left")
        self.task_value = ttk.Label(task, style="Card.TLabel", text="—")
        self.task_value.pack(side="left", padx=(6, 0))
        counts = ttk.Frame(bar, style="Status.TFrame")
        counts.pack(fill="x", pady=(2, 0))
        self._text(ttk.Label(counts, style="Card.TLabel"), "levels_cleared").pack(side="left")
        self.levels_value = ttk.Label(counts, style="Card.TLabel", text="0")
        self.levels_value.pack(side="left", padx=(4, 14))
        self._text(ttk.Label(counts, style="Card.TLabel"), "wins").pack(side="left")
        self.wins_value = ttk.Label(counts, style="Card.TLabel", text="0", foreground=_GREEN)
        self.wins_value.pack(side="left", padx=(4, 14))
        self._text(ttk.Label(counts, style="Card.TLabel"), "losses").pack(side="left")
        self.losses_value = ttk.Label(counts, style="Card.TLabel", text="0", foreground=_RED)
        self.losses_value.pack(side="left", padx=(4, 0))
        return bar

    def _run_tab(self, tab) -> None:
        self.mode = tk.StringVar(value=Mode.NORMAL.value)
        self._text(ttk.Label(tab), "mode").grid(row=0, column=0, sticky="w", pady=4)
        modes = ttk.Frame(tab)
        modes.grid(row=0, column=1, columnspan=2, sticky="w")
        self._text(ttk.Radiobutton(modes, variable=self.mode, value=Mode.NORMAL.value), "normal").pack(side="left", padx=(0, 12))
        self._text(ttk.Radiobutton(modes, variable=self.mode, value=Mode.ELITE.value), "elite").pack(side="left")

        self.elite_cost = tk.StringVar(value=str(config.ELITE_COST_DEFAULT))
        self._text(ttk.Label(tab, wraplength=900), "elite_cost").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(10, 2))
        cost = ttk.Frame(tab)
        cost.grid(row=2, column=0, columnspan=3, sticky="w")
        for value in config.ELITE_COSTS:
            ttk.Radiobutton(cost, text=str(value), variable=self.elite_cost, value=str(value)).pack(side="left", padx=(0, 12))

        self.source = tk.StringVar(value=LATEST)
        self._text(ttk.Label(tab), "level").grid(row=3, column=0, sticky="nw", pady=(10, 4))
        sources = ttk.Frame(tab)
        sources.grid(row=3, column=1, columnspan=2, sticky="w")
        self.level = tk.StringVar(value="1")
        for i, (value, key) in enumerate(((LATEST, "latest"), (BEATEN, "beaten"), (PENDING, "pending"), (STARS, "stars"))):
            self._text(ttk.Radiobutton(sources, variable=self.source, value=value, command=self._toggle_level),
                       key).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 18), pady=2)
        self.level_entry = ttk.Spinbox(sources, from_=1, to=999, width=5, textvariable=self.level, state="disabled")
        self.level_entry.grid(row=1, column=2, sticky="w")

        self.loop = tk.BooleanVar(value=False)
        self._check(tab, self.loop, "loop").grid(row=4, column=0, columnspan=3, sticky="w", pady=(12, 0))
        tab.columnconfigure(1, weight=1)

    def _routines_tab(self, tab) -> None:
        self.full = tk.BooleanVar(value=False)
        self._check(tab, self.full, "full").pack(anchor="w", pady=(0, 8), fill="x")
        self.ads = tk.BooleanVar(value=False)
        self._check(tab, self.ads, "ads").pack(anchor="w", pady=(0, 8), fill="x")
        self.skip_fights = tk.BooleanVar(value=False)
        self._check(tab, self.skip_fights, "skip_fights").pack(anchor="w", fill="x")

    def _settings_tab(self, tab) -> None:
        self._text(ttk.Label(tab), "language").grid(row=0, column=0, sticky="w", pady=4)
        self.ui_lang = tk.StringVar(value=UI_LANGUAGES[self.lang])
        picker = ttk.Combobox(tab, textvariable=self.ui_lang, values=list(UI_LANGUAGES.values()),
                              state="readonly", width=12)
        picker.grid(row=0, column=1, sticky="w")
        picker.bind("<<ComboboxSelected>>", lambda _: (self.set_language(
            next(k for k, v in UI_LANGUAGES.items() if v == self.ui_lang.get())), self._save_options()))

        self._text(ttk.Label(tab), "mumu_folder").grid(row=1, column=0, sticky="w", pady=(10, 4))
        folder = settings.load(self.settings_path).get("mumu_folder", "")
        self.mumu_folder = tk.StringVar(value=folder if emulator.tools(folder or "-") else str(emulator.find_install() or ""))
        folder_row = ttk.Frame(tab)
        folder_row.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Entry(folder_row, textvariable=self.mumu_folder, width=52).pack(side="left", fill="x", expand=True)
        self._text(ttk.Button(folder_row, command=self._browse), "browse").pack(side="left", padx=(8, 0))
        self.mumu_status = ttk.Label(tab)
        self.mumu_status.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.mumu_folder.trace_add("write", lambda *_: self._check_folder())
        tab.columnconfigure(1, weight=1)

    def _build_section(self, parent) -> ttk.LabelFrame:
        """Skill preferences: nature, damage type order (move up/down), support every N damage skills."""
        box = self._text(ttk.LabelFrame(parent, padding=8), "build_title")
        self.preset = tk.StringVar(value="custom")  # id: custom / shuriken / fire / ...
        self.preset_label = tk.StringVar()
        self._text(ttk.Label(box), "preset").grid(row=0, column=0, sticky="w")
        self.preset_box = ttk.Combobox(box, textvariable=self.preset_label, state="readonly", width=16)
        self.preset_box.grid(row=0, column=1, columnspan=2, sticky="w")
        self.preset_box.bind("<<ComboboxSelected>>", lambda _: self._on_preset())

        self.nature = tk.StringVar(value=PHYSICAL)
        self._text(ttk.Label(box), "build_nature").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._text(ttk.Radiobutton(box, variable=self.nature, value=PHYSICAL, command=self._mark_custom),
                   "physical").grid(row=1, column=1, sticky="w", pady=(6, 0))
        self._text(ttk.Radiobutton(box, variable=self.nature, value=MAGIC, command=self._mark_custom),
                   "magic").grid(row=1, column=2, sticky="w", pady=(6, 0))

        self._text(ttk.Label(box), "build_order").grid(row=2, column=0, sticky="nw", pady=(6, 0))
        self.damage_order = list(DAMAGE_TYPES)
        self.order_list = tk.Listbox(box, height=len(DAMAGE_TYPES), width=18, exportselection=False,
                                      bg=_FIELD, fg=_TEXT, selectbackground=_PURPLE, selectforeground="#ffffff",
                                      relief="flat", font=(self.family, 10), highlightthickness=0)
        self.order_list.grid(row=2, column=1, columnspan=2, sticky="w", pady=(6, 0))
        moves = ttk.Frame(box)
        moves.grid(row=2, column=3, sticky="nw", padx=6, pady=(6, 0))
        self._text(ttk.Button(moves, command=lambda: self._move(-1)), "move_up").pack(fill="x")
        self._text(ttk.Button(moves, command=lambda: self._move(1)), "move_down").pack(fill="x", pady=(4, 0))

        self.support = tk.BooleanVar(value=False)
        self.support_every = tk.StringVar(value="3")
        support = ttk.Frame(box)
        support.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self._text(ttk.Checkbutton(support, variable=self.support), "build_support").pack(side="left")
        ttk.Spinbox(support, from_=1, to=20, width=4, textvariable=self.support_every).pack(side="left", padx=4)
        self._text(ttk.Label(support), "build_support_after").pack(side="left")
        return box

    def _refresh_presets(self) -> None:
        names = ("custom",) + tuple(PRESETS)
        self._preset_ids = {tr(self.lang, "preset_" + name): name for name in names}
        self.preset_box.configure(values=list(self._preset_ids))
        current = self.preset.get() if self.preset.get() in names else "custom"
        self.preset_label.set(tr(self.lang, "preset_" + current))

    def _on_preset(self) -> None:
        self.preset.set(self._preset_ids.get(self.preset_label.get(), "custom"))
        self._apply_preset()

    def _refresh_order(self, selected: int | None = None) -> None:
        self.order_list.delete(0, "end")
        for i, damage_type in enumerate(self.damage_order, 1):
            self.order_list.insert("end", f"{i}. {tr(self.lang, 'type_' + damage_type)}")
        if selected is not None:
            self.order_list.selection_set(selected)

    def _move(self, delta: int) -> None:
        """Move the selected damage type up (-1) or down (+1) in the priority list."""
        sel = self.order_list.curselection()
        if not sel or not 0 <= sel[0] + delta < len(self.damage_order):
            return
        self._mark_custom()
        i, j = sel[0], sel[0] + delta
        self.damage_order[i], self.damage_order[j] = self.damage_order[j], self.damage_order[i]
        self._refresh_order(j)

    def _mark_custom(self) -> None:
        """A hand edit leaves the named preset. The preset's avoid list would no longer match."""
        if self._preset_lock or self.preset.get() == "custom":
            return
        self._preset_lock = True
        self.preset.set("custom")
        self.preset_label.set(tr(self.lang, "preset_custom"))
        self._preset_lock = False

    def _apply_preset(self) -> None:
        """Fill nature, type order and support from the named preset. Custom leaves them alone."""
        if self._preset_lock:
            return
        preset = PRESETS.get(self.preset.get())
        if preset is None:
            return
        self._preset_lock = True
        self.nature.set(preset.nature)
        rest = [damage_type for damage_type in DAMAGE_TYPES if damage_type not in preset.order]
        self.damage_order = list(preset.order) + rest
        self.support.set(preset.support_every is not None)
        if preset.support_every:
            self.support_every.set(str(preset.support_every))
        self._refresh_order()
        self._preset_lock = False

    def _support_every(self) -> int | None:
        every = self.support_every.get().strip()
        return int(every) if self.support.get() and every.isdigit() and int(every) > 0 else None

    def build(self) -> Build:
        support_every = self._support_every()
        preset = PRESETS.get(self.preset.get())
        if preset is not None:
            return replace(preset, support_every=support_every)
        return Build(self.nature.get(), tuple(self.damage_order), support_every)

    def options(self) -> dict:
        """Every user choice, as saved between sessions."""
        values = {"lang": self.lang, "mode": self.mode.get(), "source": self.source.get(), "level": self.level.get(),
                  "full": self.full.get(), "loop": self.loop.get(), "ads": self.ads.get(),
                  "elite_cost": int(self.elite_cost.get()) if self.elite_cost.get().isdigit() else config.ELITE_COST_DEFAULT,
                  "skip_fights": self.skip_fights.get(), "preset": self.preset.get(),
                  "nature": self.nature.get(), "damage_order": list(self.damage_order),
                  "support": self.support.get(), "support_every": self.support_every.get(),
                  "seen_help": self._seen_help}
        if emulator.tools(self.mumu_folder.get() or "-"):
            values["mumu_folder"] = self.mumu_folder.get()
        return values

    def _restore_options(self, saved: dict) -> None:
        """Last session's choices; anything missing or invalid keeps its default."""
        for var, key, choices in ((self.mode, "mode", {m.value for m in Mode}),
                                  (self.source, "source", {LATEST, BEATEN, PENDING, STARS}),
                                  (self.nature, "nature", {PHYSICAL, MAGIC})):
            if saved.get(key) in choices:
                var.set(saved[key])
        for var, key in ((self.full, "full"), (self.loop, "loop"), (self.ads, "ads"),
                         (self.support, "support"), (self.skip_fights, "skip_fights")):
            if isinstance(saved.get(key), bool):
                var.set(saved[key])
        for var, key in ((self.level, "level"), (self.support_every, "support_every")):
            if str(saved.get(key, "")).isdigit():
                var.set(str(saved[key]))
        if sorted(saved.get("damage_order") or []) == sorted(DAMAGE_TYPES):
            self.damage_order = list(saved["damage_order"])
        if saved.get("elite_cost") in config.ELITE_COSTS:
            self.elite_cost.set(str(saved["elite_cost"]))
        if saved.get("preset") == "custom" or saved.get("preset") in PRESETS:
            self.preset.set(saved["preset"])
        if isinstance(saved.get("seen_help"), bool):
            self._seen_help = saved["seen_help"]
        if self.preset.get() in PRESETS:
            self._apply_preset()
        self._toggle_level()

    def _save_options(self) -> None:
        try:
            settings.save(self.options(), self.settings_path)
        except OSError as e:  # e.g. a read-only folder: the bot still works, it just forgets the choices
            log.error("Could not save the settings: %s", e)

    def _close(self) -> None:
        self._save_options()
        self.root.destroy()

    def _check(self, parent, variable, key: str, wrap: int = 860):
        """tk checkbox: ttk has no wraplength, and these labels are a sentence long."""
        widget = tk.Checkbutton(parent, variable=variable, wraplength=wrap, anchor="w", justify="left",
                                bg=_BG, fg=_TEXT, activebackground=_BG, activeforeground=_TEXT,
                                selectcolor=_CARD, highlightthickness=0, font=(self.family, 10))
        return self._text(widget, key)

    def _text(self, widget, key: str):
        self._texts.append((widget, key))
        return widget

    def set_language(self, lang: str) -> None:
        self.lang = lang
        self.ui_lang.set(UI_LANGUAGES[lang])
        self.root.title(tr(lang, "title"))
        self.header_title.configure(text=f"{tr(lang, 'title')} v{__version__}")
        self._show_changelog_toggle()
        for widget, key in self._texts:
            widget.configure(text=tr(lang, key))
        for tab, key in self._tabs:
            self.notebook.tab(tab, text=tr(lang, key))
        sel = self.order_list.curselection()
        self._refresh_presets()
        self._refresh_order(sel[0] if sel else None)
        self._check_folder()
        self._paint_actions()
        self._show_status()

    def _toggle_changelog(self) -> None:
        self.changelog_shown = not self.changelog_shown
        if self.changelog_shown:
            self.changelog.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        else:
            self.changelog.grid_remove()
        self._show_changelog_toggle()

    def _show_changelog_toggle(self) -> None:
        arrow = "▾" if self.changelog_shown else "▸"
        self.changelog_toggle.configure(text=f"{arrow} {tr(self.lang, 'changelog')}")

    def _show_help(self) -> None:
        if self._help is not None and self._help.winfo_exists():
            self._help.lift()
            return
        win = tk.Toplevel(self.root)
        win.title(tr(self.lang, "help_title"))
        win.configure(bg=_BG)
        win.transient(self.root)
        text = tk.Text(win, height=16, width=78, wrap="word", bg=_FIELD, fg=_TEXT, relief="flat",
                       font=(self.family, 10), padx=12, pady=10)
        text.insert("1.0", tr(self.lang, "info"))
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        ttk.Button(win, text=tr(self.lang, "close"), command=lambda: self._dismiss_help(win)).pack(pady=(0, 12))
        self._help = win
        win.protocol("WM_DELETE_WINDOW", lambda: self._dismiss_help(win))

    def _dismiss_help(self, win) -> None:
        self._seen_help = True
        self._save_options()
        win.destroy()

    def mainloop(self) -> None:
        self.root.after(200, self._drain_logs)
        if not self._seen_help:
            self.root.after(300, self._show_help)
        self.root.mainloop()

    def _browse(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.mumu_folder.get() or None)
        if folder:
            self.mumu_folder.set(folder)

    def _check_folder(self) -> None:
        ok = emulator.tools(self.mumu_folder.get() or "-") is not None
        self.mumu_status.configure(text=tr(self.lang, "mumu_ok" if ok else "mumu_bad"),
                                   foreground=_GREEN if ok else _RED)

    def _toggle_level(self) -> None:
        self.level_entry.configure(state="normal" if self.source.get() == STARS else "disabled")

    def _form_ok(self) -> bool:
        if self.source.get() != STARS:
            return True
        level = self.level.get().strip()
        return level.isdigit() and int(level) > 0

    def _paint_actions(self) -> None:
        self.start.configure(text=f"▶  {tr(self.lang, 'start')}")
        if self._paused:
            self.pause_button.configure(text=f"▶  {tr(self.lang, 'resume')}")
        else:
            self.pause_button.configure(text=f"❚❚  {tr(self.lang, 'pause')}")
        self.stop_button.configure(text=f"■  {tr(self.lang, 'stop')}")

    def _refresh_actions(self) -> None:
        if self._running:
            self.start.configure(state="disabled")
            self.pause_button.configure(state="normal")
            self.stop_button.configure(state="disabled" if self._stopping or not self.stop else "normal")
        else:
            self.start.configure(state="normal" if self._form_ok() else "disabled")
            self.pause_button.configure(state="disabled")
            self.stop_button.configure(state="disabled")
        self._paint_dot()

    def _paint_dot(self) -> None:
        if self._paused:
            color = _AMBER
        elif self._running:
            color = _GREEN
        elif self._status[0] in ("error", "stopped"):
            color = _RED
        else:
            color = _MUTED
        self.dot.configure(fg=color)

    def _refresh_counters(self) -> None:
        self.levels_value.configure(text=str(self._levels))
        self.wins_value.configure(text=str(self._wins))
        self.losses_value.configure(text=str(self._losses))

    def _tick(self) -> None:
        if self._running and self._run_started is not None:
            elapsed = int(time.monotonic() - self._run_started)
        else:
            elapsed = 0
        self.elapsed.configure(text=f"{elapsed // 3600:02d}:{(elapsed % 3600) // 60:02d}:{elapsed % 60:02d}")
        self.root.after(500, self._tick)

    def _set_status(self, key: str, color: str, **kwargs) -> None:
        self._status = (key, kwargs, color)
        self._show_status()

    def _show_status(self) -> None:
        key, kwargs, color = self._status
        if key == "report":
            text = render(kwargs["report"], self.lang)
        else:
            text = tr(self.lang, key, **kwargs)
        ink = self.colors["text"] if color == "black" else color
        self.status.configure(text=text, foreground=ink)
        self._paint_dot()

    def _start(self) -> None:
        self._save_options()
        try:
            cost = int(self.elite_cost.get()) if self.elite_cost.get().isdigit() else config.ELITE_COST_DEFAULT
            request = build_request(self.mode.get(), self.source.get(), self.level.get(),
                                    self.full.get(), self.build(), self.loop.get(), self.mumu_folder.get(),
                                    self.ads.get(), elite_cost=cost, skip_fights=self.skip_fights.get())
        except ValueError as e:
            self._set_status(str(e), "red")
            self._refresh_actions()
            return
        self._running = True
        self._stopping = False
        self._paused = False
        self._run_started = time.monotonic()
        self._levels = self._wins = self._losses = 0
        self._refresh_counters()
        self.task_value.configure(text="—")
        self._paint_actions()
        if self.pause:
            self.pause(False)
        self._refresh_actions()
        self._set_status("running", _GREEN)
        threading.Thread(target=self._worker, args=(request,), daemon=True).start()

    def _worker(self, request: RunRequest) -> None:
        try:
            status = ("report", {"report": self.run(request)}, "green")
        except Exception as e:  # any failure, including the bot not being able to continue the level
            if self._stopping:
                log.info("Stopped by the user")
                status = ("stopped", {}, "darkorange")
            else:
                log.exception("Run failed")
                msg = tr(self.lang, e.key, **e.values) if isinstance(e, emulator.EmulatorError) else str(e)
                status = ("error", {"msg": msg}, "red")
        self.root.after(0, self._finish, status)

    def _finish(self, status: tuple[str, dict, str]) -> None:
        key, kwargs, color = status
        self._running = False
        self._paused = False
        self._set_status(key, color, **kwargs)
        self._paint_actions()
        self._refresh_actions()

    def _set_pause_label(self) -> None:
        self._paint_actions()

    def _pause(self) -> None:
        """Hold the run at the next screenshot or tap. Resume continues it; Stop still ends it."""
        self._paused = not self._paused
        if self.pause:
            self.pause(self._paused)
        self._set_pause_label()
        if self._paused:
            log.info("Paused: no taps until Resume (Stop still ends the run)")
            self._set_status("paused", "darkorange")
        else:
            log.info("Resumed")
            self._set_status("running", _GREEN)
        self._refresh_actions()

    def _stop(self) -> None:
        self._stopping = True
        self._refresh_actions()
        self._set_status("stopping", "darkorange")
        self.stop()

    def _drain_logs(self) -> None:
        while not self.logs.empty():
            self._append(self.logs.get())
        self.root.after(200, self._drain_logs)

    def _log_tag(self, line: str) -> str:
        body = re.sub(r"^\d{2}:\d{2}:\d{2}\s+", "", line).lower()
        if "level finished:" in body and "victory" in body:
            return "win"
        if any(word in body for word in ("error", "traceback", "stuck on", "level finished: defeat")):
            return "error"
        if body.startswith("w2 ") or " w2 " in f" {body}":
            return "w2"
        return "info"

    def _note_progress(self, line: str) -> None:
        body = re.sub(r"^\d{2}:\d{2}:\d{2}\s+", "", line)
        low = body.lower()
        found = re.search(r"level finished:\s*(victory|defeat)\s*\(run\s+(\d+)\)", low)
        if found:
            self._levels = int(found.group(2))
            if found.group(1) == "victory":
                self._wins += 1
            else:
                self._losses += 1
            self._refresh_counters()
        if body:
            self.task_value.configure(text=body[:110])

    def _append(self, line: str) -> None:
        self.log_view.configure(state="normal")
        self.log_view.insert("end", line + "\n", self._log_tag(line))
        self.log_view.delete("1.0", f"end-{LOG_VIEW_LINES}l")  # days of running grew it ~19 MB (debug/bot.log keeps all)
        self.log_view.see("end")
        self.log_view.configure(state="disabled")
        self._note_progress(line)

    def _open_debug(self) -> None:
        DEBUG_DIR.mkdir(exist_ok=True)
        path = str(DEBUG_DIR.resolve())
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606  the user's own debug folder
            return
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, path])  # noqa: S603

    def _copy_log(self) -> None:
        text = self.log_view.get("1.0", "end-1c")
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except tk.TclError:
            return
        self.task_value.configure(text=tr(self.lang, "copied"))
