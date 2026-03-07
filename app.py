#!/usr/bin/env python3
"""
app.py — Desktop GUI for PDF / PPTX → Anki deck + Step 1 question PDF.

Drag-and-drop a PDF or PPTX onto the window (or click to browse).
Choose a mode:
  • Flashcards only   → <name>.apkg saved to ~/Downloads
  • Vignette PDF only → <name>_questions.pdf saved to ~/Downloads
  • Both              → both files saved to ~/Downloads

Run:
    python app.py
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except ImportError:
    _HAS_DND = False

# ---------------------------------------------------------------------------
# Colours / layout constants
# ---------------------------------------------------------------------------

BG         = "#f0f4f8"
ACCENT     = "#1565c0"
ACCENT_HVR = "#1976d2"
DROP_BG    = "#e8f0fe"
DROP_BDR   = "#4a7fcb"
TEXT_DARK  = "#1a1a2e"
TEXT_MID   = "#555577"
SUCCESS    = "#2e7d32"
FONT_TITLE = ("Helvetica Neue", 22, "bold")
FONT_BODY  = ("Helvetica Neue", 13)
FONT_SMALL = ("Helvetica Neue", 11)
FONT_MONO  = ("Menlo", 11)

CONFIG_PATH = Path.home() / ".config" / "pdf_to_anki" / "config.json"

# Mode constants
MODE_CARDS    = "Flashcards"
MODE_VIGNETTE = "Vignette PDF"
MODE_BOTH     = "Both"

# ---------------------------------------------------------------------------
# Persist API key between sessions
# ---------------------------------------------------------------------------

def _load_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    try:
        data = json.loads(CONFIG_PATH.read_text())
        return data.get("api_key", "")
    except Exception:
        return ""


def _save_api_key(key: str) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps({"api_key": key}))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Thread-safe log queue → text widget bridge
# ---------------------------------------------------------------------------

class _QueueWriter:
    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, text: str) -> None:
        if text:
            self._q.put(text)

    def flush(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Path parsing for tkinterdnd2
# ---------------------------------------------------------------------------

def _parse_drop(data: str) -> str:
    data = data.strip()
    if data.startswith("{"):
        end = data.find("}")
        data = data[1:end] if end != -1 else data[1:]
    else:
        data = data.split()[0]
    return data


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class App:
    SUPPORTED = {".pdf", ".pptx", ".ppt"}

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PDF → Anki")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        self._selected_file: Path | None = None
        self._processing = False
        self._log_q: queue.Queue = queue.Queue()
        self._mode_var = tk.StringVar(value=MODE_BOTH)

        self._build_ui()
        self._poll_log()

    # ------------------------------------------------------------------ UI --

    def _build_ui(self):
        root = self.root

        # ── Title bar ──────────────────────────────────────────────────────
        title_frame = tk.Frame(root, bg=ACCENT)
        title_frame.pack(fill="x")
        tk.Label(
            title_frame, text="PDF → Anki",
            font=FONT_TITLE, fg="white", bg=ACCENT, pady=16,
        ).pack()
        tk.Label(
            title_frame, text="Medical Card Generator",
            font=FONT_SMALL, fg="#c5d8ff", bg=ACCENT, pady=0,
        ).pack()
        tk.Frame(title_frame, bg=ACCENT, height=14).pack()

        # ── Drop zone ──────────────────────────────────────────────────────
        outer = tk.Frame(root, bg=BG)
        outer.pack(fill="x", padx=24, pady=(20, 0))

        self._drop_frame = tk.Frame(
            outer, bg=DROP_BG, bd=2, relief="solid",
            highlightbackground=DROP_BDR, highlightthickness=2,
        )
        self._drop_frame.pack(fill="x", ipady=22)

        self._drop_icon = tk.Label(
            self._drop_frame, text="⬇", font=("Helvetica Neue", 34),
            bg=DROP_BG, fg=DROP_BDR,
        )
        self._drop_icon.pack(pady=(8, 2))

        self._drop_label = tk.Label(
            self._drop_frame, text="Drop your PDF or PPTX here",
            font=("Helvetica Neue", 15, "bold"), bg=DROP_BG, fg=TEXT_DARK,
        )
        self._drop_label.pack()

        self._drop_sub = tk.Label(
            self._drop_frame, text="or",
            font=FONT_SMALL, bg=DROP_BG, fg=TEXT_MID,
        )
        self._drop_sub.pack(pady=2)

        browse_btn = tk.Button(
            self._drop_frame, text="Browse for file",
            font=FONT_SMALL, bg=ACCENT, fg="white",
            activebackground=ACCENT_HVR, activeforeground="white",
            relief="flat", cursor="hand2", padx=14, pady=6,
            command=self._browse,
        )
        browse_btn.pack(pady=(0, 8))

        if _HAS_DND:
            for widget in (self._drop_frame, self._drop_icon,
                           self._drop_label, self._drop_sub):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<DropEnter>>", self._on_enter)
                widget.dnd_bind("<<DropLeave>>", self._on_leave)
                widget.dnd_bind("<<Drop>>",      self._on_drop)

        # ── Settings ───────────────────────────────────────────────────────
        settings = tk.Frame(root, bg=BG)
        settings.pack(fill="x", padx=24, pady=(14, 0))

        # Deck / file name
        tk.Label(settings, text="Name", font=FONT_SMALL,
                 bg=BG, fg=TEXT_MID).grid(row=0, column=0, sticky="w")
        self._deck_var = tk.StringVar(value="Medical Lecture")
        tk.Entry(
            settings, textvariable=self._deck_var,
            font=FONT_BODY, width=36, relief="solid", bd=1,
        ).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        # API key
        tk.Label(settings, text="API key", font=FONT_SMALL,
                 bg=BG, fg=TEXT_MID).grid(row=1, column=0, sticky="w", pady=(8, 0))
        key_frame = tk.Frame(settings, bg=BG)
        key_frame.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        self._key_var = tk.StringVar(value=_load_api_key())
        self._key_entry = tk.Entry(
            key_frame, textvariable=self._key_var,
            font=FONT_BODY, width=33, relief="solid", bd=1, show="•",
        )
        self._key_entry.pack(side="left")

        self._show_key = tk.BooleanVar(value=False)
        tk.Checkbutton(
            key_frame, text="Show", variable=self._show_key,
            font=FONT_SMALL, bg=BG, fg=TEXT_MID, activebackground=BG,
            command=self._toggle_key_vis,
        ).pack(side="left", padx=(6, 0))

        settings.columnconfigure(1, weight=1)

        # ── Mode selector ──────────────────────────────────────────────────
        mode_frame = tk.Frame(root, bg=BG)
        mode_frame.pack(fill="x", padx=24, pady=(12, 0))

        tk.Label(mode_frame, text="Output", font=FONT_SMALL,
                 bg=BG, fg=TEXT_MID).pack(side="left")

        for mode in (MODE_CARDS, MODE_VIGNETTE, MODE_BOTH):
            tk.Radiobutton(
                mode_frame, text=mode, variable=self._mode_var, value=mode,
                font=FONT_SMALL, bg=BG, fg=TEXT_DARK,
                activebackground=BG, selectcolor=BG,
                command=self._update_btn_label,
            ).pack(side="left", padx=(10, 0))

        # ── Generate button ────────────────────────────────────────────────
        self._gen_btn = tk.Button(
            root,
            text=self._btn_label(),
            font=("Helvetica Neue", 14, "bold"),
            bg="#b0bec5", fg="white",
            activebackground=ACCENT_HVR, activeforeground="white",
            relief="flat", cursor="arrow",
            padx=20, pady=10,
            state="disabled",
            command=self._start_generation,
        )
        self._gen_btn.pack(pady=(12, 0))

        # ── Log area ───────────────────────────────────────────────────────
        log_frame = tk.Frame(root, bg=BG)
        log_frame.pack(fill="both", expand=True, padx=24, pady=(12, 0))

        tk.Label(log_frame, text="Progress", font=FONT_SMALL,
                 bg=BG, fg=TEXT_MID).pack(anchor="w")

        self._log = scrolledtext.ScrolledText(
            log_frame, font=FONT_MONO,
            bg="#1e2030", fg="#c0caf5",
            insertbackground="white", relief="flat", bd=0,
            height=10, state="disabled", wrap="word",
        )
        self._log.pack(fill="both", expand=True)

        # ── Status bar ─────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Ready — drop a file to begin")
        tk.Label(
            root, textvariable=self._status_var,
            font=FONT_SMALL, bg="#dce6f0", fg=TEXT_MID,
            anchor="w", pady=6, padx=14,
        ).pack(fill="x", pady=(10, 0))

    # ---------------------------------------------------------------- DnD --

    def _on_enter(self, event):
        self._drop_frame.configure(bg="#d0e4ff")
        for w in (self._drop_icon, self._drop_label, self._drop_sub):
            w.configure(bg="#d0e4ff")

    def _on_leave(self, event):
        self._drop_frame.configure(bg=DROP_BG)
        for w in (self._drop_icon, self._drop_label, self._drop_sub):
            w.configure(bg=DROP_BG)

    def _on_drop(self, event):
        self._on_leave(event)
        self._set_file(Path(_parse_drop(event.data)))

    # ------------------------------------------------------------ File I/O --

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select PDF or PPTX",
            filetypes=[
                ("Supported files", "*.pdf *.pptx *.ppt"),
                ("PDF files", "*.pdf"),
                ("PowerPoint files", "*.pptx *.ppt"),
            ],
        )
        if path:
            self._set_file(Path(path))

    def _set_file(self, path: Path):
        if path.suffix.lower() not in self.SUPPORTED:
            messagebox.showerror(
                "Unsupported file",
                f"'{path.suffix}' is not supported.\nUse a .pdf or .pptx file.",
            )
            return
        self._selected_file = path
        if self._deck_var.get() in ("", "Medical Lecture"):
            self._deck_var.set(path.stem)
        self._drop_label.configure(text=f"  {path.name}  ", fg=SUCCESS)
        self._drop_icon.configure(text="✓", fg=SUCCESS)
        self._drop_sub.configure(text="file selected")
        self._enable_gen()
        self._status_var.set(f"File: {path.name}  |  Ready to generate")

    def _enable_gen(self):
        self._gen_btn.configure(state="normal", bg=ACCENT, cursor="hand2")

    def _disable_gen(self):
        self._gen_btn.configure(state="disabled", bg="#b0bec5", cursor="arrow")

    # --------------------------------------------------------- Mode / btn --

    def _btn_label(self) -> str:
        mode = self._mode_var.get()
        if mode == MODE_CARDS:
            return "Generate Anki Deck"
        if mode == MODE_VIGNETTE:
            return "Generate Question PDF"
        return "Generate Deck + Question PDF"

    def _update_btn_label(self):
        if not self._processing:
            self._gen_btn.configure(text=self._btn_label())

    # ------------------------------------------------------------ API key --

    def _toggle_key_vis(self):
        self._key_entry.configure(show="" if self._show_key.get() else "•")

    # --------------------------------------------------------------- Log --

    def _log_write(self, text: str):
        self._log.configure(state="normal")
        self._log.insert("end", text)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _log_clear(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _poll_log(self):
        try:
            while True:
                self._log_write(self._log_q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(80, self._poll_log)

    # ---------------------------------------------------------- Generation --

    def _start_generation(self):
        if self._processing:
            return
        key = self._key_var.get().strip()
        if not key:
            messagebox.showerror("API key missing",
                                 "Please enter your Anthropic API key.")
            return
        if self._selected_file is None:
            messagebox.showerror("No file",
                                 "Please drop or browse for a file first.")
            return

        _save_api_key(key)
        self._processing = True
        self._disable_gen()
        self._log_clear()
        self._status_var.set("Processing… please wait")
        self._gen_btn.configure(text="Processing…")

        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        import anthropic
        from extractor import chunk_pages, extract
        from card_generator import generate_all_cards
        from anki_builder import build_deck
        from vignette_generator import generate_all_questions
        from pdf_builder import build_pdf
        from config import MAX_CHUNK_WORDS, MAX_VIGNETTE_CHUNK_WORDS

        input_path = self._selected_file
        deck_name  = self._deck_var.get().strip() or input_path.stem
        api_key    = self._key_var.get().strip()
        mode       = self._mode_var.get()
        dl         = Path.home() / "Downloads"

        anki_path = dl / (input_path.stem + ".apkg")
        pdf_path  = dl / (input_path.stem + "_questions.pdf")

        old_stdout = sys.stdout
        sys.stdout = _QueueWriter(self._log_q)

        success = False
        out_files: list[Path] = []

        try:
            self._log_q.put(f"{'='*46}\n")
            self._log_q.put(f"  File : {input_path.name}\n")
            self._log_q.put(f"  Name : {deck_name}\n")
            self._log_q.put(f"  Mode : {mode}\n")
            self._log_q.put(f"{'='*46}\n\n")

            # ── Extract ──────────────────────────────────────────────────
            self._log_q.put("[1] Extracting text...\n")
            pages = extract(str(input_path))
            if not pages:
                raise RuntimeError(
                    "No text found. The file may be a scanned (image-only) PDF."
                )
            unit = "pages" if input_path.suffix.lower() == ".pdf" else "slides"
            self._log_q.put(f"  {len(pages)} {unit} extracted.\n\n")

            # ── Chunk (two sizes: larger for cards, smaller for vignettes) ──
            self._log_q.put("[2] Chunking content...\n")
            card_chunks = chunk_pages(pages, max_words=MAX_CHUNK_WORDS)
            vignette_chunks = chunk_pages(pages, max_words=MAX_VIGNETTE_CHUNK_WORDS)
            self._log_q.put(
                f"  {len(card_chunks)} flashcard chunk(s), "
                f"{len(vignette_chunks)} vignette chunk(s).\n\n"
            )

            client = anthropic.Anthropic(api_key=api_key)

            # ── Flashcards ───────────────────────────────────────────────
            if mode in (MODE_CARDS, MODE_BOTH):
                self._log_q.put("[3] Generating Anki flashcards...\n")
                cards = generate_all_cards(client, card_chunks)
                if not cards:
                    raise RuntimeError("No flashcards were generated.")
                cloze_n = sum(1 for c in cards if c.get("type") == "cloze")
                basic_n = sum(1 for c in cards if c.get("type") == "basic")
                self._log_q.put(f"\n  {len(cards)} cards total\n")
                self._log_q.put(f"    Cloze  : {cloze_n}\n")
                self._log_q.put(f"    Basic  : {basic_n}\n\n")

                self._log_q.put("  Building .apkg...\n")
                added = build_deck(cards, deck_name, str(anki_path))
                self._log_q.put(f"  {added} cards written → {anki_path.name}\n\n")
                out_files.append(anki_path)

            # ── Vignette questions ────────────────────────────────────────
            if mode in (MODE_VIGNETTE, MODE_BOTH):
                self._log_q.put("[4] Generating Step 1 vignette questions...\n")
                questions = generate_all_questions(client, vignette_chunks)
                if not questions:
                    raise RuntimeError("No vignette questions were generated.")
                self._log_q.put(f"\n  {len(questions)} questions generated.\n\n")

                self._log_q.put("  Building question PDF...\n")
                written = build_pdf(questions, deck_name, str(pdf_path))
                self._log_q.put(f"  {written} questions written → {pdf_path.name}\n\n")
                out_files.append(pdf_path)

            self._log_q.put(f"{'='*46}\n")
            self._log_q.put("  Done!\n")
            for f in out_files:
                self._log_q.put(f"  → {f}\n")
            self._log_q.put(f"{'='*46}\n")
            success = True

        except anthropic.AuthenticationError:
            self._log_q.put("\nERROR: Invalid API key.\n")
        except anthropic.APIConnectionError as e:
            self._log_q.put(f"\nERROR: Could not reach Anthropic API.\n{e}\n")
        except Exception as e:
            self._log_q.put(f"\nERROR: {e}\n")
        finally:
            sys.stdout = old_stdout

        self.root.after(0, self._on_done, success, out_files)

    def _on_done(self, success: bool, out_files: list):
        self._processing = False
        self._gen_btn.configure(text=self._btn_label())
        self._enable_gen()

        if success:
            names = "\n".join(str(f) for f in out_files)
            self._status_var.set(
                "Saved to Downloads: " + ",  ".join(f.name for f in out_files)
            )
            messagebox.showinfo(
                "Done!",
                f"Files saved to ~/Downloads:\n\n{names}\n\n"
                + ("Open Anki → File → Import to load the deck."
                   if any(str(f).endswith(".apkg") for f in out_files) else ""),
            )
        else:
            self._status_var.set("Failed — see log for details")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()

    w, h = 580, 720
    root.geometry(f"{w}x{h}")
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
