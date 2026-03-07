# Developer Guide

## Prerequisites
- Python 3.11+
- Node.js 18+
- An Anthropic API key (`sk-ant-...`)
- macOS (desktop app uses macOS system fonts; web app works cross-platform)

## Local Setup

### Python environment
```bash
cd "/Users/jahansherkhan/Downloads/PDF to Anki"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Set API key (desktop app)
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```
Or enter it in the GUI — it persists to `~/.config/pdf_to_anki/config.json`.

## Running Locally

### Desktop app
```bash
python3 app.py
```

### Flask backend (web)
```bash
python3 server.py
# Runs on http://localhost:5000
```

### Next.js frontend (web)
```bash
cd frontend
npm install
npm run dev
# Runs on http://localhost:3000
# Set NEXT_PUBLIC_API_URL=http://localhost:5000 in frontend/.env.local
```

`frontend/.env.local`:
```
NEXT_PUBLIC_API_URL=http://localhost:5000
```

## Build & Deploy

### Push to GitHub (triggers Railway + Vercel auto-deploy)
```bash
git add <files>
git commit -m "description"
git push
```

### Railway (backend)
- Auto-deploys on push to `main`
- Deploys from repo root using `Procfile`:
  `web: gunicorn server:app --timeout 600 --workers 2 --bind 0.0.0.0:$PORT`
- No environment variables required (API key is user-supplied per request)

### Vercel (frontend)
- Auto-deploys on push to `main`
- Root directory: `frontend`
- Required env var: `NEXT_PUBLIC_API_URL=https://pdf-to-anki-production-7064.up.railway.app`
- To make public: Settings → Deployment Protection → None

## Testing a Change End-to-End
1. Start Flask locally: `python3 server.py`
2. Start Next.js locally: `cd frontend && npm run dev`
3. Open `http://localhost:3000`, drop in a small PDF, enter API key, click Generate
4. Watch SSE progress log; download zip when done

## Debugging Tips

### JSON parse errors from Claude
- Symptom: `Expecting ',' delimiter` or `Unterminated string`
- Cause: `max_tokens` too low, response truncated mid-JSON
- Fix: ensure `max_tokens=16000` (cards) / `max_tokens=32000` (vignettes) in the respective generator

### Unicode errors in PDF
- Symptom: `Character 'β' is outside the range of characters supported by helvetica`
- Fix: only use Arial TTF fonts via `add_font()` — never use built-in fpdf2 fonts for medical content

### PDF content overlapping header
- Symptom: question text appears inside the blue header bar on new pages
- Fix: `header()` must end with `self.set_y(20)`; constructor must call `set_margins(14, 20, 14)`

### Streaming errors (`Streaming is required`)
- Cause: `max_tokens > 10000` requires streaming API
- Fix: use `client.messages.stream()` + `stream.get_final_text()` — never `client.messages.create()`

### Railway timeout on long requests
- `Procfile` has `--timeout 600` (10 min); increase if needed for very large PDFs

### SSE not streaming in browser
- Railway disables nginx buffering with `X-Accel-Buffering: no` header (already set in `server.py`)

## Coding Conventions
- All Claude API calls use streaming (`client.messages.stream`)
- Retry logic: 2 retries with `10s * attempt` backoff on API errors
- Chunk text is passed as plain string — no HTML or markdown
- Card/question parsing: strip markdown fences before JSON parse (`re.sub` in `_parse_response`)
- Output files always go to a `tempfile.mkdtemp()` directory; never write to cwd

## Common Pitfalls
- Do not change `ANKI_BASIC_MODEL_ID` or `ANKI_CLOZE_MODEL_ID` — breaks existing decks
- Do not reduce `max_tokens` below 16000/32000 — causes truncated JSON
- Do not use `fpdf2` built-in fonts for any text that may contain medical symbols
- The `tkinterdnd2` package is desktop-only; do not import it in `server.py`
- Railway free tier: $5 credit / 30 days — monitor usage on the Railway dashboard
