"""
card_generator.py — Use the Claude API to turn raw medical text into
structured Anki card data (list of dicts).

Two card types are generated per chunk:
  - "cloze"  → for discrete, memorisable facts (drugs, values, mechanisms)
  - "basic"  → for clinical presentations, concepts, and reasoning
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
student preparing for in-house (shelf / NBME-style) exams.

Given a section of medical lecture notes or slides, generate a comprehensive \
set of high-yield Anki flashcards in TWO formats:

──────────────────────────────────────────────────────────────────────────────
CARD TYPE 1 — CLOZE  (for memorisable facts)
──────────────────────────────────────────────────────────────────────────────
Use for:
  • Drug names, mechanisms of action, doses
  • Specific lab values, cut-offs, and diagnostic criteria
  • Epidemiology numbers and risk-factor associations
  • Pathophysiology steps and buzzword pairings
  • Classic findings (e.g., "strawberry cervix → Trichomonas")

Rules:
  • Use {{c1::answer}} for the first blank, {{c2::answer}} for the second, etc.
  • Keep 1–3 cloze deletions per card; never more.
  • The "extra" field should contain a helpful mnemonic, clinical pearl, or
    the broader context that makes the fact stick.

──────────────────────────────────────────────────────────────────────────────
CARD TYPE 2 — BASIC  (for clinical reasoning and concepts)
──────────────────────────────────────────────────────────────────────────────
Use for:
  • Clinical presentations and characteristic symptom constellations
  • Differential diagnosis questions
  • Management algorithms and first-line treatments
  • Pathophysiology explanations (the "why")
  • Exam-style vignette-style questions

Rules:
  • "front": Write as a pointed clinical question. Be specific.
    Good: "What is the pathophysiology of HRS Type 1?"
    Bad:  "Tell me about hepatorenal syndrome."
  • "back": Use numbered lists or bullet points for clarity.
    Include key distinguishing features and exam high-yield details.

──────────────────────────────────────────────────────────────────────────────
GENERAL RULES
──────────────────────────────────────────────────────────────────────────────
  • Only include medically relevant, high-yield information.
  • Cover every disease, drug, mechanism, and clinical pearl in the content.
  • Do NOT generate duplicate cards or trivially rephrased variants.
  • Use correct medical terminology throughout.
  • Aim for 15–30 cards per content chunk depending on density.

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
    retries: int = 2,
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
                wait = 60 * attempt  # rate limit window is per minute
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
    combined list of raw card dicts.
    """
    all_cards: List[Dict[str, Any]] = []
    total = len(chunks)
    for i, chunk in enumerate(chunks, start=1):
        cards = _generate_chunk(client, chunk, i, total, log_fn=log_fn)
        all_cards.extend(cards)
    return all_cards
