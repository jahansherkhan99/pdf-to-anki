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
# Shared CSS  — AnKing Overhaul style
# ---------------------------------------------------------------------------

_CSS = """\
/* ~~ AnKing Overhaul style (adapted for PDF-to-Anki) ~~ */

.timer { display: block; }
#tags-container { display: none; }
.mobile #tags-container { display: none; }
#tags-container { padding-bottom: 0px; }

html { font-size: 28px; }
.mobile { font-size: 28px; }
.hints { font-size: .85rem; }

.card, kbd { font-family: Arial Greek, Arial; }

img { max-width: 85%; max-height: 100%; }

/* Default text & background */
.card { color: black; }
.card { background-color: #D1CFCE; }

/* Cloze */
.cloze, .cloze b, .cloze u, .cloze i { color: blue; }
.cloze.one-by-one, .cloze.one-by-one b, .cloze.one-by-one u, .cloze.one-by-one i { color: #009400; }
.cloze-hint, .cloze-hint b, .cloze-hint u, .cloze-hint i { color: #009400; }

/* Extra field */
#extra, #extra i { color: navy; }

/* Hints */
.hints { color: #4297F9; }

/* Missed */
#missed { color: red; }

/* Timer */
.timer { color: transparent; }

/* Empty links */
a:not([href]), a[href^="javascript:"] { text-decoration: none; color: inherit; }

/* Night mode */
.nightMode.card, .night_mode .card { color: #FFFAFA !important; }
.nightMode.card, .night_mode .card { background-color: #272828 !important; }
.nightMode .cloze, .nightMode .cloze b, .nightMode .cloze u, .nightMode .cloze i,
.night_mode .cloze, .night_mode .cloze b, .night_mode .cloze u, .night_mode .cloze i { color: #4297F9 !important; }
.nightMode .cloze.one-by-one, .nightMode .cloze.one-by-one b,
.night_mode .cloze.one-by-one, .night_mode .cloze.one-by-one b { color: #009400 !important; }
.nightMode #extra, .nightMode #extra i,
.night_mode #extra, .night_mode #extra i { color: magenta; }
.nightMode .hints, .night_mode .hints { color: cyan; }

b { color: inherit; }
u { color: inherit; }
i { color: inherit; }

/* Card layout */
.card {
  text-align: center;
  font-size: 1rem;
  height: 100%;
  margin: 0px 15px;
  flex-grow: 1;
  padding-bottom: 1em;
  margin-top: 15px;
}
.mobile .card { padding-bottom: 5em; margin: 1ex .3px; }

hr { opacity: .7; }
.timer { font-size: 20px; margin: 12em auto auto auto; }

/* Cloze field */
.cloze { font-weight: bold; }
.clozefield, .mobile .editcloze { display: none; }
.editcloze, .mobile .clozefield { display: block; }

/* Hints */
.hints { font-style: italic; }
.hints+#extra { margin-top: 1rem; }

/* Extra field */
#extra { font-style: italic; font-size: 1rem; }

/* Tables */
table {
  overflow-x: auto; margin-left: auto; margin-right: auto;
  border-collapse: collapse; overflow: scroll; white-space: normal;
  font-style: normal;
  font-size: clamp(0.1rem, 1.7vw, 0.9rem) !important;
  max-width: 95vw;
}
table td:first-child { border-left: 1px solid white; }
table td:last-child { border-right: 1px solid white; }
table tr, td, th {
  padding-top: clamp(0.05rem, 1vw, 1rem);
  padding-bottom: clamp(0.05rem, 1vw, 1rem);
  padding-left: clamp(0.05rem, 1vw, 1rem);
  padding-right: clamp(0.05rem, 1vw, 1rem);
}
table tr td:first-child[colspan]:last-child[colspan] {
  background-color: #ffffff; color: #367390;
  border-top: 3px solid #367390; border-bottom: 3px solid #367390;
}
table th { background-color: #ddecf2; color: #266988; border: 1px solid #ffffff; font-weight: normal; }
table tr:nth-child(even) { color: #000000; background-color: #f8f8f8; }
table { color: #000000; border: 1px solid #a4cde0; background-color: #ffffff; }
.night_mode table th, .nightMode table th { background-color: #19181d; color: #3086ae; border: 1px solid #393743; }
.night_mode table tr:nth-child(even), .nightMode table tr:nth-child(even) { color: #ffffff; background-color: #2e2e36; }
.night_mode table, .nightMode table { color: #ffffff; border: 1px solid #393743; background-color: #26252b; }

/* Lists */
ul, ol { padding-left: 40px; max-width: 50%; margin-left: auto; margin-right: auto; text-align: left; }
ul ul, table ul, ol ol, table ol { padding-left: 20px; max-width: 100%; margin-left: 0; margin-right: 0; display: block; }
.mobile ul, .mobile ol { text-align: left; max-width: 100%; }

/* Basic card back — white text (intentional: preserved from original design) */
.back { color: #ffffff; }

/* Front */
.front { font-size: 1.05rem; font-weight: 600; margin-bottom: 4px; }
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
                "afmt": '{{cloze:Text}}<div id="extra">{{Extra}}</div>',
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

    Cards stamped with a 'chunk_label' key (set by generate_all_cards) are
    placed in a subdeck named  deck_name::chunk_label  so each chunk of the
    source document gets its own subdeck.  Cards without a label go into the
    root deck.

    Returns the number of notes successfully added across all decks.
    """
    basic_model = _basic_model()
    cloze_model = _cloze_model()

    # Collect subdeck labels in the order they first appear
    seen: dict[str, genanki.Deck] = {}
    root_deck_id = random.randrange(1 << 30, 1 << 31)
    root_deck = genanki.Deck(root_deck_id, deck_name)

    def get_deck(label: str | None) -> genanki.Deck:
        if not label:
            return root_deck
        if label not in seen:
            seen[label] = genanki.Deck(
                random.randrange(1 << 30, 1 << 31),
                f"{deck_name}::{label}",
            )
        return seen[label]

    added = 0
    skipped = 0

    for card in cards:
        card_type = card.get("type", "").lower().strip()
        deck = get_deck(card.get("chunk_label"))

        try:
            if card_type == "basic":
                front = str(card.get("front", "")).strip()
                back = str(card.get("back", "")).strip()
                if not front or not back:
                    skipped += 1
                    continue
                back_html = back.replace("\n", "<br>")
                note = genanki.Note(model=basic_model, fields=[front, back_html])
                deck.add_note(note)
                added += 1

            elif card_type == "cloze":
                text = str(card.get("text", "")).strip()
                extra = str(card.get("extra", "")).strip()
                if not text or "{{c" not in text:
                    skipped += 1
                    continue
                note = genanki.Note(model=cloze_model, fields=[text, extra])
                deck.add_note(note)
                added += 1

            else:
                skipped += 1

        except Exception:
            skipped += 1

    all_decks = [root_deck] + list(seen.values())
    package = genanki.Package(all_decks)
    package.write_to_file(output_path)

    if skipped:
        print(f"  (Skipped {skipped} malformed or unrecognised cards)")

    return added
