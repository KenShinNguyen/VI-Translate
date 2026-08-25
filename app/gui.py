#!/usr/bin/env python3
"""Desktop front end for the PDF translation runner.

Google mode only: a packaged executable has no agent and no API key, so the
handoff engine is reachable from the skill rather than from here.
"""

from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD

APP_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from scripts.translate_pdf import (  # noqa: E402
    DEFAULT_TARGET_LANGUAGE,
    TARGET_LANGUAGES,
    TranslationError,
    translate_pdf,
)

FONT_DIRECTORY = APP_ROOT / "app" / "fonts"
ASSET_DIRECTORY = APP_ROOT / "app" / "assets"
UI_FONT = "Be Vietnam Pro"
MONO_FONT = "JetBrains Mono"
FALLBACK_UI_FONT = "Segoe UI"
FALLBACK_MONO_FONT = "Consolas"

LANGUAGE_NAMES = {
    "af": "Afrikaans", "ca": "Català", "cs": "Čeština", "cy": "Cymraeg",
    "da": "Dansk", "de": "Deutsch", "en": "English", "es": "Español",
    "et": "Eesti", "eu": "Euskara", "fi": "Suomi", "fr": "Français",
    "ga": "Gaeilge", "gl": "Galego", "hr": "Hrvatski", "hu": "Magyar",
    "id": "Bahasa Indonesia", "is": "Íslenska", "it": "Italiano",
    "lt": "Lietuvių", "lv": "Latviešu", "ms": "Bahasa Melayu", "mt": "Malti",
    "nl": "Nederlands", "no": "Norsk", "pl": "Polski", "pt": "Português",
    "ro": "Română", "sk": "Slovenčina", "sl": "Slovenščina", "sq": "Shqip",
    "sv": "Svenska", "sw": "Kiswahili", "tl": "Tagalog", "tr": "Türkçe",
    "vi": "Tiếng Việt",
}

STATUS_MARKS = {"queued": "•", "running": "▶", "done": "✓", "partial": "!", "failed": "✕", "skipped": "–"}
STATUS_COLORS = {
    "queued": ("gray50", "gray60"),
    "running": ("#1f6feb", "#58a6ff"),
    "done": ("#1a7f37", "#3fb950"),
    "partial": ("#9a6700", "#d29922"),
    "failed": ("#cf222e", "#f85149"),
    "skipped": ("gray50", "gray60"),
}


def ensure_writable_streams() -> None:
    """Give the app real streams, because a windowed build has none.

    PyInstaller sets sys.stdout and sys.stderr to None when console=False, and
    the core's tqdm progress bar writes to stderr, so translating raised
    AttributeError: 'NoneType' object has no attribute 'write'.
    """
    for name in ("stdout", "stderr", "__stdout__", "__stderr__"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def use_bundled_assets() -> None:
    """Point the engine at the packaged model and font so no download is needed."""
    model = ASSET_DIRECTORY / "doclayout.onnx"
    font = ASSET_DIRECTORY / "GoNotoKurrent-Regular.ttf"
    if model.is_file():
        os.environ.setdefault("PDF_TRANSLATE_MODEL", str(model))
    if font.is_file():
        os.environ.setdefault("NOTO_FONT_PATH", str(font))


def load_bundled_fonts() -> bool:
    """Register the bundled fonts for this process only, so no install is needed.

    tkinter can only use fonts the OS knows about, and AddFontResourceEx with
    FR_PRIVATE is the Windows way to add one without touching the system.
    """
    if sys.platform != "win32" or not FONT_DIRECTORY.is_dir():
        return False
    private = 0x10
    loaded = 0
    try:
        for font in FONT_DIRECTORY.glob("*.ttf"):
            loaded += ctypes.windll.gdi32.AddFontResourceExW(str(font), private, 0)
    except OSError:
        return False
    return loaded > 0


def _is_pdf(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".pdf"


def collect_pdfs(paths: list[Path]) -> list[Path]:
    """Expand dropped or picked paths into a deduplicated list of PDF files."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            # Not glob("*.pdf"): that is case-sensitive on POSIX and would miss .PDF.
            found.extend(sorted(p for p in path.iterdir() if _is_pdf(p)))
        elif path.suffix.lower() == ".pdf":
            found.append(path)
    unique: dict[Path, None] = {}
    for path in found:
        unique.setdefault(path.resolve(), None)
    return list(unique)


class App(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self) -> None:
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)

        has_fonts = load_bundled_fonts()
        self.ui_font = UI_FONT if has_fonts else FALLBACK_UI_FONT
        self.mono_font = MONO_FONT if has_fonts else FALLBACK_MONO_FONT

        self.title("PDF Translate")
        self.geometry("620x620")
        self.minsize(520, 560)

        self.files: list[Path] = []
        self.rows: dict[Path, ctk.CTkLabel] = {}
        self.states: dict[Path, str] = {}
        self.events: queue.Queue[tuple] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.batch_done = 0
        self.batch_total = 0

        self._build()
        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self._on_drop)
        self.after(100, self._drain_events)

    # -- layout ------------------------------------------------------------
    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            self,
            text="PDF Translate",
            font=ctk.CTkFont(self.ui_font, size=24, weight="bold"),
        ).grid(row=0, column=0, padx=24, pady=(24, 4), sticky="w")

        self.dropzone = ctk.CTkFrame(self, corner_radius=12, border_width=2, height=150)
        self.dropzone.grid(row=1, column=0, padx=24, pady=8, sticky="ew")
        self.dropzone.grid_propagate(False)
        self.dropzone.grid_columnconfigure(0, weight=1)
        self.dropzone.grid_rowconfigure(0, weight=1)
        self.dropzone.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            self.dropzone,
            text="Kéo thả file PDF hoặc thư mục vào đây",
            font=ctk.CTkFont(self.ui_font, size=14),
        ).grid(row=0, column=0, pady=(24, 8), sticky="s")

        buttons = ctk.CTkFrame(self.dropzone, fg_color="transparent")
        buttons.grid(row=1, column=0)
        ctk.CTkButton(
            buttons, text="Chọn file", width=130, command=self._pick_files,
            font=ctk.CTkFont(self.ui_font, size=13),
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            buttons, text="Chọn thư mục", width=130, command=self._pick_directory,
            font=ctk.CTkFont(self.ui_font, size=13),
        ).pack(side="left", padx=6)

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=2, column=0, padx=24, pady=8, sticky="ew")
        controls.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            controls, text="Dịch sang", font=ctk.CTkFont(self.ui_font, size=13)
        ).grid(row=0, column=0, padx=(0, 10))

        names = sorted(LANGUAGE_NAMES[code] for code in TARGET_LANGUAGES if code in LANGUAGE_NAMES)
        self.language = ctk.CTkOptionMenu(
            controls, values=names, width=190, font=ctk.CTkFont(self.ui_font, size=13)
        )
        self.language.set(LANGUAGE_NAMES[DEFAULT_TARGET_LANGUAGE])
        self.language.grid(row=0, column=1, sticky="w")

        self.translate_button = ctk.CTkButton(
            controls, text="Dịch", width=110, command=self._start,
            font=ctk.CTkFont(self.ui_font, size=13, weight="bold"),
        )
        self.translate_button.grid(row=0, column=2, padx=(10, 0))

        self.overwrite = ctk.CTkCheckBox(
            controls, text="Ghi đè file đã dịch trước đó",
            font=ctk.CTkFont(self.ui_font, size=12),
        )
        self.overwrite.grid(row=1, column=0, columnspan=3, pady=(12, 0), sticky="w")

        self.list = ctk.CTkScrollableFrame(self, corner_radius=12, label_text="Hàng đợi")
        self.list.grid(row=3, column=0, padx=24, pady=8, sticky="nsew")
        self.list.grid_columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0)
        self.progress.grid(row=4, column=0, padx=24, pady=(4, 4), sticky="ew")

        self.status = ctk.CTkLabel(
            self, text="Chưa có file nào", font=ctk.CTkFont(self.ui_font, size=12)
        )
        self.status.grid(row=5, column=0, padx=24, sticky="w")

        ctk.CTkLabel(
            self,
            text="Bản app dùng Google Translate. Cần chất lượng cao hơn thì dùng skill pdf-translate trong Claude Code.",
            font=ctk.CTkFont(self.ui_font, size=11),
            text_color=("gray45", "gray60"),
            wraplength=560,
            justify="left",
        ).grid(row=6, column=0, padx=24, pady=(4, 20), sticky="w")

    # -- input -------------------------------------------------------------
    def _on_drop(self, event) -> None:
        # splitlist handles the brace quoting tkdnd uses for paths with spaces.
        self._add([Path(item) for item in self.tk.splitlist(event.data)])

    def _pick_files(self) -> None:
        chosen = ctk.filedialog.askopenfilenames(filetypes=[("PDF", "*.pdf")])
        self._add([Path(item) for item in chosen])

    def _pick_directory(self) -> None:
        chosen = ctk.filedialog.askdirectory()
        if chosen:
            self._add([Path(chosen)])

    def _add(self, paths: list[Path]) -> None:
        for path in collect_pdfs(paths):
            if path in self.rows:
                continue
            self.files.append(path)
            row = ctk.CTkLabel(
                self.list,
                text=f"{STATUS_MARKS['queued']}  {path.name}",
                font=ctk.CTkFont(self.mono_font, size=12),
                text_color=STATUS_COLORS["queued"],
                anchor="w",
                justify="left",
                wraplength=520,
            )
            row.grid(sticky="ew", padx=6, pady=2)
            self.rows[path] = row
            self.states[path] = "queued"
        self.status.configure(text=f"{len(self.files)} file trong hàng đợi")

    # -- work --------------------------------------------------------------
    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        pending = [path for path in self.files if self.states[path] in ("queued", "failed")]
        if not pending:
            self.status.configure(text="Không còn file nào cần dịch")
            return

        names = {name: code for code, name in LANGUAGE_NAMES.items()}
        language = names[self.language.get()]
        overwrite = bool(self.overwrite.get())

        self.translate_button.configure(state="disabled", text="Đang dịch…")
        self.progress.set(0)
        self.batch_done, self.batch_total = 0, len(pending)
        self.worker = threading.Thread(
            target=self._run, args=(pending, language, overwrite), daemon=True
        )
        self.worker.start()

    def _run(self, files: list[Path], language: str, overwrite: bool) -> None:
        for index, path in enumerate(files, 1):
            self.events.put(("status", path, "running", ""))
            destination = path.parent / "translated"

            def report(done: int, total: int, _p: Path = path) -> None:
                self.events.put(("page", _p, done, total))

            try:
                result = translate_pdf(
                    path,
                    destination,
                    target_language=language,
                    overwrite=overwrite,
                    on_progress=report,
                )
                detail = (
                    f"{result.untranslated} đoạn chưa dịch được"
                    if result.untranslated
                    else str(result.path)
                )
                state = "partial" if result.untranslated else "done"
                self.events.put(("status", path, state, detail))
            except TranslationError as error:
                # One unreadable or already-translated file must not stop the batch.
                state = "skipped" if "already exists" in str(error) else "failed"
                if state == "failed":
                    self._log_failure(destination, path, error)
                self.events.put(("status", path, state, str(error)))
            except Exception as error:  # noqa: BLE001 - keep the queue moving
                self._log_failure(destination, path, error)
                self.events.put(("status", path, "failed", f"{type(error).__name__}: {error}"))
            self.events.put(("progress", index / len(files), index, len(files)))
        self.events.put(("finished",))

    @staticmethod
    def _log_failure(destination: Path, source: Path, error: BaseException) -> None:
        """Append the full traceback to a log file the user can send back.

        The queue row only has space for one line, which is never enough to
        diagnose a failure on someone else's document.
        """
        try:
            destination.mkdir(parents=True, exist_ok=True)
            with (destination / "pdf-translate.log").open("a", encoding="utf-8") as log:
                log.write(f"\n{'=' * 70}\n{datetime.now():%Y-%m-%d %H:%M:%S}  {source}\n")
                traceback.print_exception(type(error), error, error.__traceback__, file=log)
        except OSError:
            pass  # a failure to log must never mask the failure being logged

    def _drain_events(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event[0] == "status":
                _, path, state, detail = event
                self.states[path] = state
                row = self.rows[path]
                text = f"{STATUS_MARKS[state]}  {path.name}"
                if state in ("failed", "skipped", "partial") and detail:
                    text += f"\n     {detail.splitlines()[0]}"
                row.configure(text=text, text_color=STATUS_COLORS[state])
            elif event[0] == "page":
                # Per-page progress inside the file being translated. A textbook
                # is hundreds of pages, so file-level progress alone looks stuck.
                _, path, done, total = event
                if self.states.get(path) == "running" and total:
                    self.rows[path].configure(
                        text=f"{STATUS_MARKS['running']}  {path.name}   trang {done}/{total}"
                    )
                    self.progress.set((self.batch_done + done / total) / max(self.batch_total, 1))
                    self.status.configure(
                        text=f"Đang dịch {path.name}   trang {done}/{total}"
                    )
            elif event[0] == "progress":
                _, fraction, done_files, total_files = event
                self.batch_done, self.batch_total = done_files, total_files
                self.progress.set(fraction)
            elif event[0] == "finished":
                self.translate_button.configure(state="normal", text="Dịch")
                counts = {}
                for state in self.states.values():
                    counts[state] = counts.get(state, 0) + 1
                summary = f"Xong {counts.get('done', 0)}/{len(self.files)} file"
                if counts.get("partial"):
                    summary += f", {counts['partial']} file dịch thiếu"
                if counts.get("failed"):
                    summary += f", {counts['failed']} file lỗi"
                self.status.configure(text=summary)
        self.after(100, self._drain_events)


def main() -> None:
    ensure_writable_streams()
    use_bundled_assets()
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = App()
    # Windows passes anything dropped on the executable icon as arguments.
    if sys.argv[1:]:
        app._add([Path(argument) for argument in sys.argv[1:]])
    app.mainloop()


if __name__ == "__main__":
    main()
