# Voice Clone

Standalone voice cloning tool powered by [Chatterbox](https://github.com/resemble-ai/chatterbox).

## What it does

- Clone any voice from a short reference clip (6–30 seconds of clean speech works best)
- Record your own voice from the browser mic
- 28 preset celebrity/character voices included
- Sentence-by-sentence streaming synthesis with live playback
- Download the full output as WAV

## AI attestation

This project was built with human direction and AI assistance. Attestation via [`attest-client`](https://www.npmjs.com/package/attest-client) on [attest.97115104.com](https://attest.97115104.com):

[![attested: collab](https://img.shields.io/badge/attested-collab-blueviolet)](https://attest.97115104.com/s/9uccr2j5)

| | |
|---|---|
| **Verify** | [attest.97115104.com/s/9uccr2j5](https://attest.97115104.com/s/9uccr2j5) |
| **Regenerate** | `npm install && npm run attest` |

## Quick start

**One command** — auto-detects Docker vs local Python, and GPU vs CPU:

```bash
./install
./scripts/deploy.sh
```

Open http://localhost:8004

| Platform | Install | Start |
|----------|---------|-------|
| macOS / Linux | `./install` | `./scripts/deploy.sh` |
| Windows (Docker Desktop) | `.\install.ps1` | `.\scripts\deploy.ps1` |
| Windows (Git Bash / WSL) | `./install --local` | `./scripts/deploy.sh --local` |

### How auto-detection works

- **Install (`./install`)** — local Python on Apple Silicon / NVIDIA hosts (MPS/CUDA); Docker on other machines when Docker is running
- **Deploy (`./scripts/deploy.sh`)** — same logic: local when host GPU/MPS is available, otherwise Docker
- **GPU** — on Linux/Windows with NVIDIA + Docker GPU support, uses CUDA automatically. macOS Docker always uses CPU. Apple Silicon local installs use MPS when available.

### Manual modes

```bash
# Docker (builds image on first run, CPU on macOS)
./install --docker
./scripts/deploy.sh --docker

# Docker in background (after first build)
./scripts/deploy.sh --docker --detach --no-build

# Local Python only (recommended on Apple Silicon — uses MPS)
./install --local
./scripts/deploy.sh --local

# Docker with NVIDIA GPU (Linux/Windows only)
./scripts/deploy-docker.sh

# Stop everything
./scripts/deploy.sh --stop
```

On **Apple Silicon Macs**, `./scripts/deploy.sh` defaults to **local MPS** (much faster than Docker CPU). Use `--docker` only when you explicitly want a container.

### Windows notes

- **Docker Desktop** (recommended): use `install.ps1` and `scripts\deploy.ps1`
- **Git Bash / WSL**: use the bash scripts (`./install`, `./scripts/deploy.sh`)
- Docker on Windows with WSL2 + NVIDIA can use GPU; Docker on macOS cannot pass GPU to containers

### First startup

The Chatterbox model downloads on first run (Docker volume `huggingface-cache`, or local `~/.cache`). CPU can take 5–15 minutes.

## Scripts

| Script | Purpose |
|--------|---------|
| `./install` | Install (auto Docker or local) |
| `./scripts/deploy.sh` | Start app (auto; add `--docker` or `--local`) |
| `./scripts/deploy-docker.sh` | Docker only |
| `./scripts/deploy-locally.sh` | Local Python only |
| `./scripts/start.sh` | Start local server (no browser) |
| `./scripts/test.sh` | Platform + syntax checks |

**`deploy.sh` flags:** `--docker`, `--local`, `--stop`, `--detach`, `--no-build`, `--no-open`, `--smoke`

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/health` | GET | Server status |
| `/api/voices` | GET | List preset voices |
| `/voices/<name>.<ext>` | GET | Preset voice file |
| `/tts/stream` | POST | SSE sentence streaming |
| `/tts/synthesize` | POST | Single-shot audio |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8004` | Server port |
| `TTS_DEVICE` | auto | `cuda`, `mps` (Apple Silicon), or `cpu` |
| `USE_GPU` | auto | `1`/`0` to force Docker GPU mode |
| `CB_EXAGGERATION` | `0.5` | Expressiveness (0–2) |
| `CB_CFG_WEIGHT` | `0.5` | Guidance weight (0–1) |
| `CB_TEMPERATURE` | `0.8` | Sampling temperature |

## Project layout

```
voice-clone/
├── install / install.ps1
├── package.json           # attest-client for AI attestation
├── Dockerfile
├── docker-compose.yml
├── docker-compose.gpu.yml
├── server/tts_server.py
├── server/voices/
├── web/index.html
└── scripts/
    ├── lib/common.sh      # cross-platform helpers
    ├── deploy.sh          # unified start
    ├── deploy-docker.sh
    ├── deploy-locally.sh
    ├── deploy.ps1         # Windows
    ├── install-deps.sh
    ├── attest.mjs           # npm run attest
    ├── start.sh
    └── test.sh
```
