# Voice preset files

Reference audio for Chatterbox voice cloning. Each file is served at `/voices/<name>.<ext>`
and used as the voice-cloning reference in the web UI.

| Filename      | Preset |
|---------------|--------|
| `steve.wav`   | steve  |
| `austin.wav`  | austin |
| `dakota.wav`  | dakota |
| `trump.wav`   | trump  |

## Requirements

- Format: WAV (PCM, any sample rate) or MP3
- Duration: 6–30 seconds of clean speech works best
- Max upload size: 10 MB (enforced in UI)
- No background music or heavy noise

Files are fetched by the browser, base64-encoded client-side, and sent with each TTS request.
