"""
server.py — Flask backend for the PDF-to-Anki web app.

Deployed on Railway. The Next.js frontend on Vercel calls this API.

Endpoints:
  POST /api/generate          — upload file, start background job, return job_id
  GET  /api/progress/<job_id> — SSE stream of progress log lines
  GET  /api/download/<job_id> — download the output zip when done
  GET  /api/health            — health check
"""

from __future__ import annotations

import os
import queue
import tempfile
import threading
import uuid
import zipfile
from typing import Any, Dict

import anthropic
from flask import Flask, Response, jsonify, request, send_file
from flask_cors import CORS

from config import MAX_CHUNK_WORDS, MAX_VIGNETTE_CHUNK_WORDS
from extractor import chunk_pages, extract
from card_generator import generate_all_cards
from anki_builder import build_deck
from vignette_generator import generate_all_questions
from pdf_builder import build_pdf

app = Flask(__name__)
CORS(app, origins="*")

# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------

_jobs: Dict[str, Any] = {}
_jobs_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _run_job(
    job_id: str,
    file_path: str,
    mode: str,
    api_key: str,
    deck_name: str,
    out_dir: str,
) -> None:
    q = _jobs[job_id]["queue"]

    def log(msg: str) -> None:
        q.put(("log", msg))
        print(f"[{job_id[:8]}] {msg}")

    try:
        log("Extracting text from file...")
        pages = extract(file_path)
        log(f"Extracted {len(pages)} pages/slides.")

        client = anthropic.Anthropic(api_key=api_key)

        apkg_path = None
        pdf_path = None

        if mode in ("flashcards", "both"):
            card_chunks = chunk_pages(pages, MAX_CHUNK_WORDS)
            log(f"Generating flashcards — {len(card_chunks)} chunk(s)...")
            cards = generate_all_cards(client, card_chunks)
            log(f"Generated {len(cards)} cards. Building Anki deck...")
            apkg_path = os.path.join(out_dir, f"{deck_name}.apkg")
            count = build_deck(cards, deck_name, apkg_path)
            log(f"Anki deck ready: {count} notes.")

        if mode in ("vignettes", "both"):
            vig_chunks = chunk_pages(pages, MAX_VIGNETTE_CHUNK_WORDS)
            log(f"Generating vignette questions — {len(vig_chunks)} chunk(s)...")
            questions = generate_all_questions(client, vig_chunks)
            log(f"Generated {len(questions)} questions. Building PDF...")
            pdf_path = os.path.join(out_dir, f"{deck_name}_questions.pdf")
            written = build_pdf(questions, deck_name, pdf_path)
            log(f"PDF ready: {written} questions.")

        # Zip all outputs into one file
        zip_path = os.path.join(out_dir, f"{deck_name}_output.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            if apkg_path and os.path.exists(apkg_path):
                zf.write(apkg_path, os.path.basename(apkg_path))
            if pdf_path and os.path.exists(pdf_path):
                zf.write(pdf_path, os.path.basename(pdf_path))

        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result_path"] = zip_path

        log("DONE")

    except Exception as exc:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(exc)
        q.put(("error", str(exc)))
        print(f"[{job_id[:8]}] ERROR: {exc}")

    finally:
        q.put(None)  # sentinel — tells SSE stream to close


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/generate", methods=["POST"])
def generate():
    file = request.files.get("file")
    mode = request.form.get("mode", "both")
    api_key = request.form.get("api_key", "").strip()
    deck_name = (request.form.get("deck_name", "") or "My Deck").strip()

    if not file or not file.filename:
        return jsonify({"error": "No file uploaded"}), 400
    if not api_key:
        return jsonify({"error": "Anthropic API key required"}), 400
    if mode not in ("flashcards", "vignettes", "both"):
        return jsonify({"error": "mode must be flashcards, vignettes, or both"}), 400

    job_id = str(uuid.uuid4())
    out_dir = tempfile.mkdtemp()

    suffix = os.path.splitext(file.filename)[1].lower()
    file_path = os.path.join(out_dir, f"input{suffix}")
    file.save(file_path)

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "queue": queue.Queue(),
            "result_path": None,
            "error": None,
        }

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, file_path, mode, api_key, deck_name, out_dir),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/progress/<job_id>")
def progress(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    def stream():
        q = job["queue"]
        while True:
            try:
                item = q.get(timeout=15)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if item is None:
                yield "data: [DONE]\n\n"
                break
            kind, msg = item
            # SSE format: "data: <payload>\n\n"
            yield f"data: {kind}:{msg}\n\n"

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering on Railway
        },
    )


@app.route("/api/download/<job_id>")
def download(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] != "done":
        return jsonify({"error": "Job not complete yet"}), 400
    return send_file(job["result_path"], as_attachment=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
