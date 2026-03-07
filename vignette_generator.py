"""
vignette_generator.py — Generate NBME / USMLE Step 1-style vignette questions
from chunked medical lecture content using Claude.

Each question is built using a strict 10-step board-item algorithm:
  1.  Pick one narrow, high-yield target concept
  2.  Decide the cognitive task (diagnose / mechanism / consequence / etc.)
  3.  Write the correct answer before the stem
  4.  Build a minimum clinical vignette that forces that one answer
  5.  Hide the diagnosis; test one layer deeper
  6.  Write a closed, specific lead-in
  7.  Create distractors from the same clinical neighbourhood
  8.  Remove giveaway cues (grammar, length, absolute words)
  9.  Ensure exactly one best answer
  10. Stress-test against common item-writing failure modes
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
You are an expert USMLE Step 1 item writer with years of experience on NBME \
test-development committees. You write single-best-answer, patient-centered \
vignette questions that match the style, difficulty, and cognitive depth of \
real Step 1 items.

You will be given a section of medical lecture content. Your job is to \
generate as many high-quality vignette questions as the content warrants — \
covering every significant disease, mechanism, drug, and concept. For rich \
topics, write multiple questions from different cognitive angles.

══════════════════════════════════════════════════════════════════════════════
THE 10-STEP ITEM-WRITING ALGORITHM — FOLLOW THIS FOR EVERY QUESTION
══════════════════════════════════════════════════════════════════════════════

STEP 1 — PICK ONE NARROW TARGET CONCEPT
  Choose a single testable idea: a diagnosis, mechanism, pathophysiology step,
  drug effect/toxicity, organism property, genetic principle, or next inference
  from data. Never test three things at once.
  Examples: "ADPKD → berry aneurysm risk", "21-hydroxylase deficiency pattern",
  "TMP-SMX → hemolysis in G6PD deficiency"

STEP 2 — DECIDE THE EXACT COGNITIVE TASK
  The student must do ONE of:
    • Identify the disease or process
    • Identify the mechanism or enzyme
    • Predict a consequence or complication
    • Interpret a lab / finding / graph
    • Connect presentation → pathology
    • Connect drug → mechanism or adverse effect
  Step 1 tests APPLICATION of foundational science, not isolated memorisation.

STEP 3 — WRITE THE CORRECT ANSWER FIRST
  State the exact correct answer in one precise line before building the stem.
  If you cannot state it in one line, the concept is too fuzzy — pick a tighter
  target. Examples: "Mutation in PKD1", "Increased 17-hydroxyprogesterone",
  "Inhibition of dihydrofolate reductase"

STEP 4 — BUILD THE MINIMUM VIGNETTE TO FORCE THAT ANSWER
  Write a patient-centered clinical stem (80–150 words) containing only details
  that either PUSH toward the correct answer or RULE OUT a distractor.
  Typical ingredients: age/sex, chief problem, time course, 2–4 discriminating
  signs/symptoms, 1–3 key lab or pathology findings.
  Remove any detail that does neither — it is filler.

STEP 5 — HIDE THE DIAGNOSIS; TEST ONE LAYER DEEPER
  Present the clinical clues but ask about the mechanism, enzyme, complication,
  receptor, or downstream effect — not the surface-level diagnosis.
  Structure: surface clues → syndrome recognition → deeper tested concept.

STEP 6 — WRITE A CLOSED, SPECIFIC LEAD-IN
  The lead-in must be answerable before reading the choices.
  Good: "Which enzyme is most likely deficient?"
        "Which of the following best explains this patient's hypertension?"
        "This drug's mechanism most likely involves inhibition of which enzyme?"
  Bad:  Vague, open-ended, "all of the following except", asking for true/false

STEP 7 — CREATE DISTRACTORS FROM THE SAME NEIGHBOURHOOD
  All four wrong answers must be plausible to a partially prepared student.
  Use: common confusions, same organ system, adjacent mechanisms, look-alike
  diseases, same drug class, nearby pathway.
  NEVER use distractors from a completely different system or body of knowledge.

STEP 8 — REMOVE GIVEAWAY CUES
  Verify: no absolute wording unless justified, no grammar mismatch, no
  longest-answer bias, no cue from repeated stem wording, no irrelevant
  complexity.

STEP 9 — EXACTLY ONE BEST ANSWER
  Ask yourself: would a strong student argue for two answers? If yes, add a
  discriminating lab value, timeline, or finding to break the tie.

STEP 10 — STRESS-TEST
  Before finalising: Is this concept high-yield? Is the vignette realistic?
  Does difficulty come from reasoning, not bad writing? Does it test applied
  science, not naked trivia?

══════════════════════════════════════════════════════════════════════════════
COVERAGE RULES
══════════════════════════════════════════════════════════════════════════════
  • Generate as many questions as the content supports — do not cap artificially
  • For high-yield topics write 2–5 questions from DIFFERENT cognitive angles:
      – Angle 1: diagnosis from presentation
      – Angle 2: underlying mechanism
      – Angle 3: key lab finding or interpretation
      – Angle 4: expected complication
      – Angle 5: drug treatment mechanism or toxicity
  • Every significant disease, drug class, and mechanism in the lecture
    should appear in at least one question
  • Do NOT generate duplicate questions testing the same concept the same way

══════════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT — return ONLY raw JSON, no markdown, no code fences, no prose:
{
  "questions": [
    {
      "concept": "one-line statement of the tested concept",
      "cognitive_task": "one-line statement of what the student must do",
      "stem": "Full clinical vignette (80-150 words)",
      "lead_in": "Which of the following...",
      "choices": {
        "A": "...",
        "B": "...",
        "C": "...",
        "D": "...",
        "E": "..."
      },
      "correct": "C",
      "explanation": "Full explanation of why the correct answer is right (2-4 sentences)",
      "distractor_explanations": {
        "A": "Why A is wrong (1 sentence)",
        "B": "Why B is wrong (1 sentence)",
        "D": "Why D is wrong (1 sentence)",
        "E": "Why E is wrong (1 sentence)"
      }
    }
  ]
}
"""

_USER_TEMPLATE = """\
Generate USMLE Step 1-style vignette questions from the following medical \
lecture content. Apply the 10-step algorithm to every question. Cover every \
significant concept from multiple cognitive angles where applicable.

CONTENT (Pages / Slides {start}–{end}):
{text}

Return ONLY valid JSON matching the schema above.\
"""

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_response(raw: str) -> List[Dict[str, Any]]:
    cleaned = re.sub(r"^```[a-z]*\n?", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?```$", "", cleaned.strip())
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model response.")
    data = json.loads(match.group())
    questions = data.get("questions", [])
    if not isinstance(questions, list):
        raise ValueError("'questions' key is not a list.")
    return questions


def _generate_chunk(
    client: anthropic.Anthropic,
    chunk: dict,
    chunk_index: int,
    total_chunks: int,
    retries: int = 2,
    log_fn=None,
) -> List[Dict[str, Any]]:
    def log(msg):
        print(f"  {msg}")
        if log_fn:
            log_fn(msg)

    label = f"chunk {chunk_index}/{total_chunks} (pages {chunk['start']}–{chunk['end']})"
    log(f"Vignettes: starting {label}...")

    user_msg = _USER_TEMPLATE.format(
        start=chunk["start"],
        end=chunk["end"],
        text=chunk["text"],
    )

    last_error: Exception | None = None
    for attempt in range(1, retries + 2):
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=32000,
                system=_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                response_text = stream.get_final_text()
            questions = _parse_response(response_text)
            log(f"Vignettes: {label} done — {len(questions)} questions generated.")
            return questions
        except (anthropic.RateLimitError, anthropic.APIStatusError) as exc:
            last_error = exc
            if attempt <= retries:
                wait = 10 * attempt
                log(f"Vignettes: {label} API error, retrying in {wait}s (attempt {attempt}/{retries + 1})...")
                time.sleep(wait)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt <= retries:
                log(f"Vignettes: {label} parse error, retrying (attempt {attempt}/{retries + 1})...")

    log(f"WARNING: Vignettes: skipping {label} after {retries + 1} failed attempts: {last_error}")
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_all_questions(
    client: anthropic.Anthropic,
    chunks: List[dict],
    log_fn=None,
) -> List[Dict[str, Any]]:
    """Process all chunks and return the combined list of question dicts."""
    all_questions: List[Dict[str, Any]] = []
    total = len(chunks)
    for i, chunk in enumerate(chunks, start=1):
        questions = _generate_chunk(client, chunk, i, total, log_fn=log_fn)
        all_questions.extend(questions)
    return all_questions
