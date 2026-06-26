# Voice Clone

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Free and open source voice cloning tool powered by [Chatterbox](https://github.com/resemble-ai/chatterbox). Use it, fork it, and modify it under the [MIT License](LICENSE).

## What it does

- Clone any voice from a short reference clip (6–30 seconds of clean speech works best)
- Record your own voice from the browser mic
- **Download recordings** as audio files and re-upload them later
- 29 preset celebrity/character voices included
- Sentence-by-sentence streaming synthesis with live playback
- Download synthesized output as WAV
- **OpenAI-compatible remote API** — send text, get audio back (streaming or single file)
- **API key auth** — generate keys at `/admin` for programmatic access
- **Cloudflare Quick Tunnel** — expose the API publicly with no port forwarding (optional)

### Saving a recording

1. Click **● record**, speak for 6–30 seconds, then stop.
2. Download the file:
   - Click **↓** on the recording pill in the voice row, or
   - Click **↓ save** next to `using <name>` when that recording is active, or
   - Open **● record** again → **saved recordings** → **↓** on the row.
3. Reuse later with **↑ upload** on the main screen.

Recordings are stored in your browser (`localStorage`) until you delete them; downloading gives you a portable copy.

## License

This project is [MIT licensed](LICENSE) — free for personal and commercial use. Preset voice clips are for demonstration; you are responsible for how you use voice cloning.

## AI attestation

This project was built with human direction and AI assistance. Attestation via [`attest-client`](https://www.npmjs.com/package/attest-client) on [attest.97115104.com](https://attest.97115104.com):

[![attested: collab](https://img.shields.io/badge/attested-collab-blueviolet)](https://attest.97115104.com/s/9uccr2j5)

| | |
|---|---|
| **Verify** | [attest.97115104.com/s/9uccr2j5](https://attest.97115104.com/s/9uccr2j5) |
| **Regenerate** | `npm install && npm run attest` |

## Quick start

**One command** — starts Docker (builds the image on first run only), opens a Cloudflare Quick Tunnel, and opens your browser:

```bash
./deploy-locally.sh
```

Open http://localhost:8004

The browser opens as soon as the container is up. Model download and load progress is shown on the loading page — the script does not block on that.

On first run, `./deploy-locally.sh` also creates `.env` from `.env.example` if it does not exist.

| Platform | Runtime |
|----------|---------|
| macOS | CPU in Docker (GPU passthrough not available) |
| Linux, no NVIDIA GPU | CPU in Docker |
| Linux + NVIDIA + nvidia-container-toolkit | CUDA in Docker |

```bash
# Force rebuild image
./deploy-locally.sh --build

# Skip build (fail if image missing)
./deploy-locally.sh --no-build

# Stop Docker services
./deploy-locally.sh --stop

# Run in background (container + tunnel keep running)
./deploy-locally.sh --detach

# Force CPU or GPU on Linux
USE_GPU=0 ./deploy-locally.sh
USE_GPU=1 ./deploy-locally.sh

# Local only — skip Cloudflare tunnel
./deploy-locally.sh --no-tunnel
```

**Flags:** `--stop`, `--build`, `--no-build`, `--detach`, `--no-open`, `--no-tunnel`

When running in the foreground (default), press **Ctrl+C** to stop the tunnel. The Docker container keeps running — use `./deploy-locally.sh --stop` to shut it down.

### Remote access (Cloudflare Quick Tunnel)

By default, `./deploy-locally.sh` starts a [Cloudflare Quick Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/) — no Cloudflare account required. The public URL is printed in the terminal and saved to the admin dashboard.

Use `--no-tunnel` for local-only deployments.

**Before exposing a tunnel**, copy `.env.example` to `.env` and change the admin password and JWT secret:

```bash
cp .env.example .env
# edit ADMIN_PASSWORD and JWT_SECRET
```

### First startup

- **Image build** (first run only): several minutes while Docker pulls the base image and installs dependencies.
- **Model download** (first run per volume): ~3 GB into the `huggingface-cache` Docker volume. Progress is shown in the browser loading page.
- **Re-runs**: fast — cached image and cached model weights.

## Admin dashboard

Open http://localhost:8004/admin

Default login: `admin` / `password` (configured via `.env`).

| Feature | Description |
|---------|-------------|
| **API keys** | Create, revoke, and copy `sk-voice-…` keys |
| **Voices** | Upload shared custom voices (available to all API keys) |
| **Requests** | Audit log of API synthesis requests |
| **Dashboard** | Model status and Cloudflare tunnel URL |

The main web UI at `/` auto-configures a local bootstrap API key on first load. This key is only returned by `/setup/status` for requests from the local/private network — it is not exposed to remote tunnel clients.

## Authentication

| Route | Auth |
|-------|------|
| `/`, `/admin`, `/health`, `/live`, `/attestation.json` | None |
| `/voices/*` (preset audio files) | None |
| `GET /setup/status` | None (bootstrap key included for local requests only) |
| `/v1/*`, `/tts/*`, `/api/voices` | API key — `Authorization: Bearer sk-voice-…` |
| `/admin/*` (except login) | Admin JWT from `POST /admin/login` |
| `POST /setup/tunnel` | Admin JWT |

API keys use the prefix `sk-voice-`. A separate bootstrap key (`sk-voice-local-…`) is created automatically for the local web UI.

## OpenAI-compatible API

Base URL: `http://localhost:8004/v1` (or `https://YOUR-TUNNEL.trycloudflare.com/v1` when using a tunnel).

All `/v1/*` endpoints require an API key header:

```
Authorization: Bearer sk-voice-YOUR_KEY
```

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/models` | GET | List voices as OpenAI model objects |
| `/v1/voices` | GET | List available voices (presets + uploads) |
| `/v1/voices` | POST | Upload a custom voice (multipart form) |
| `/v1/voices/{id}` | DELETE | Delete a voice you uploaded |
| `/v1/audio/speech` | POST | Synthesize speech |

### Voice selection (`model` field)

The `model` parameter selects the reference voice:

| Value | Source |
|-------|--------|
| Preset name (e.g. `fry`) | File in `server/voices/` |
| Uploaded ID (e.g. `voice-a1b2c3d4e5f6`) | Voice uploaded via `/v1/voices` or the admin dashboard |

Use `GET /v1/models` or `GET /v1/voices` to list available options.

### `POST /v1/audio/speech`

Request body:

```json
{
  "model": "fry",
  "input": "Hello, this is a test.",
  "response_format": "wav",
  "stream": false,
  "exaggeration": 0.5,
  "cfg_weight": 0.5,
  "temperature": 0.8
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `model` | Yes | Preset voice name or uploaded voice ID |
| `input` | Yes | Text to synthesize |
| `response_format` | No | `wav` (default), `mp3`, or `opus` |
| `stream` | No | `true` for sentence-by-sentence SSE streaming |
| `exaggeration` | No | Expressiveness 0–2 (default `0.5`) |
| `cfg_weight` | No | Guidance weight 0–1 (default `0.5`) |
| `temperature` | No | Sampling temperature (default `0.8`) |

**Non-streaming** returns raw audio bytes with the appropriate `Content-Type`.

**Streaming** (`"stream": true`) returns Server-Sent Events. Each chunk is a JSON object with base64-encoded WAV audio; the stream ends with `data: [DONE]`:

```
data: {"object":"speech.chunk","index":0,"total":2,"audio":"<base64 wav>"}
data: {"object":"speech.chunk","index":1,"total":2,"audio":"<base64 wav>"}
data: [DONE]
```

### Examples

```bash
# List voices as models
curl http://localhost:8004/v1/models \
  -H "Authorization: Bearer sk-voice-YOUR_KEY"

# Non-streaming speech
curl http://localhost:8004/v1/audio/speech \
  -H "Authorization: Bearer sk-voice-YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"fry","input":"Hello world.","response_format":"wav"}' \
  --output speech.wav

# Streaming speech (SSE)
curl -N http://localhost:8004/v1/audio/speech \
  -H "Authorization: Bearer sk-voice-YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"fry","input":"Hello world. This streams by sentence.","stream":true}'

# Upload a custom voice (owned by your API key)
curl http://localhost:8004/v1/voices \
  -H "Authorization: Bearer sk-voice-YOUR_KEY" \
  -F "file=@my-voice.wav" -F "name=my-voice"
```

### Python SDK

Works for **non-streaming** requests. Streaming uses custom SSE (see `curl` example above).

```python
from pathlib import Path
from openai import OpenAI

client = OpenAI(
    api_key="sk-voice-YOUR_KEY",
    base_url="http://localhost:8004/v1",  # or your tunnel URL + /v1
)

response = client.audio.speech.create(
    model="fry",
    input="Hello world.",
    response_format="wav",
)
response.stream_to_file(Path("speech.wav"))
```

## Web UI & legacy API

These endpoints power the browser UI. They also require an API key (the local UI obtains a bootstrap key automatically).

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tts/stream` | POST | SSE sentence streaming (legacy format) |
| `/tts/synthesize` | POST | Single-shot audio response |
| `/api/voices` | GET | List all voices (presets + uploads) |
| `/api/voices/{id}/audio` | GET | Download voice audio (preset or upload) |

Legacy `/tts/stream` SSE format (used by the web UI):

```
data: {"i":0,"total":2,"audio":"<base64 wav>"}
data: {"done":true}
```

### Setup & health

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Model ready (503 while loading) |
| `/live` | GET | Process up (container running) |
| `/setup/status` | GET | Tunnel URL, model status, local bootstrap key |
| `/setup/tunnel` | POST | Register tunnel URL (admin JWT) |

## Environment variables

Set these in `.env` (read by Docker Compose) or pass directly to the container.

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8004` | Host port mapped to the container |
| `USE_GPU` | auto | `1`/`0` to force GPU overlay on/off (Linux only, deploy script) |
| `ADMIN_USERNAME` | `admin` | Admin login username |
| `ADMIN_PASSWORD` | `password` | Admin login password |
| `JWT_SECRET` | `voice-clone-change-me` | JWT signing secret — **change in production** |
| `DATA_DIR` | `/app/data` (in Docker) | SQLite database and uploaded voice files |
| `CB_EXAGGERATION` | `0.5` | Default expressiveness (0–2) |
| `CB_CFG_WEIGHT` | `0.5` | Default guidance weight (0–1) |
| `CB_TEMPERATURE` | `0.8` | Default sampling temperature |
| `TTS_DEVICE` | auto | Force device: `cpu`, `cuda`, or `mps` |
| `HF_HOME` | `/data/huggingface` | Hugging Face model cache directory |

Persistent data is stored on the host at:

- `./data/` — API keys, admin accounts, uploaded voices, tunnel URL, request log
- Docker volume `huggingface-cache` — Chatterbox model weights (~3 GB)

## Project layout

```
voice-clone/
├── deploy-locally.sh      # Docker start + Cloudflare tunnel
├── .env.example           # admin credentials and JWT secret
├── package.json           # attest-client for AI attestation
├── Dockerfile             # multi-target: cpu | cuda
├── docker-compose.yml     # base service
├── docker-compose.gpu.yml # GPU overlay (Linux + NVIDIA)
├── data/                  # created on first run (gitignored)
├── server/
│   ├── tts_server.py      # FastAPI app entry
│   ├── tts_engine.py      # Chatterbox inference
│   ├── db.py              # SQLite persistence
│   ├── auth.py            # JWT + API keys
│   └── routes/            # /v1, /admin, /setup
├── server/voices/         # preset reference audio
├── web/index.html         # main UI
├── web/admin.html         # admin dashboard
└── scripts/
    └── attest.mjs         # npm run attest
```

## Scripts

| Script | Purpose |
|--------|---------|
| `./deploy-locally.sh` | Build, start Docker, optional Cloudflare tunnel |
| `npm run attest` | Regenerate AI attestation badge |
