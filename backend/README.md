# Clean Backend

A pure Python backend for real-time voice conversation using FastAPI, Google Cloud Speech-to-Text, Gemini, and Google Cloud Text-to-Speech.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up Google Cloud credentials:
   - Create a service account key file
   - Set `GOOGLE_APPLICATION_CREDENTIALS` in `.env` to the absolute path of your key file

3. Copy `.env.example` to `.env` and configure:
```bash
cp .env.example .env
```

4. Run the server:
```bash
uvicorn clean.backend.app:app --reload
```

## Features

- Real-time ASR via WebSocket (`/ws/audio-in/{session_id}`)
- LLM response generation with sentence chunking
- Streaming TTS via WebSocket (`/ws/audio-out/{session_id}`)
- In-memory session management
- Token guard for conversation turn management
- RAG support (optional, requires SentenceTransformer and Qdrant)

## API Endpoints

- `POST /sessions` - Create a new session
- `DELETE /sessions/{session_id}` - Delete a session
- `POST /respond` - Send text input for LLM processing
- `GET /config` - Get character and script configurations
- `GET /healthz` - Health check
- `WebSocket /ws/audio-in/{session_id}` - Stream audio input for ASR
- `WebSocket /ws/audio-out/{session_id}` - Receive audio output from TTS

## Examples

See `clean/examples/` for client scripts:
- `voice_client.py` - Minimal voice client
- `launch.py` - Microphone test script with audio playback

