# Architecture

## System Overview

Two deployment modes sharing the same Python processing pipeline:

```
[Desktop]  app.py (tkinter GUI)
               │
               ▼
[Shared Pipeline]
  extractor.py → card_generator.py / vignette_generator.py → anki_builder.py / pdf_builder.py

[Web]  frontend/ (Next.js on Vercel)
           │  HTTP (FormData + SSE)
           ▼
       server.py (Flask on Railway)
           │
           ▼
[Shared Pipeline] (same modules as above)
```

## Components

### `extractor.py`
- `extract(path)` → `List[Tuple[int, str]]` — (page_num, text) pairs
- `chunk_pages(pages, max_words)` → `List[Chunk]` — groups pages into word-limited chunks
- Supports `.pdf` (PyMuPDF) and `.pptx`/`.ppt` (python-pptx)
- Skips blank pages/slides

### `card_generator.py`
- Input: list of chunks
- Calls Claude per chunk via streaming API
- System prompt instructs: cloze cards for facts, basic cards for clinical reasoning
- Output: `List[Dict]` with `type`, `text`/`extra` (cloze) or `front`/`back` (basic)
- Retry logic: 2 retries on `RateLimitError`, `APIStatusError`, or JSON parse failure

### `vignette_generator.py`
- Input: list of chunks (max 700 words each — smaller than flashcard chunks)
- System prompt embeds full 10-step NBME item-writing algorithm
- Output: `List[Dict]` with `concept`, `cognitive_task`, `stem`, `lead_in`, `choices` (A–E), `correct`, `explanation`, `distractor_explanations`
- max_tokens=32000 (vignettes are verbose)

### `anki_builder.py`
- Two genanki models with stable IDs (from `config.py`):
  - `ANKI_BASIC_MODEL_ID = 1_607_392_319`
  - `ANKI_CLOZE_MODEL_ID = 998_877_661`
- CSS: white text on back of basic cards (`.back { color: #ffffff }`)
- Writes `.apkg` via `genanki.Package`

### `pdf_builder.py`
- Two-section PDF: QUESTIONS section + ANSWER KEY section
- Uses Arial TTF fonts from `/System/Library/Fonts/Supplemental/` (Unicode support)
- Header: 14mm navy bar; `set_y(20)` reset prevents content overlap
- Page guard: `if get_y() > h - b_margin - 50: add_page()`
- Answer key includes: correct answer (green), full explanation, distractor explanations (red)

### `server.py` (Flask web backend)
- In-memory job store: `_jobs` dict keyed by UUID
- Background threads: one per generation request
- Endpoints:
  - `POST /api/generate` — saves uploaded file, starts thread, returns `job_id`
  - `GET /api/progress/<job_id>` — SSE stream of log lines (`kind:message\n\n`)
  - `GET /api/download/<job_id>` — serves zip file when status=done
  - `GET /api/health` — health check
- Output: zip containing `.apkg` and/or `_questions.pdf`

### `frontend/app/page.tsx` (Next.js)
- Single-page app, fully client-side (`"use client"`)
- File input: drag-and-drop + click-to-browse
- Streams progress via `EventSource` (SSE)
- `NEXT_PUBLIC_API_URL` env var points to Railway backend

## Data Flow (Web)

```
User uploads PDF
    │
    ▼
POST /api/generate (multipart form)
    │  file, mode, api_key, deck_name
    ▼
server.py saves file to tempdir, starts background thread, returns job_id
    │
    ▼
Frontend opens EventSource to GET /api/progress/{job_id}
    │
    ├── extractor.py extracts + chunks text
    ├── card_generator.py calls Claude (streaming) per chunk
    ├── vignette_generator.py calls Claude (streaming) per chunk
    ├── anki_builder.py writes .apkg
    ├── pdf_builder.py writes .pdf
    └── zip both files → job status = "done"
    │
    ▼
Frontend shows Download button
    │
    ▼
GET /api/download/{job_id} → zip file sent as attachment
```

## Config (`config.py`)
| Key | Value | Purpose |
|-----|-------|---------|
| `MODEL` | `claude-opus-4-6` | Claude model for all generation |
| `MAX_CHUNK_WORDS` | 1500 | Flashcard chunk size |
| `MAX_VIGNETTE_CHUNK_WORDS` | 700 | Vignette chunk size (smaller = safer JSON) |
| `ANKI_BASIC_MODEL_ID` | 1607392319 | Must never change |
| `ANKI_CLOZE_MODEL_ID` | 998877661 | Must never change |

## Key Design Decisions
- **Streaming API**: required because generation takes 5–15 min; non-streaming requests timeout
- **Separate chunk sizes**: vignettes produce ~5x more output tokens per input word than flashcards
- **In-memory job store**: sufficient for single-instance Railway deployment; no Redis needed
- **User-supplied API key**: no key stored server-side; each request uses the user's own key
- **Stable Anki model IDs**: changing these causes Anki to create duplicate cards on re-import
