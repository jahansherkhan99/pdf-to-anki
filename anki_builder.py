"""
anki_builder.py — Assemble a genanki Deck from raw card dicts and write an
.apkg file ready to import into Anki.

Two note models are defined:
  • PDF-to-Anki Basic  — standard front/back card with clean medical styling
  • PDF-to-Anki Cloze  — cloze-deletion card with highlighted blanks
"""

from __future__ import annotations

import random
from typing import Any, Dict, List

import genanki

from config import ANKI_BASIC_MODEL_ID, ANKI_CLOZE_MODEL_ID

# ---------------------------------------------------------------------------
# Shared CSS
# ---------------------------------------------------------------------------

_CSS = """\
.card {
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 17px;
    line-height: 1.65;
    color: #1a1a2e;
    background: #f4f6fb;
    padding: 24px 28px;
    max-width: 680px;
    margin: 0 auto;
    border-radius: 8px;
}
.front {
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 4px;
}
.back {
    color: #ffffff;
}
hr#answer {
    border: none;
    border-top: 2px solid #c9d6f0;
    margin: 14px 0;
}
.extra {
    display: block;
    margin-top: 14px;
    padding: 8px 12px;
    background: #e8edf8;
    border-left: 4px solid #4a7fcb;
    border-radius: 4px;
    font-size: 14px;
    color: #3a3a60;
    font-style: italic;
}
.cloze {
    font-weight: bold;
    color: #1565c0;
    text-decoration: underline dotted;
}
"""

# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------

def _basic_model() -> genanki.Model:
    return genanki.Model(
        ANKI_BASIC_MODEL_ID,
        "PDF-to-Anki Basic",
        fields=[
            {"name": "Front"},
            {"name": "Back"},
        ],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "<div class='front'>{{Front}}</div>",
                "afmt": (
                    "<div class='front'>{{Front}}</div>"
                    "<hr id=answer>"
                    "<div class='back'>{{Back}}</div>"
                ),
            }
        ],
        css=_CSS,
    )


def _cloze_model() -> genanki.Model:
    return genanki.Model(
        ANKI_CLOZE_MODEL_ID,
        "PDF-to-Anki Cloze",
        fields=[
            {"name": "Text"},
            {"name": "Extra"},
        ],
        templates=[
            {
                "name": "Cloze",
                "qfmt": "{{cloze:Text}}",
                "afmt": "{{cloze:Text}}<span class='extra'>{{Extra}}</span>",
            }
        ],
        model_type=genanki.Model.CLOZE,
        css=_CSS,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_deck(
    cards: List[Dict[str, Any]],
    deck_name: str,
    output_path: str,
) -> int:
    """
    Build an Anki package (.apkg) from *cards* and write it to *output_path*.

    Returns the number of notes successfully added to the deck.
    """
    deck_id = random.randrange(1 << 30, 1 << 31)
    deck = genanki.Deck(deck_id, deck_name)

    basic_model = _basic_model()
    cloze_model = _cloze_model()

    added = 0
    skipped = 0

    for card in cards:
        card_type = card.get("type", "").lower().strip()

        try:
            if card_type == "basic":
                front = str(card.get("front", "")).strip()
                back = str(card.get("back", "")).strip()
                if not front or not back:
                    skipped += 1
                    continue
                # Preserve line breaks as HTML
                back_html = back.replace("\n", "<br>")
                note = genanki.Note(
                    model=basic_model,
                    fields=[front, back_html],
                )
                deck.add_note(note)
                added += 1

            elif card_type == "cloze":
                text = str(card.get("text", "")).strip()
                extra = str(card.get("extra", "")).strip()
                # Validate that at least one cloze deletion is present
                if not text or "{{c" not in text:
                    skipped += 1
                    continue
                note = genanki.Note(
                    model=cloze_model,
                    fields=[text, extra],
                )
                deck.add_note(note)
                added += 1

            else:
                skipped += 1

        except Exception:
            skipped += 1

    package = genanki.Package(deck)
    package.write_to_file(output_path)

    if skipped:
        print(f"  (Skipped {skipped} malformed or unrecognised cards)")

    return added
