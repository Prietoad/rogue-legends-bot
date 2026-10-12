"""Minimal tkinter window: pick mode and level, press Start, see status and log. Spanish or English."""

import logging
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path
from typing import Callable

from roguebot import __version__, emulator, settings
from roguebot.build import Build
from roguebot.i18n import UI_LANGUAGES, tr
from roguebot.report import Report, render
from roguebot.request import BEATEN, LATEST, PENDING, STARS, RunRequest, build_request
from roguebot.screens import Mode
from roguebot.skills import DAMAGE_TYPES, MAGIC, PHYSICAL

log = logging.getLogger("roguebot")
ICON = Path(__file__).parent / "assets" / "icon.png"
CHANGELOG = Path(__file__).parent.parent / "CHANGELOG.md"  # the exe bundles it at its root
ICON_HEADER_SHRINK = 3  # 192 px icon -> 64 px in the header


class _QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        self.q.put(self.format(record))


class App:
    def __init__(self, run: Callable[[RunRequest], Report], lang: str = "es",
                 stop: Callable[[], None] | None = None):
        """run(request) does the whole job and returns a Report; it raises on failure.
        stop() asks a running job to end (it then raises from run)."""
        self.run = run
        self.stop = stop
        self._stopping = False
        self.lang = lang
        self.logs: queue.Queue = queue.Queue()
        self._status: tuple[str, dict, str] = ("idle", {}, "black")  # i18n key, args, color
        self._texts: list[tuple[ttk.Widget, str]] = []                 # widgets to retranslate

        if sys.platform == "win32":  # own taskbar entry (and icon) instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("roguebot.RogueLegendBot")
        self.root = tk.Tk()
        self.icon = tk.PhotoImage(file=ICON)
        self.root.iconphoto(True, self.icon)  # title bar and taskbar
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        header = ttk.Frame(frame)
        header.grid(row=0, column=0, columnspan=4, sticky="ew")
        header.columnconfigure(1, weight=1)
        self.header_icon = self.icon.subsample(ICON_HEADER_SHRINK)
        ttk.Label(header, image=self.header_icon).grid(row=0, column=0, rowspan=2, padx=(0, 10))
        self.header_title = ttk.Label(header, font=("Segoe UI", 14, "bold"))
        self.header_title.grid(row=0, column=1, sticky="w")
        self.changelog_toggle = ttk.Button(header, command=self._toggle_changelog)
        self.changelog_toggle.grid(row=1, column=1, sticky="w")
        self.changelog = tk.Text(header, height=10, width=80, wrap="word")
        self.changelog.insert("1.0", CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else "")
        self.changelog.configure(state="disabled")
        self.changelog_shown = False
        top = ttk.Frame(header)
        top.grid(row=0, column=2, sticky="ne")
        self._text(ttk.Label(top), "language").pack(side="left", padx=(0, 6))
        self.ui_lang = tk.StringVar(value=UI_LANGUAGES[lang])
        picker = ttk.Combobox(top, textvariable=self.ui_lang, values=list(UI_LANGUAGES.values()),
                              state="readonly", width=10)
        picker.pack(side="left")
        picker.bind("<<ComboboxSelected>>", lambda _: self.set_language(
            next(k for k, v in UI_LANGUAGES.items() if v == self.ui_lang.get())))

        info = self._text(ttk.LabelFrame(frame, padding=8), "info_title")
        info.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 10))
        self.info = self._text(ttk.Label(info, justify="left"), "info")
        self.info.pack(anchor="w")
        folder_row = ttk.Frame(info)
        folder_row.pack(fill="x", pady=(6, 0))
        self._text(ttk.Label(folder_row), "mumu_folder").pack(side="left", padx=(0, 6))
        saved = settings.load().get("mumu_folder", "")
        self.mumu_folder = tk.StringVar(value=saved if emulator.tools(saved or "-") else str(emulator.find_install() or ""))
        ttk.Entry(folder_row, textvariable=self.mumu_folder, width=45).pack(side="left", fill="x", expand=True)
        self._text(ttk.Button(folder_row, command=self._browse), "browse").pack(side="left", padx=(6, 0))
        self.mumu_status = ttk.Label(info)
        self.mumu_status.pack(anchor="w")
        self.mumu_folder.trace_add("write", lambda *_: self._check_folder())

        self.mode = tk.StringVar(value=Mode.NORMAL.value)
        self._text(ttk.Label(frame), "mode").grid(row=2, column=0, sticky="w")
        self._text(ttk.Radiobutton(frame, variable=self.mode, value=Mode.NORMAL.value), "normal").grid(row=2, column=1, sticky="w")
        self._text(ttk.Radiobutton(frame, variable=self.mode, value=Mode.ELITE.value), "elite").grid(row=2, column=2, sticky="w")

        self.source = tk.StringVar(value=LATEST)
        self._text(ttk.Label(frame), "level").grid(row=3, column=0, sticky="w")
        sources = ttk.Frame(frame)
        sources.grid(row=3, column=1, columnspan=3, sticky="w")
        for value, key in ((LATEST, "latest"), (BEATEN, "beaten"), (PENDING, "pending"), (STARS, "stars")):
            self._text(ttk.Radiobutton(sources, variable=self.source, value=value, command=self._toggle_level),
                       key).pack(side="left", padx=(0, 8))
        self.level = tk.StringVar(value="1")
        self.level_entry = ttk.Spinbox(sources, from_=1, to=999, width=5, textvariable=self.level, state="disabled")
        self.level_entry.pack(side="left")

        self.repeat = tk.BooleanVar(value=False)
        self._text(ttk.Checkbutton(frame, variable=self.repeat), "repeat").grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(4, 0))

        self.full = tk.BooleanVar(value=False)
        self._text(ttk.Checkbutton(frame, variable=self.full), "full").grid(
            row=5, column=0, columnspan=4, sticky="w", pady=(4, 0))

        self.loop = tk.BooleanVar(value=False)
        self._text(ttk.Checkbutton(frame, variable=self.loop), "loop").grid(
            row=6, column=0, columnspan=4, sticky="w", pady=(4, 0))

        self._build_section(frame).grid(row=7, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=8, column=0, columnspan=4, sticky="ew", pady=8)
        buttons.columnconfigure((0, 1), weight=1)
        self.start = self._text(ttk.Button(buttons, command=self._start), "start")
        self.start.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.stop_button = self._text(ttk.Button(buttons, command=self._stop, state="disabled"), "stop")
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.status = ttk.Label(frame, font=("Segoe UI", 11, "bold"))
        self.status.grid(row=9, column=0, columnspan=4, sticky="w", pady=(0, 6))

        self.log_view = tk.Text(frame, height=12, width=80, state="disabled")
        self.log_view.grid(row=10, column=0, columnspan=4, sticky="nsew")
        frame.rowconfigure(10, weight=1)
        frame.columnconfigure(3, weight=1)

        handler = _QueueHandler(self.logs)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        log.addHandler(handler)
        self.set_language(lang)

    def _build_section(self, parent) -> ttk.LabelFrame:
        """Skill preferences: nature, damage type order (move up/down), support every N damage skills."""
        box = self._text(ttk.LabelFrame(parent, padding=8), "build_title")
        self.nature = tk.StringVar(value=PHYSICAL)
        self._text(ttk.Label(box), "build_nature").grid(row=0, column=0, sticky="w")
        self._text(ttk.Radiobutton(box, variable=self.nature, value=PHYSICAL), "physical").grid(row=0, column=1, sticky="w")
        self._text(ttk.Radiobutton(box, variable=self.nature, value=MAGIC), "magic").grid(row=0, column=2, sticky="w")

        self._text(ttk.Label(box), "build_order").grid(row=1, column=0, sticky="nw", pady=(6, 0))
        self.damage_order = list(DAMAGE_TYPES)
        self.order_list = tk.Listbox(box, height=len(DAMAGE_TYPES), width=18, exportselection=False)
        self.order_list.grid(row=1, column=1, columnspan=2, sticky="w", pady=(6, 0))
        moves = ttk.Frame(box)
        moves.grid(row=1, column=3, sticky="nw", padx=6, pady=(6, 0))
        self._text(ttk.Button(moves, command=lambda: self._move(-1)), "move_up").pack(fill="x")
        self._text(ttk.Button(moves, command=lambda: self._move(1)), "move_down").pack(fill="x", pady=(4, 0))

        self.support = tk.BooleanVar(value=False)
        self.support_every = tk.StringVar(value="3")
        support = ttk.Frame(box)
        support.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self._text(ttk.Checkbutton(support, variable=self.support), "build_support").pack(side="left")
        ttk.Spinbox(support, from_=1, to=20, width=4, textvariable=self.support_every).pack(side="left", padx=4)
        self._text(ttk.Label(support), "build_support_after").pack(side="left")
        return box

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
        i, j = sel[0], sel[0] + delta
        self.damage_order[i], self.damage_order[j] = self.damage_order[j], self.damage_order[i]
        self._refresh_order(j)

    def build(self) -> Build:
        every = self.support_every.get().strip()
        support_every = int(every) if self.support.get() and every.isdigit() and int(every) > 0 else None
        return Build(self.nature.get(), tuple(self.damage_order), support_every)

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
        sel = self.order_list.curselection()
        self._refresh_order(sel[0] if sel else None)
        self._check_folder()
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

    def mainloop(self) -> None:
        self.root.after(200, self._drain_logs)
        self.root.mainloop()

    def _browse(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.mumu_folder.get() or None)
        if folder:
            self.mumu_folder.set(folder)

    def _check_folder(self) -> None:
        ok = emulator.tools(self.mumu_folder.get() or "-") is not None
        self.mumu_status.configure(text=tr(self.lang, "mumu_ok" if ok else "mumu_bad"),
                                   foreground="green" if ok else "red")

    def _toggle_level(self) -> None:
        self.level_entry.configure(state="normal" if self.source.get() == STARS else "disabled")

    def _set_status(self, key: str, color: str, **kwargs) -> None:
        self._status = (key, kwargs, color)
        self._show_status()

    def _show_status(self) -> None:
        key, kwargs, color = self._status
        if key == "report":
            text = render(kwargs["report"], self.lang)
        else:
            text = tr(self.lang, key, **kwargs)
        self.status.configure(text=text, foreground=color)

    def _start(self) -> None:
        try:
            request = build_request(self.mode.get(), self.source.get(), self.level.get(), self.repeat.get(),
                                    self.full.get(), self.build(), self.loop.get(), self.mumu_folder.get())
        except ValueError as e:
            self._set_status(str(e), "red")
            return
        if emulator.tools(request.mumu_folder or "-"):
            settings.save({"mumu_folder": request.mumu_folder})
        self.start.configure(state="disabled")
        self._stopping = False
        if self.stop:
            self.stop_button.configure(state="normal")
        self._set_status("running", "black")
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
        self._set_status(key, color, **kwargs)
        self.start.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def _stop(self) -> None:
        self._stopping = True
        self.stop_button.configure(state="disabled")
        self._set_status("stopping", "darkorange")
        self.stop()

    def _drain_logs(self) -> None:
        while not self.logs.empty():
            self._append(self.logs.get())
        self.root.after(200, self._drain_logs)

    def _append(self, line: str) -> None:
        self.log_view.configure(state="normal")
        self.log_view.insert("end", line + "\n")
        self.log_view.see("end")
        self.log_view.configure(state="disabled")
