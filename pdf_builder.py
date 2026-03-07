"""
pdf_builder.py — Export vignette questions + answer key to a clean PDF.

Layout:
  Page 1+  : Numbered questions (stem, lead-in, A–E choices)
  Final sec.: Answer Key — correct answer, full explanation, distractor notes
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from fpdf import FPDF

# ---------------------------------------------------------------------------
# Unicode font paths (macOS system fonts with full medical symbol support)
# ---------------------------------------------------------------------------

_FONT_DIR = "/System/Library/Fonts/Supplemental"
_FONT_REGULAR = f"{_FONT_DIR}/Arial.ttf"
_FONT_BOLD    = f"{_FONT_DIR}/Arial Bold.ttf"
_FONT_ITALIC  = f"{_FONT_DIR}/Arial Italic.ttf"
_FONT_BOLDITA = f"{_FONT_DIR}/Arial Bold Italic.ttf"
_FONT_UNICODE = f"{_FONT_DIR}/Arial Unicode.ttf"   # fallback for exotic chars

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

_NAVY   = (21,  101, 192)   # header / accent
_BLACK  = (26,  26,  46)    # body text
_GREEN  = (27,  94,  32)    # correct answer
_RED    = (183, 28,  28)    # wrong answers in key
_GREY   = (100, 100, 120)   # sub-labels
_BGPAGE = (250, 252, 255)   # page background


# ---------------------------------------------------------------------------
# PDF class
# ---------------------------------------------------------------------------

class _MedPDF(FPDF):
    def __init__(self, title: str):
        super().__init__()
        self._title = title
        self.set_auto_page_break(auto=True, margin=20)
        # Register Unicode-aware Arial variants
        self.add_font("Arial",  style="",   fname=_FONT_REGULAR)
        self.add_font("Arial",  style="B",  fname=_FONT_BOLD)
        self.add_font("Arial",  style="I",  fname=_FONT_ITALIC)
        self.add_font("Arial",  style="BI", fname=_FONT_BOLDITA)

    # ── Header ──────────────────────────────────────────────────────────────
    def header(self):
        self.set_fill_color(*_NAVY)
        self.rect(0, 0, 210, 14, "F")          # 14 mm tall blue bar
        self.set_font("Arial", "B", 8)
        self.set_text_color(255, 255, 255)
        self.set_xy(0, 3)
        self.cell(0, 8, f"  {self._title}", align="L")
        # CRITICAL: always reset Y to below the header so content on any page
        # (including pages created by mid-question auto-breaks) starts in the
        # white area, never on top of the blue bar.
        self.set_y(20)

    # ── Footer ──────────────────────────────────────────────────────────────
    def footer(self):
        self.set_y(-12)
        self.set_font("Arial", "", 8)
        self.set_text_color(*_GREY)
        self.cell(0, 8, f"Page {self.page_no()}  |  Generated {date.today()}", align="C")

    # ── Helpers ──────────────────────────────────────────────────────────────
    def _body_text(self, text: str, indent: float = 0):
        self.set_x(14 + indent)
        self.set_font("Arial", "", 10.5)
        self.set_text_color(*_BLACK)
        self.multi_cell(
            w=182 - indent,
            h=5.5,
            text=str(text),
            align="J",
        )

    def _small_label(self, text: str):
        self.set_x(14)
        self.set_font("Arial", "I", 8.5)
        self.set_text_color(*_GREY)
        self.cell(0, 5, text)
        self.ln(5)

    def _section_bar(self, text: str):
        """Full-width coloured section divider."""
        self.ln(4)
        self.set_fill_color(*_NAVY)
        self.set_text_color(255, 255, 255)
        self.set_font("Arial", "B", 11)
        self.set_x(0)
        self.cell(210, 9, f"  {text}", fill=True)
        self.ln(9)

    def _divider(self):
        self.set_draw_color(*_NAVY)
        self.set_line_width(0.3)
        self.line(14, self.get_y(), 196, self.get_y())
        self.ln(3)


# ---------------------------------------------------------------------------
# Builder function
# ---------------------------------------------------------------------------

def _choice_label(letter: str, text: str, is_correct: bool, in_key: bool) -> str:
    return f"({letter})  {text}"


def build_pdf(
    questions: List[Dict[str, Any]],
    deck_name: str,
    output_path: str,
) -> int:
    """
    Build a PDF with all vignette questions and a full answer key.
    Returns the number of questions written.
    """
    pdf = _MedPDF(title=deck_name)
    pdf.set_margins(14, 20, 14)   # top=20 mm matches header() set_y(20)

    # ── Cover / title block ──────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_fill_color(*_NAVY)
    pdf.rect(0, 0, 210, 60, "F")
    pdf.set_y(18)
    pdf.set_font("Arial", "B", 22)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 12, deck_name, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 8, "USMLE Step 1-Style Practice Questions", align="C")
    pdf.ln(7)
    pdf.set_font("Arial", "", 10)
    pdf.set_text_color(197, 216, 255)
    pdf.cell(0, 6, f"{len(questions)} Questions  |  Generated {date.today()}", align="C")

    pdf.set_y(72)
    pdf.set_text_color(*_BLACK)
    pdf.set_font("Arial", "I", 9.5)
    pdf.set_x(14)
    pdf.multi_cell(
        182, 5,
        "Instructions: For each question, select the single best answer. "
        "An answer key with full explanations begins after the final question.",
        align="J",
    )
    pdf.ln(4)
    pdf._divider()

    # ── Questions ─────────────────────────────────────────────────────────────
    pdf._section_bar("QUESTIONS")

    written = 0
    for idx, q in enumerate(questions, start=1):
        stem    = str(q.get("stem", "")).strip()
        lead_in = str(q.get("lead_in", "")).strip()
        choices = q.get("choices", {})
        correct = str(q.get("correct", "")).strip().upper()

        if not stem or not choices or not correct:
            continue

        # If fewer than 50 mm remain on the page, start a fresh page so the
        # question number is never stranded alone at the bottom.
        if pdf.get_y() > pdf.h - pdf.b_margin - 50:
            pdf.add_page()

        # Question number
        pdf.ln(2)
        pdf.set_x(14)
        pdf.set_font("Arial", "B", 11)
        pdf.set_text_color(*_NAVY)
        pdf.cell(0, 6, f"Question {idx}", ln=True)
        pdf.ln(1)

        # Stem
        pdf._body_text(stem)
        pdf.ln(2)

        # Lead-in
        pdf.set_x(14)
        pdf.set_font("Arial", "BI", 10.5)
        pdf.set_text_color(*_BLACK)
        pdf.multi_cell(182, 5.5, lead_in, align="L")
        pdf.ln(2)

        # Choices
        for letter in ["A", "B", "C", "D", "E"]:
            text = str(choices.get(letter, "")).strip()
            if not text:
                continue
            pdf.set_x(20)
            pdf.set_font("Arial", "", 10.5)
            pdf.set_text_color(*_BLACK)
            pdf.multi_cell(176, 5.5, f"({letter})  {text}", align="L")
            pdf.ln(0.5)

        pdf.ln(3)
        pdf._divider()
        written += 1

    # ── Answer Key ────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf._section_bar("ANSWER KEY")

    for idx, q in enumerate(questions, start=1):
        correct  = str(q.get("correct", "")).strip().upper()
        choices  = q.get("choices", {})
        expl     = str(q.get("explanation", "")).strip()
        dist_exp = q.get("distractor_explanations", {})
        concept  = str(q.get("concept", "")).strip()

        if not correct or not choices:
            continue

        correct_text = str(choices.get(correct, "")).strip()

        if pdf.get_y() > pdf.h - pdf.b_margin - 50:
            pdf.add_page()

        pdf.ln(2)
        # Question number + correct answer
        pdf.set_x(14)
        pdf.set_font("Arial", "B", 11)
        pdf.set_text_color(*_NAVY)
        pdf.cell(30, 6, f"Question {idx}")
        pdf.set_font("Arial", "B", 11)
        pdf.set_text_color(*_GREEN)
        pdf.cell(0, 6, f"Correct: ({correct})  {correct_text}", ln=True)
        pdf.ln(1)

        # Concept tag
        if concept:
            pdf._small_label(f"Concept tested: {concept}")

        # Explanation
        pdf._body_text(expl)
        pdf.ln(2)

        # Distractor explanations
        has_dist = any(
            str(dist_exp.get(l, "")).strip()
            for l in ["A", "B", "C", "D", "E"]
            if l != correct
        )
        if has_dist:
            pdf.set_x(14)
            pdf.set_font("Arial", "B", 9.5)
            pdf.set_text_color(*_GREY)
            pdf.cell(0, 5, "Why not the others:", ln=True)
            for letter in ["A", "B", "C", "D", "E"]:
                if letter == correct:
                    continue
                why = str(dist_exp.get(letter, "")).strip()
                if not why:
                    continue
                pdf.set_x(20)
                pdf.set_font("Arial", "B", 9.5)
                pdf.set_text_color(*_RED)
                pdf.cell(10, 5, f"({letter})")
                pdf.set_font("Arial", "", 9.5)
                pdf.set_text_color(*_BLACK)
                pdf.multi_cell(166, 5, why, align="L")
                pdf.ln(0.5)

        pdf.ln(3)
        pdf._divider()

    pdf.output(output_path)
    return written
