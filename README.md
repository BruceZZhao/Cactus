# Project Cactus - a super-fast voice system

Voice-forward chat experience that pairs a FastAPI backend (Google Speech-to-Text, Gemini, Google Text-to-Speech) with a Vite/React frontend. You can drive the stack either from the browser UI or from the included `quick_launch/simple_reply.py` microphone client.

## Repository layout

- `backend/` – FastAPI server, ASR/LLM/TTS orchestration, session handling.
- `frontend/` – Vite + React UI with waveform input, chat log, and streaming audio player.
- `quick_launch/` – CLI helper scripts (`simple_reply.py`) for testing the full audio loop without the browser.

---


## Requirements

- **Python (3.11 tested)** – backend + quick-launch client.
- **Node.js (v18 or newer)** – Vite frontend.
- **Google Cloud** – Speech-to-Text + Text-to-Speech enabled, service-account JSON.
- **Google Gemini API key** – Gemini 2.x model with streaming access (`Google_LLM_API` / `GOOGLE_LLM_API_KEY`).

---

## 1. Backend setup

1. **Create & activate a virtual environment**
   ```bash
   cd /Users/brucezhao/Desktop/Python/Cactus
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Install backend dependencies**
   ```bash
   pip install -r backend/requirements.txt
   ```

3. **Configure credentials & API keys**

   - **Google Speech-to-Text & Text-to-Speech**  
     Enable both APIs, create a service account, download the JSON key, then set `GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/key.json`.
   - **Google Gemini key**  
     Generate at <https://aistudio.google.com/app/apikey>, export `Google_LLM_API=your-gemini-key` (fallback `GOOGLE_LLM_API_KEY`).

   Suggested file placement:
   ```bash
   mkdir -p ~/.config/cactus
   mv ~/Downloads/your-service-account.json ~/.config/cactus/
   export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/cactus/your-service-account.json"
   ```
   Add the exports to your shell profile or a `.env` file that you `source` before running the backend.

4. **Run the FastAPI server**
   ```bash
   source venv/bin/activate
   uvicorn backend.app:app --host 0.0.0.0 --port 8000
   ```

   The server exposes:
   - `POST /sessions` – create voice session.
   - `WebSocket /ws/audio-in/{session_id}` – microphone/ASR stream.
   - `WebSocket /ws/audio-out/{session_id}` – TTS audio + metadata stream.
   - `POST /respond` – text input fallback.

---

## 2. Backend capabilities & APIs
- Real-time ASR via WebSocket streaming (Google Speech-to-Text) with configurable sample rate, language, and frame size (`backend/config.py`).
- Gemini-powered response generation with conversation/session state, token guard, and optional thinker model.
- Sentence-buffered streaming TTS output (Google Text-to-Speech) with per-sentence metadata, ordered queuing, and audio trimming hooks.
- Session orchestration helpers in `backend/runtime/` (bus, queues, session store) and `backend/service/` (ASR, LLM, TTS, orchestrator).

HTTP + WebSocket summary:
- `POST /sessions` – create a new conversation session.
- `DELETE /sessions/{session_id}` – close a session.
- `POST /respond` – send text directly to the LLM.
- `GET /config` – fetch character/script metadata.
- `GET /healthz` – health probe.
- `WS /ws/audio-in/{session_id}` – stream PCM16 mic audio (10 ms chunks recommended).
- `WS /ws/audio-out/{session_id}` – receive interleaved TTS audio bytes + metadata JSON.
---

## 3. Headless testing via `simple_reply.py`
`quick_launch/simple_reply.py` is a minimal end-to-end REPL that hits the same backend APIs/websockets without the browser.

Steps:
```bash
cd /Users/brucezhao/Desktop/Python/Cactus
source venv/bin/activate
python quick_launch/simple_reply.py
```

What it does:
- Creates a backend session (`POST /sessions`).
- Opens `/ws/audio-in/{session}` with your microphone stream (16 kHz mono).
- Opens `/ws/audio-out/{session}` to receive TTS audio chunks + metadata.
- Logs interim/final ASR text (`you:`) and assistant sentences to the console.
- Automatically trims the first ~50 ms of each chunk to avoid plosives and pauses your mic stream while TTS audio is playing (prevents echo).

Make sure:
- The FastAPI backend is already running on `http://127.0.0.1:8000`.
- Your terminal process has mic permissions (macOS will prompt the first time).

Stop the script with `Ctrl+C`.

---


## 4. Frontend setup (Vite)

1. Install JS deps once:
   ```bash
   cd /Users/brucezhao/Desktop/Python/Cactus/frontend
   npm install
   ```

2. Start the dev server (after the backend is already running on port 8000):
   ```bash
   npm run dev
   ```
   The Vite dev server proxies `/api`, `/sessions`, `/respond`, `/config`, `/ws`, and `/healthz` to `http://127.0.0.1:8000` (configured in `vite.config.ts`). Visit the printed URL (usually `http://localhost:5173`) and allow microphone permissions. The UI will:
   - stream mic audio via the ASR socket,
   - display interim/final transcripts above the chat log,
   - queue and auto-play TTS chunks sequentially,
   - auto-scroll and keep chat ordering consistent.

---

## 5. Common workflow

1. `source venv/bin/activate`
2. Export/update the required Google env vars if you haven’t persisted them.
3. `uvicorn backend.app:app --port 8000 --reload`
4. In another terminal: `cd frontend && npm run dev`
5. Optionally, in a third terminal: `python quick_launch/simple_reply.py` for a headless sanity check.

---

## Troubleshooting

- **`ModuleNotFoundError: No module named 'backend'`** – ensure you run `uvicorn backend.app:app` from the project root (so `backend` is importable) and the virtualenv is active.
- **`uvicorn: command not found`** – virtualenv not activated or dependencies not installed. Use `source venv/bin/activate && pip install -r backend/requirements.txt`.
- **Frontend can’t reach backend** – confirm backend runs on `127.0.0.1:8000`; Vite proxy relies on that host/port.
- **No audio output / permission issues** – verify browser or terminal has mic/audio permissions and that your Google API keys are valid (watch backend logs for quota/auth errors).

---

