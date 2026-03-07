import os

# Anthropic API key — set via environment variable or --api-key flag
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")

# Claude model used for card generation
MODEL: str = "claude-opus-4-6"

# Maximum words per chunk sent to Claude in a single request.
# Keeps prompts within a comfortable token budget while staying thorough.
MAX_CHUNK_WORDS: int = 1500

# Smaller chunk size for vignette generation — each question produces ~500 output
# tokens (stem + 5 choices + explanations), so smaller input = safer JSON size.
MAX_VIGNETTE_CHUNK_WORDS: int = 700

# Stable genanki model IDs — must be unique per model type and never change
# so that re-importing an updated deck updates existing cards rather than
# creating duplicates.
ANKI_BASIC_MODEL_ID: int = 1_607_392_319
ANKI_CLOZE_MODEL_ID: int = 998_877_661
