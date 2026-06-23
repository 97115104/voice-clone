"""
Standalone Chatterbox voice cloning server.

GitHub: https://github.com/resemble-ai/chatterbox

Quality knobs (per-request or env defaults):
  exaggeration  0.0–2.0  — expressiveness; 0.5 = neutral, 0.7+ = animated
  cfg_weight    0.0–1.0  — classifier-free guidance; lower = more faithful to voice
  temperature   0.05–2.0 — sampling temperature; 0.8 = default

Install:
  pip install -r requirements.txt
"""
import base64, hashlib, io, json, os, re, subprocess, tempfile, time
from pathlib import Path

import soundfile as sf
import torch
from chatterbox.tts import ChatterboxTTS
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
VOICES_DIR = ROOT / "voices"
WEB_DIR = ROOT.parent / "web"

app = FastAPI(title="Voice Clone", version="1.0.0")

DEVICE = os.environ.get("TTS_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
EXAGGERATION = float(os.environ.get("CB_EXAGGERATION", "0.5"))
CFG_WEIGHT    = float(os.environ.get("CB_CFG_WEIGHT",    "0.5"))
TEMPERATURE   = float(os.environ.get("CB_TEMPERATURE",   "0.8"))

print(f"[chatterbox] loading model on {DEVICE}...", flush=True)
_t0 = time.time()
tts = ChatterboxTTS.from_pretrained(device=DEVICE)
SAMPLE_RATE = tts.sr
print(f"[chatterbox] model loaded in {time.time()-_t0:.1f}s  sr={SAMPLE_RATE}", flush=True)

# Warmup — eliminates cold-start latency on the first real request.
_WARMUP_WAV = VOICES_DIR / "warmup.wav"
if _WARMUP_WAV.exists():
    print("[chatterbox] warming up...", flush=True)
    tts.generate("Warmup.", audio_prompt_path=str(_WARMUP_WAV))
    print("[chatterbox] warmup complete", flush=True)


class TTSRequest(BaseModel):
    text: str
    voice: str                  # base64 data URL of reference WAV
    exaggeration: float = 0.5   # expressiveness (0–2); now used by Chatterbox
    cfg_weight: float   = 0.5   # guidance weight (0–1); now used by Chatterbox
    temperature: float  = 0.8   # sampling temperature; now used by Chatterbox
    format: str         = "wav" # "wav" | "mp3" | "opus"
    speed: float        = 1.0   # unused by Chatterbox; kept for API compat
    nfe_steps: int      = 0     # unused by Chatterbox; kept for API compat


def _decode_voice(data_url: str) -> str:
    b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.write(base64.b64decode(b64))
    tmp.close()
    return tmp.name


# Voice embedding cache: md5(voice_bytes:exaggeration) → tts.conds
# Skips prepare_conditionals on repeated requests with the same voice.
_CONDS_CACHE: dict[str, object] = {}
_CONDS_CACHE_MAX = 4

def _prepare_conditionals_cached(data_url: str, exaggeration: float) -> None:
    key = hashlib.md5(f"{data_url}:{exaggeration:.3f}".encode()).hexdigest()
    if key in _CONDS_CACHE:
        tts.conds = _CONDS_CACHE[key]
        return
    ref_path = _decode_voice(data_url)
    try:
        tts.prepare_conditionals(ref_path, exaggeration=exaggeration)
    finally:
        os.unlink(ref_path)
    if len(_CONDS_CACHE) >= _CONDS_CACHE_MAX:
        del _CONDS_CACHE[next(iter(_CONDS_CACHE))]
    _CONDS_CACHE[key] = tts.conds


def _tensor_to_bytes(wav: torch.Tensor, sr: int, fmt: str) -> bytes:
    # squeeze [1, N] → [N] numpy array for soundfile
    arr = wav.squeeze(0).cpu().numpy()
    wav_buf = io.BytesIO()
    sf.write(wav_buf, arr, sr, format="WAV")
    wav_bytes = wav_buf.getvalue()
    if fmt in ("mp3", "opus"):
        codec   = "libmp3lame" if fmt == "mp3" else "libopus"
        out_fmt = "mp3"        if fmt == "mp3" else "ogg"
        result = subprocess.run(
            ["ffmpeg", "-f", "wav", "-i", "pipe:0",
             "-c:a", codec, "-f", out_fmt, "pipe:1", "-loglevel", "error"],
            input=wav_bytes, capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()}")
        return result.stdout
    return wav_bytes


def _infer(text: str, exaggeration: float, cfg_weight: float, temperature: float) -> tuple[torch.Tensor, int]:
    wav = tts.generate(
        text,
        exaggeration=exaggeration,
        cfg_weight=cfg_weight,
        temperature=temperature,
    )
    return wav, SAMPLE_RATE


_MD_STRIP = [
    (re.compile(r"```[\s\S]*?```"), ""),          # fenced code blocks
    (re.compile(r"`[^`]+`"), ""),                  # inline code
    (re.compile(r"\*+([^*]+)\*+"), r"\1"),         # bold / italic
    (re.compile(r"^#+\s*", re.MULTILINE), ""),     # ATX headings
    (re.compile(r"\[([^\]]+)\]\([^\)]+\)"), r"\1"),# markdown links
]

def _split_sentences(text: str) -> list[str]:
    """Split text into utterance-sized chunks for streaming TTS."""
    for pat, repl in _MD_STRIP:
        text = pat.sub(repl, text)
    sentences: list[str] = []
    for para in re.split(r"\n{2,}", text.strip()):
        para = para.replace("\n", " ").strip()
        if not para:
            continue
        for s in re.split(r"(?<=[.!?])\s+", para):
            s = s.strip()
            if len(s) > 4:
                sentences.append(s)
    return sentences or [text.strip()]


@app.post("/tts/synthesize")
async def synthesize(req: TTSRequest):
    _prepare_conditionals_cached(req.voice, req.exaggeration)
    wav, sr = _infer(req.text, req.exaggeration, req.cfg_weight, req.temperature)
    audio_bytes = _tensor_to_bytes(wav, sr, req.format)
    media_type = {"mp3": "audio/mpeg", "opus": "audio/ogg", "wav": "audio/wav"}.get(req.format, "audio/wav")
    return Response(content=audio_bytes, media_type=media_type)


@app.post("/tts/stream")
async def stream(req: TTSRequest):
    """Sentence-streaming TTS: synthesizes sentence-by-sentence and returns
    SSE events so clients can start playing the first sentence immediately
    instead of waiting for the full response to be synthesized."""
    sentences = _split_sentences(req.text)
    total = len(sentences)

    # Pre-condition the voice model once — amortised (and cached) across requests
    # with the same voice so subsequent requests skip the encoder entirely.
    _prepare_conditionals_cached(req.voice, req.exaggeration)

    def generate():
        for i, sentence in enumerate(sentences):
            wav = tts.generate(
                sentence,
                exaggeration=req.exaggeration,
                cfg_weight=req.cfg_weight,
                temperature=req.temperature,
            )
            audio_b64 = base64.b64encode(_tensor_to_bytes(wav, SAMPLE_RATE, "wav")).decode()
            yield f"data: {json.dumps({'i': i, 'total': total, 'audio': audio_b64})}\n\n"
        yield 'data: {"done":true}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "backend": "chatterbox",
        "version": "1.0.0",
        "device": DEVICE,
        "sample_rate": SAMPLE_RATE,
        "exaggeration": EXAGGERATION,
        "cfg_weight": CFG_WEIGHT,
        "temperature": TEMPERATURE,
    }


_VOICE_EXCLUDE = {"warmup.wav", "default.txt", "README.md"}


@app.get("/api/voices")
async def list_voices():
    voices = []
    for path in sorted(VOICES_DIR.iterdir()):
        if path.name in _VOICE_EXCLUDE or path.suffix.lower() not in {".mp3", ".wav"}:
            continue
        voices.append({"name": path.stem, "ext": path.suffix.lstrip(".").lower()})
    return voices


@app.get("/voices/default.txt")
async def default_voice():
    default_path = VOICES_DIR / "default.txt"
    if default_path.exists():
        return Response(content=default_path.read_text().strip(), media_type="text/plain")
    return Response(content="fry", media_type="text/plain")


@app.get("/")
async def index():
    index_path = WEB_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return Response(content="Voice clone server running. Add web/index.html for the UI.", media_type="text/plain")


if VOICES_DIR.exists():
    app.mount("/voices", StaticFiles(directory=str(VOICES_DIR)), name="voice-files")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8004))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
