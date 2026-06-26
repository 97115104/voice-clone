# Voice preset files

Reference audio for Chatterbox voice cloning. Each file is served at `/voices/<name>.<ext>` and listed by the API as a model/voice option.

## Included presets (29)

| Name | File |
|------|------|
| alan | `alan.mp3` |
| austin | `austin.wav` |
| bateman | `bateman.mp3` |
| bill | `bill.mp3` |
| buffett | `buffett.mp3` |
| crestfallen | `crestfallen.mp3` |
| dakota | `dakota.wav` |
| david | `david.mp3` |
| dumbledore | `dumbledore.mp3` |
| elizabeth | `elizabeth.mp3` |
| elon | `elon.mp3` |
| fry | `fry.mp3` (default) |
| gollum | `gollum.mp3` |
| helena | `helena.wav` |
| hillary | `hillary.mp3` |
| ian | `ian.mp3` |
| jack | `jack.mp3` |
| jeremy | `jeremy.mp3` |
| jim | `jim.mp3` |
| joker | `joker.mp3` |
| liam | `liam.mp3` |
| mrbeast | `mrbeast.mp3` |
| obama | `obama.mp3` |
| oprah | `oprah.mp3` |
| patrick | `patrick.mp3` |
| samuel | `samuel.mp3` |
| steve | `steve.wav` |
| trump | `trump.wav` |
| zac | `zac.mp3` |

Default preset: `fry` (see `default.txt`).

Excluded from the voice list: `warmup.wav` (model warmup only).

## Usage

| Context | How presets are used |
|---------|---------------------|
| **Web UI** | Selected in the voice picker; sent as a base64 data URL with each TTS request |
| **API** | Pass the filename stem as `model` in `POST /v1/audio/speech` (e.g. `"model": "fry"`) |
| **Listing** | `GET /v1/models`, `GET /v1/voices`, or `GET /api/voices` (includes presets + uploads) |

## Requirements

- Format: WAV (PCM, any sample rate) or MP3
- Duration: 6–30 seconds of clean speech works best
- Max upload size: 10 MB (enforced in the web UI)
- No background music or heavy noise

Files are converted to 24 kHz mono WAV internally when needed.

## Adding presets

Drop a `.wav` or `.mp3` file in this directory named after the voice (e.g. `fry.wav`). The stem becomes the model ID. Set the default preset name in `default.txt` (one line, no extension).

## Custom voices via API

For voices not stored here, upload via:

- `POST /v1/voices` (API key) — owned by your key
- Admin dashboard → Voices (shared with all API keys)

Uploaded voices receive an ID like `voice-a1b2c3d4e5f6` and are stored in `data/voices/`.
