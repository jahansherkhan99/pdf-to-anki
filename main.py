#!/usr/bin/env python3
"""
main.py — PDF / PPTX  →  Anki deck (.apkg)

Usage:
    python main.py lecture.pdf
    python main.py slides.pptx --deck "Cardiology Week 3" --output cardio.apkg
    python main.py lecture.pdf --deck "Renal Pathology" --api-key sk-ant-...

Environment:
    ANTHROPIC_API_KEY — set this instead of passing --api-key every time.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import anthropic

from config import ANTHROPIC_API_KEY, MODEL
from extractor import chunk_pages, extract
from card_generator import generate_all_cards
from anki_builder import build_deck

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".pdf", ".pptx", ".ppt"}


def _banner(text: str, width: int = 48) -> str:
    return f"\n{'=' * width}\n  {text}\n{'=' * width}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-to-anki",
        description=(
            "Convert a medical PDF or PPTX lecture into an Anki deck (.apkg).\n"
            "Generates cloze-deletion cards for facts and basic Q&A cards\n"
            "for clinical presentations and concepts."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py lecture.pdf\n"
            "  python main.py slides.pptx --deck \"Cardiology Week 3\"\n"
            "  python main.py lecture.pdf --output renal.apkg\n"
        ),
    )
    parser.add_argument(
        "input",
        help="Path to the source PDF or PPTX file.",
    )
    parser.add_argument(
        "--deck", "-d",
        default=None,
        metavar="NAME",
        help=(
            "Name of the Anki deck that will be created. "
            "Defaults to the filename without extension."
        ),
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        metavar="FILE",
        help=(
            "Destination .apkg path. "
            "Defaults to <input_name>.apkg in the same directory."
        ),
    )
    parser.add_argument(
        "--api-key", "-k",
        default=None,
        metavar="KEY",
        help=(
            "Anthropic API key. "
            "Overrides the ANTHROPIC_API_KEY environment variable."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # ── Resolve API key ──────────────────────────────────────────────────────
    api_key = args.api_key or ANTHROPIC_API_KEY
    if not api_key:
        print(
            "Error: No Anthropic API key found.\n"
            "Set the ANTHROPIC_API_KEY environment variable or use --api-key.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Validate input file ──────────────────────────────────────────────────
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        print(
            f"Error: Unsupported file type '{input_path.suffix}'. "
            f"Only {', '.join(sorted(SUPPORTED_EXTENSIONS))} are accepted.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Resolve deck name and output path ────────────────────────────────────
    deck_name = args.deck or input_path.stem
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else input_path.with_suffix(".apkg")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Header ───────────────────────────────────────────────────────────────
    print(_banner("PDF → Anki  |  Medical Card Generator"))
    print(f"  Input  : {input_path}")
    print(f"  Deck   : {deck_name}")
    print(f"  Output : {output_path}")
    print(f"  Model  : {MODEL}")

    # ── Step 1: Extract text ─────────────────────────────────────────────────
    print("\n[1/4] Extracting text from file...")
    try:
        pages = extract(str(input_path))
    except Exception as exc:
        print(f"Error during extraction: {exc}", file=sys.stderr)
        sys.exit(1)

    if not pages:
        print(
            "Error: No text could be extracted. The file may be image-based "
            "(scanned PDF). Please use a PDF with selectable text.",
            file=sys.stderr,
        )
        sys.exit(1)

    unit = "pages" if input_path.suffix.lower() == ".pdf" else "slides"
    print(f"  Found {len(pages)} {unit} containing text.")

    # ── Step 2: Chunk content ────────────────────────────────────────────────
    print("\n[2/4] Chunking content for API processing...")
    chunks = chunk_pages(pages)
    print(f"  Split into {len(chunks)} chunk(s).")

    # ── Step 3: Generate cards via Claude ────────────────────────────────────
    print(f"\n[3/4] Generating Anki cards with Claude ({MODEL})...")
    client = anthropic.Anthropic(api_key=api_key)
    try:
        cards = generate_all_cards(client, chunks)
    except anthropic.AuthenticationError:
        print("Error: Invalid API key.", file=sys.stderr)
        sys.exit(1)
    except anthropic.APIConnectionError as exc:
        print(f"Error: Could not reach the Anthropic API: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error during card generation: {exc}", file=sys.stderr)
        sys.exit(1)

    if not cards:
        print(
            "Error: No cards were generated. Check that the file contains "
            "readable medical content.",
            file=sys.stderr,
        )
        sys.exit(1)

    cloze_n = sum(1 for c in cards if c.get("type") == "cloze")
    basic_n = sum(1 for c in cards if c.get("type") == "basic")
    print(f"\n  Cards generated : {len(cards)}")
    print(f"    Cloze (facts)  : {cloze_n}")
    print(f"    Basic (concepts): {basic_n}")

    # ── Step 4: Build Anki package ───────────────────────────────────────────
    print(f"\n[4/4] Building Anki package...")
    try:
        added = build_deck(cards, deck_name, str(output_path))
    except Exception as exc:
        print(f"Error building Anki deck: {exc}", file=sys.stderr)
        sys.exit(1)

    # ── Done ─────────────────────────────────────────────────────────────────
    print(_banner("Done!"))
    print(f"  {added} cards written to: {output_path}")
    print("\n  To study: open Anki → File → Import → select the .apkg file.")
    print()


if __name__ == "__main__":
    main()
