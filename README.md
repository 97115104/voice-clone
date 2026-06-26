# Voice Clone

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Free and open source voice cloning tool powered by [Chatterbox](https://github.com/resemble-ai/chatterbox). Use it, fork it, and modify it under the [MIT License](LICENSE).

## What it does

- Clone any voice from a short reference clip (6–30 seconds of clean speech works best)
- Record your own voice from the browser mic
- **Download recordings** as audio files and re-upload them later
- 28 preset celebrity/character voices included
- Sentence-by-sentence streaming synthesis with live playback
- Download synthesized output as WAV

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

**One command** — starts Docker (builds the image on first run only), opens your browser:

```bash
./deploy-locally.sh
```

Open http://localhost:8004

The browser opens as soon as the container is up. Model download and load progress is shown in the loading page — the script does not block on that.

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

# Stop
./deploy-locally.sh --stop

# Force CPU or GPU on Linux
USE_GPU=0 ./deploy-locally.sh
USE_GPU=1 ./deploy-locally.sh
```

### First startup

- **Image build** (first run only): several minutes while Docker pulls the base image and installs dependencies. A spinner shows progress.
- **Model download** (first run per volume): ~3 GB into the `huggingface-cache` Docker volume. Progress is shown in the browser loading page.
- **Re-runs**: fast — cached image and cached model weights.

## Scripts

| Script | Purpose |
|--------|---------|
| `./deploy-locally.sh` | Build and start via Docker |
| `npm run attest` | Regenerate AI attestation badge |

**Flags:** `--stop`, `--build`, `--no-build`, `--detach`, `--no-open`

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/live` | GET | Process up (container running) |
| `/health` | GET | Model ready (503 while loading) |
| `/api/voices` | GET | List preset voices |
| `/voices/<name>.<ext>` | GET | Preset voice file |
| `/tts/stream` | POST | SSE sentence streaming |
| `/tts/synthesize` | POST | Single-shot audio |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8004` | Server port |
| `USE_GPU` | auto | `1`/`0` to force GPU overlay on/off (Linux only) |
| `CB_EXAGGERATION` | `0.5` | Expressiveness (0–2) |
| `CB_CFG_WEIGHT` | `0.5` | Guidance weight (0–1) |
| `CB_TEMPERATURE` | `0.8` | Sampling temperature |

## Project layout

```
voice-clone/
├── deploy-locally.sh      # start via Docker (auto CPU/GPU)
├── package.json           # attest-client for AI attestation
├── Dockerfile             # multi-target: cpu | cuda
├── docker-compose.yml     # base service
├── docker-compose.gpu.yml # GPU overlay (Linux + NVIDIA)
├── server/tts_server.py
├── server/voices/
├── web/index.html
└── scripts/
    └── attest.mjs         # npm run attest
```
