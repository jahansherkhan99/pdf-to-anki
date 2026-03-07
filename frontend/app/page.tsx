"use client";

import { useCallback, useRef, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:5000";

type Status = "idle" | "running" | "done" | "error";
type Mode = "flashcards" | "vignettes" | "both";

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [deckName, setDeckName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [mode, setMode] = useState<Mode>("both");
  const [status, setStatus] = useState<Status>("idle");
  const [logs, setLogs] = useState<string[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const appendLog = useCallback((line: string) => {
    setLogs((prev) => [...prev, line]);
    setTimeout(() => logsEndRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
  }, []);

  // ── Drag-and-drop handlers ────────────────────────────────────────────────
  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(true);
  };
  const onDragLeave = () => setDragging(false);
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) acceptFile(dropped);
  };
  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0];
    if (picked) acceptFile(picked);
  };
  const acceptFile = (f: File) => {
    const ext = f.name.split(".").pop()?.toLowerCase();
    if (!["pdf", "pptx", "ppt"].includes(ext ?? "")) {
      alert("Only .pdf and .pptx files are supported.");
      return;
    }
    setFile(f);
    // Pre-fill deck name from file name (strip extension)
    if (!deckName) setDeckName(f.name.replace(/\.[^.]+$/, ""));
  };

  // ── Generate ──────────────────────────────────────────────────────────────
  const handleGenerate = async () => {
    if (!file) return alert("Please upload a PDF or PPTX file.");
    if (!apiKey.trim()) return alert("Please enter your Anthropic API key.");

    setStatus("running");
    setLogs([]);
    setJobId(null);

    // 1. POST the file and options
    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
    form.append("api_key", apiKey.trim());
    form.append("deck_name", deckName.trim() || "My Deck");

    let jid: string;
    try {
      const res = await fetch(`${API_URL}/api/generate`, {
        method: "POST",
        body: form,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Server error");
      jid = data.job_id;
      setJobId(jid);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setStatus("error");
      appendLog(`ERROR: ${msg}`);
      return;
    }

    // 2. Stream progress via SSE
    const es = new EventSource(`${API_URL}/api/progress/${jid}`);
    es.onmessage = (e) => {
      const payload = e.data as string;
      if (payload === "[DONE]") {
        es.close();
        setStatus((prev) => (prev === "running" ? "done" : prev));
        return;
      }
      const colonIdx = payload.indexOf(":");
      const kind = payload.slice(0, colonIdx);
      const msg = payload.slice(colonIdx + 1);
      if (kind === "error") {
        setStatus("error");
        appendLog(`ERROR: ${msg}`);
      } else {
        appendLog(msg);
      }
    };
    es.onerror = () => {
      es.close();
      setStatus((s) => (s === "running" ? "error" : s));
      appendLog("Connection to server lost.");
    };
  };

  // ── Download ──────────────────────────────────────────────────────────────
  const handleDownload = () => {
    if (!jobId) return;
    window.location.href = `${API_URL}/api/download/${jobId}`;
  };

  const isRunning = status === "running";
  const isDone = status === "done";
  const isError = status === "error";

  return (
    <div className="min-h-screen bg-[#f4f6fb] flex flex-col">
      {/* ── Header ── */}
      <header className="bg-[#1565c0] text-white py-4 px-6 shadow-lg">
        <h1 className="text-2xl font-bold tracking-tight">PDF to Anki</h1>
        <p className="text-sm text-blue-200 mt-0.5">
          Generate Anki flashcards &amp; USMLE Step 1 vignette questions from medical PDFs
        </p>
      </header>

      <main className="flex-1 max-w-2xl mx-auto w-full px-4 py-10 flex flex-col gap-6">
        {/* ── Drop zone ── */}
        <div
          className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors ${
            dragging
              ? "border-blue-500 bg-blue-50"
              : file
              ? "border-green-500 bg-green-50"
              : "border-gray-300 bg-white hover:border-blue-400 hover:bg-blue-50"
          }`}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.pptx,.ppt"
            className="hidden"
            onChange={onFileChange}
          />
          {file ? (
            <>
              <p className="text-green-700 font-semibold text-lg">{file.name}</p>
              <p className="text-green-600 text-sm mt-1">
                {(file.size / 1024 / 1024).toFixed(2)} MB — click to change
              </p>
            </>
          ) : (
            <>
              <p className="text-gray-500 text-lg font-medium">
                Drag &amp; drop your PDF or PPTX here
              </p>
              <p className="text-gray-400 text-sm mt-1">or click to browse</p>
            </>
          )}
        </div>

        {/* ── Deck name ── */}
        <div>
          <label className="block text-sm font-semibold text-gray-700 mb-1">
            Deck / Document name
          </label>
          <input
            type="text"
            value={deckName}
            onChange={(e) => setDeckName(e.target.value)}
            placeholder="e.g. Renal Pathology Block 3"
            className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {/* ── API key ── */}
        <div>
          <label className="block text-sm font-semibold text-gray-700 mb-1">
            Anthropic API key
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-ant-..."
            className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p className="text-xs text-gray-400 mt-1">
            Your key is never stored — it is sent directly to the API for your request only.
          </p>
        </div>

        {/* ── Mode selector ── */}
        <div>
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            Output mode
          </label>
          <div className="flex gap-3">
            {(
              [
                { value: "flashcards", label: "Flashcards only" },
                { value: "vignettes", label: "Vignette PDF only" },
                { value: "both", label: "Both" },
              ] as { value: Mode; label: string }[]
            ).map(({ value, label }) => (
              <button
                key={value}
                onClick={() => setMode(value)}
                className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-colors ${
                  mode === value
                    ? "bg-[#1565c0] text-white border-[#1565c0]"
                    : "bg-white text-gray-600 border-gray-300 hover:border-blue-400"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* ── Generate button ── */}
        <button
          onClick={handleGenerate}
          disabled={isRunning}
          className={`w-full py-3 rounded-xl text-white font-bold text-base transition-colors ${
            isRunning
              ? "bg-blue-300 cursor-not-allowed"
              : "bg-[#1565c0] hover:bg-[#0d47a1] active:bg-[#0a2e6e]"
          }`}
        >
          {isRunning ? "Generating..." : "Generate"}
        </button>

        {/* ── Progress log ── */}
        {logs.length > 0 && (
          <div className="rounded-xl overflow-hidden border border-gray-800">
            <div className="bg-[#1a1a2e] px-4 py-2 text-xs text-blue-300 font-semibold uppercase tracking-widest">
              Progress
            </div>
            <div className="log-area bg-[#0f0f1a] px-4 py-3 h-52 overflow-y-auto font-mono text-xs text-green-400 space-y-0.5">
              {logs.map((line, i) => (
                <div key={i} className={line.startsWith("ERROR") ? "text-red-400" : ""}>
                  {line}
                </div>
              ))}
              <div ref={logsEndRef} />
            </div>
          </div>
        )}

        {/* ── Status banners ── */}
        {isDone && (
          <div className="bg-green-50 border border-green-300 rounded-xl p-4 flex items-center justify-between">
            <div>
              <p className="text-green-800 font-semibold">Done!</p>
              <p className="text-green-600 text-sm">Your files are ready to download.</p>
            </div>
            <button
              onClick={handleDownload}
              className="bg-green-600 hover:bg-green-700 text-white font-bold py-2.5 px-5 rounded-lg text-sm"
            >
              Download ZIP
            </button>
          </div>
        )}

        {isError && (
          <div className="bg-red-50 border border-red-300 rounded-xl p-4">
            <p className="text-red-800 font-semibold">Something went wrong.</p>
            <p className="text-red-600 text-sm">Check the log above for details.</p>
          </div>
        )}
      </main>

      <footer className="text-center text-xs text-gray-400 py-4">
        Powered by Claude (Anthropic) &mdash; PDF to Anki
      </footer>
    </div>
  );
}
