# PDF to Anki — Claude Context

## Project Overview
Desktop + web app that converts medical PDF/PPTX lecture files into:
- Anki flashcard decks (.apkg) — cloze deletions for facts, basic Q&A for concepts
- USMLE Step 1-style vignette question PDFs with full answer key

Target user: medical students studying for shelf/NBME/USMLE exams.

## Tech Stack
- **AI**: Anthropic Claude (`claude-opus-4-6`) via streaming API (`client.messages.stream`)
- **Desktop GUI**: tkinter + tkinterdnd2
- **Web backend**: Flask + gunicorn (deployed on Railway)
- **Web frontend**: Next.js 14 + Tailwind CSS (deployed on Vercel)
- **PDF extraction**: PyMuPDF (fitz)
- **PPTX extraction**: python-pptx
- **Anki deck building**: genanki
- **PDF generation**: fpdf2 with Arial TTF fonts (macOS: `/System/Library/Fonts/Supplemental/`)

## Key Files
```
/                        # Flask backend root (Railway deploys from here)
├── server.py            # Flask API (web backend)
├── app.py               # tkinter desktop GUI
├── card_generator.py    # Claude flashcard generation
├── vignette_generator.py# Claude USMLE vignette generation (10-step algorithm)
├── pdf_builder.py       # fpdf2 PDF output
├── anki_builder.py      # genanki .apkg builder
├── extractor.py         # PDF/PPTX text extraction + chunking
├── config.py            # MODEL, chunk sizes, Anki model IDs
├── Procfile             # Railway: gunicorn server:app --timeout 600
├── requirements.txt     # All Python deps incl. flask, gunicorn
└── frontend/            # Next.js app (Vercel deploys from this subdirectory)
    └── app/page.tsx     # Main UI page
```

## Critical Rules
- **Always use streaming API** — `client.messages.stream()` + `stream.get_final_text()`. Never use `client.messages.create()` for large outputs; Railway/Claude will timeout.
- **max_tokens**: 16000 for flashcards, 32000 for vignettes — never lower.
- **Chunk sizes**: 1500 words for flashcards, 700 words for vignettes.
- **Anki model IDs** in `config.py` must never change (changing them creates duplicate cards on reimport).
- **fpdf2 fonts**: must use Arial TTF (not Helvetica) — medical content contains Unicode (β, α, etc.).
- **PDF header overlap fix**: `header()` ends with `self.set_y(20)`; `set_margins(14, 20, 14)`; 50mm page guard before each question.
- Basic card backs use `color: #ffffff` (white text) in CSS.

## Deployments
- **Railway backend**: `https://pdf-to-anki-production-7064.up.railway.app`
- **Vercel frontend**: `NEXT_PUBLIC_API_URL` env var points to Railway URL
- **GitHub**: `https://github.com/jahansherkhan99/pdf-to-anki`

## Current Focus
Web version is live. Desktop app (`app.py`) remains functional independently.
