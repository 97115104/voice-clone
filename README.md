# Voice Clone

Standalone voice cloning tool powered by [Chatterbox](https://github.com/resemble-ai/chatterbox). Extracted from the [429 Inference Network](https://github.com/97115104/429-inference-network) voice stack.

## What it does

- Clone any voice from a short reference clip (6–30 seconds of clean speech works best)
- 28 preset celebrity/character voices included
- Sentence-by-sentence streaming synthesis with live playback
- Download the full output as WAV

## Requirements

- Python 3.10+
- NVIDIA GPU recommended (CUDA). CPU works but is slow.
- `ffmpeg` on PATH (for MP3/Opus output)

## Quick start

Install everything (system deps, Python packages, Chatterbox model):

```bash
./install
```

Then start the app:

```bash
./scripts/deploy-locally.sh
```

Or manually:

```bash
python -m venv .venv
source .venv/bin/activate
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt

./scripts/start.sh
```

Open http://127.0.0.1:8004

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/health` | GET | Server status |
| `/api/voices` | GET | List preset voices |
| `/voices/<name>.<ext>` | GET | Preset voice file |
| `/tts/stream` | POST | SSE sentence streaming |
| `/tts/synthesize` | POST | Single-shot audio |

**Stream request:**

```json
{
  "text": "Hello world",
  "voice": "data:audio/wav;base64,...",
  "exaggeration": 0.5,
  "cfg_weight": 0.5,
  "temperature": 0.8,
  "format": "wav"
}
```

**Stream response (SSE):**

```
data: {"i":0,"total":3,"audio":"<base64 WAV>"}

data: {"done":true}
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8004` | Server port |
| `TTS_DEVICE` | `cuda` or `cpu` | Inference device |
| `CB_EXAGGERATION` | `0.5` | Default expressiveness (0–2) |
| `CB_CFG_WEIGHT` | `0.5` | Default guidance weight (0–1) |
| `CB_TEMPERATURE` | `0.8` | Default sampling temperature |

## Voice presets

Preset files live in `server/voices/`. Default voice is `fry` (see `server/voices/default.txt`).

Add your own reference clips as `.wav` or `.mp3` files — they appear automatically in the UI picker.

## Project layout

```
voice-clone/
├── install                  # Install all dependencies + model
├── server/
│   ├── tts_server.py    # Chatterbox FastAPI server
│   └── voices/          # Preset reference audio
├── web/
│   └── index.html       # Browser UI
├── scripts/
│   ├── deploy-locally.sh  # One-shot local setup + browser launch
│   └── start.sh
└── requirements.txt
```
