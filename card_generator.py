"""
card_generator.py — Use the Claude API to turn raw medical text into
structured Anki card data (list of dicts).

Default card type is cloze deletion.  Two formats are used:

  - "cloze" (VIGNETTE style) → clinical presentations/diagnoses written as a
    patient scenario with the diagnosis as the cloze blank
  - "cloze" (STANDARD style) → definitions, mechanisms, treatments, lab values
  - "basic" → last resort only; avoided unless content truly cannot be cloze
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List

import anthropic

from config import MODEL

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are an expert medical educator building Anki flashcards for a medical \
student preparing for shelf / NBME-style exams.

══════════════════════════════════════════════════════════════════════════════
DEFAULT FORMAT: CLOZE DELETION
══════════════════════════════════════════════════════════════════════════════
Cloze deletion is the default for EVERY card. Only use the "basic" type as a
last resort when content genuinely cannot be expressed as a cloze.

Use {{c1::answer}} for the first blank, {{c2::answer}} for the second, etc.
Keep 1–2 cloze deletions per card; never more than 3.
The "extra" field: mnemonic, clinical pearl, or the "why" behind the fact.

══════════════════════════════════════════════════════════════════════════════
FORMAT A — VIGNETTE-STYLE CLOZE  ← USE THIS for clinical presentations
══════════════════════════════════════════════════════════════════════════════
WHEN TO USE:
  • Any disease, syndrome, or diagnosis defined by a cluster of symptoms/signs
  • Classic triads, tetrads, or constellations
  • Diagnosis-from-presentation pattern recognition
  • Any time a student would need to identify a condition from clinical clues

HOW TO WRITE IT:
  Present as a one-sentence patient scenario. Hide the diagnosis as the cloze.

  Template:
    "A patient presents with [key symptoms/findings]; the most likely
     diagnosis is {{c1::DIAGNOSIS}}."

  Rules:
    • Include only the 2–4 discriminating features that point to that diagnosis
    • Do NOT name the diagnosis in the stem — it is always the cloze blank
    • Extra field: explain why those clues point to this diagnosis; add
      differentiating feature vs. the nearest look-alike

  Examples:
    ✓ "A patient presents with fever, jaundice, and right upper quadrant pain;
       the most likely diagnosis is {{c1::acute cholangitis (Charcot's triad)}}."
       Extra: "Add altered mental status + hypotension → Reynolds pentad
               (suppurative cholangitis). Distinguish from cholecystitis:
               cholangitis has jaundice."

    ✓ "A young woman presents with malar rash, arthritis, and
       anti-dsDNA antibodies; the most likely diagnosis is {{c1::SLE}}."
       Extra: "Butterfly rash spares nasolabial folds. ANA sensitive,
               anti-dsDNA specific."

    ✓ "A patient with a history of GERD presents with dysphagia to solids
       progressing to liquids and weight loss; the most likely diagnosis
       is {{c1::esophageal adenocarcinoma}}."

══════════════════════════════════════════════════════════════════════════════
FORMAT B — STANDARD CLOZE  ← USE THIS for non-presentation facts
══════════════════════════════════════════════════════════════════════════════
WHEN TO USE:
  • Definitions, mechanisms of action, pathophysiology steps
  • Drug names, doses, side effects, contraindications
  • Lab values, diagnostic criteria, cut-offs
  • Buzzword associations and classic findings
  • Treatments and first-line agents

  Examples:
    ✓ "{{c1::Charcot's triad}} consists of fever, jaundice, and RUQ pain."
    ✓ "The most common cause of community-acquired pneumonia is
       {{c1::Streptococcus pneumoniae}}."
    ✓ "Metformin's mechanism: inhibits {{c1::Complex I of the mitochondrial
       electron transport chain}}, reducing hepatic gluconeogenesis."
    ✓ "HbA1c reflects average blood glucose over the past {{c1::2–3 months}}
       due to the lifespan of {{c2::RBCs}}."

══════════════════════════════════════════════════════════════════════════════
FORMAT C — BASIC (LAST RESORT ONLY)
══════════════════════════════════════════════════════════════════════════════
Only use when multi-step reasoning, a comparison table, or a management
algorithm genuinely cannot be expressed as a single cloze statement.
Aim for fewer than 5% of cards to be basic type.

  Rules:
    • "front": Pointed clinical question. Not "Tell me about X."
      Good: "What distinguishes Type 1 from Type 2 HRS?"
    • "back": Bullet points. Key distinguishing features only.

══════════════════════════════════════════════════════════════════════════════
GENERAL RULES
══════════════════════════════════════════════════════════════════════════════
  • Cover every disease, drug, mechanism, and clinical pearl in the content.
  • Only high-yield, testable concepts — no filler, no redundancy.
  • Do NOT hallucinate beyond the provided content.
  • Aim for 15–30 cards per chunk depending on density.

OUTPUT FORMAT — return ONLY raw JSON (no markdown, no code fences, no prose):
{
  "cards": [
    {"type": "cloze", "text": "...", "extra": "..."},
    {"type": "basic", "front": "...", "back": "..."}
  ]
}
"""

_USER_TEMPLATE = """\
Generate Anki flashcards from the following medical content. Cover every \
disease, presentation, mechanism, drug, and high-yield fact.

CONTENT (Pages / Slides {start}–{end}):
{text}

Return ONLY valid JSON matching the schema above.\
"""

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_response(raw: str) -> List[Dict[str, Any]]:
    """
    Extract the JSON object from Claude's reply and return the card list.
    Handles cases where the model wraps output in markdown fences.
    """
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```[a-z]*\n?", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?```$", "", cleaned.strip())

    # Find the outermost JSON object
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model response.")

    data = json.loads(match.group())
    cards = data.get("cards", [])
    if not isinstance(cards, list):
        raise ValueError("'cards' key is not a list.")
    return cards


def _generate_chunk(
    client: anthropic.Anthropic,
    chunk: dict,
    chunk_index: int,
    total_chunks: int,
    retries: int = 5,
    log_fn=None,
) -> List[Dict[str, Any]]:
    """Call Claude for a single chunk, with simple retry on transient errors."""
    def log(msg):
        print(f"  {msg}")
        if log_fn:
            log_fn(msg)

    label = f"chunk {chunk_index}/{total_chunks} (pages {chunk['start']}–{chunk['end']})"
    log(f"Flashcards: starting {label}...")

    user_msg = _USER_TEMPLATE.format(
        start=chunk["start"],
        end=chunk["end"],
        text=chunk["text"],
    )

    last_error: Exception | None = None
    for attempt in range(1, retries + 2):  # retries+1 total attempts
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=16000,
                system=_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                response_text = stream.get_final_text()
            cards = _parse_response(response_text)
            log(f"Flashcards: {label} done — {len(cards)} cards generated.")
            return cards
        except anthropic.RateLimitError as exc:
            last_error = exc
            if attempt <= retries:
                wait = 65  # slightly over 1 minute so the per-minute counter resets
                log(f"Flashcards: {label} rate limited, waiting {wait}s (attempt {attempt}/{retries + 1})...")
                time.sleep(wait)
        except anthropic.APIStatusError as exc:
            last_error = exc
            if attempt <= retries:
                wait = 10 * attempt
                log(f"Flashcards: {label} API error ({exc}), retrying in {wait}s (attempt {attempt}/{retries + 1})...")
                time.sleep(wait)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt <= retries:
                log(f"Flashcards: {label} parse error, retrying (attempt {attempt}/{retries + 1})...")

    log(f"WARNING: Flashcards: skipping {label} after {retries + 1} failed attempts: {last_error}")
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_all_cards(
    client: anthropic.Anthropic,
    chunks: List[dict],
    log_fn=None,
) -> List[Dict[str, Any]]:
    """
    Iterate over all text chunks, call Claude for each, and return the
    combined list of raw card dicts.  Each card is stamped with a
    'chunk_label' key (e.g. "Pages 1–15") used by anki_builder to create
    one subdeck per chunk.
    """
    all_cards: List[Dict[str, Any]] = []
    total = len(chunks)
    for i, chunk in enumerate(chunks, start=1):
        cards = _generate_chunk(client, chunk, i, total, log_fn=log_fn)
        label = f"Pages {chunk['start']}–{chunk['end']}"
        for card in cards:
            card["chunk_label"] = label
        all_cards.extend(cards)
    return all_cards
