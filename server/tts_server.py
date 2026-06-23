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
import base64, hashlib, io, json, os, re, subprocess, tempfile, threading, time
from pathlib import Path

import soundfile as sf
import torch
from chatterbox.tts import ChatterboxTTS
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from huggingface_hub import HfApi, hf_hub_download
from pydantic import BaseModel
from tqdm.auto import tqdm

ROOT = Path(__file__).resolve().parent
VOICES_DIR = ROOT / "voices"
WEB_DIR = ROOT.parent / "web"

app = FastAPI(title="Voice Clone", version="1.0.0")

_ready = threading.Event()
_load_error: str | None = None
tts: ChatterboxTTS | None = None
SAMPLE_RATE: int | None = None


def _default_device() -> str:
    if env := os.environ.get("TTS_DEVICE"):
        return env
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


DEVICE = _default_device()
EXAGGERATION = float(os.environ.get("CB_EXAGGERATION", "0.5"))
CFG_WEIGHT    = float(os.environ.get("CB_CFG_WEIGHT",    "0.5"))
TEMPERATURE   = float(os.environ.get("CB_TEMPERATURE",   "0.8"))

_LOAD_MESSAGE = (
    "Downloading and loading the voice model. "
    "First start can take 5–15 minutes on CPU."
)

HF_REPO_ID = "ResembleAI/chatterbox"
MODEL_FILES = [
    "ve.safetensors",
    "t3_cfg.safetensors",
    "s3gen.safetensors",
    "tokenizer.json",
    "conds.pt",
]

_progress_lock = threading.Lock()
_load_progress: dict = {
    "phase": "starting",
    "current_file": "",
    "files_done": 0,
    "files_total": len(MODEL_FILES),
    "bytes_done": 0,
    "bytes_total": 0,
    "percent": 0,
}


def _set_progress(**kwargs) -> None:
    with _progress_lock:
        _load_progress.update(kwargs)
        total = _load_progress["bytes_total"]
        if total > 0:
            _load_progress["percent"] = min(
                99, round(100 * _load_progress["bytes_done"] / total)
            )


def _progress_snapshot() -> dict:
    with _progress_lock:
        return dict(_load_progress)


def _model_file_sizes() -> dict[str, int]:
    try:
        infos = HfApi().get_paths_info(HF_REPO_ID, paths=MODEL_FILES, repo_type="model")
        return {info.path: info.size for info in infos if info.size}
    except Exception:
        return {}


def _make_download_tqdm(completed_bytes: int, total_bytes: int, file_name: str, file_count: int):
    base = tqdm

    class DownloadTqdm(base):
        def update(self, n=1):
            result = super().update(n)
            if total_bytes > 0:
                _set_progress(
                    phase="downloading",
                    current_file=file_name,
                    bytes_done=completed_bytes + self.n,
                    percent=min(99, round(100 * (completed_bytes + self.n) / total_bytes)),
                )
            else:
                file_frac = (self.n / self.total) if self.total else 1.0
                overall = ((file_count - 1) + file_frac) / len(MODEL_FILES)
                _set_progress(
                    phase="downloading",
                    current_file=file_name,
                    files_done=file_count - 1,
                    percent=min(99, round(100 * overall)),
                )
            return result

    return DownloadTqdm


def _download_model_files() -> Path:
    sizes = _model_file_sizes()
    total_bytes = sum(sizes.get(name, 0) for name in MODEL_FILES)
    _set_progress(
        phase="downloading",
        files_total=len(MODEL_FILES),
        bytes_total=total_bytes,
        bytes_done=0,
        percent=0,
    )

    completed_bytes = 0
    local_dir: Path | None = None
    for index, filename in enumerate(MODEL_FILES, start=1):
        _set_progress(current_file=filename, files_done=index - 1)
        tqdm_class = _make_download_tqdm(completed_bytes, total_bytes, filename, index)
        local_path = hf_hub_download(
            repo_id=HF_REPO_ID,
            filename=filename,
            tqdm_class=tqdm_class,
        )
        local_dir = Path(local_path).parent
        completed_bytes += sizes.get(filename, 0)
        _set_progress(files_done=index, bytes_done=completed_bytes)

    assert local_dir is not None
    return local_dir


def _require_ready() -> None:
    if _load_error:
        raise HTTPException(status_code=500, detail=_load_error)
    if not _ready.is_set():
        raise HTTPException(status_code=503, detail="Model still loading")


def _load_model() -> None:
    global tts, SAMPLE_RATE, _load_error
    try:
        print(f"[chatterbox] loading model on {DEVICE}...", flush=True)
        _t0 = time.time()
        model_dir = _download_model_files()
        _set_progress(phase="loading", current_file="weights", percent=99)
        tts = ChatterboxTTS.from_local(model_dir, DEVICE)
        SAMPLE_RATE = tts.sr
        print(f"[chatterbox] model loaded in {time.time()-_t0:.1f}s  sr={SAMPLE_RATE}", flush=True)

        warmup_wav = VOICES_DIR / "warmup.wav"
        if warmup_wav.exists():
            _set_progress(phase="warming up", current_file="warmup", percent=99)
            print("[chatterbox] warming up...", flush=True)
            tts.generate("Warmup.", audio_prompt_path=str(warmup_wav))
            print("[chatterbox] warmup complete", flush=True)

        _set_progress(phase="ready", percent=100)
        _ready.set()
    except Exception as exc:
        _load_error = str(exc)
        print(f"[chatterbox] model load failed: {exc}", flush=True)


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
    header, b64 = (data_url.split(",", 1) if "," in data_url else ("", data_url))
    mime = "audio/wav"
    if header.startswith("data:"):
        mime = header[5:].split(";")[0].lower()

    raw = base64.b64decode(b64)
    ext_map = {
        "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav",
        "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
        "audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a",
    }
    ext = ext_map.get(mime, ".wav")

    tmp_in = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    tmp_in.write(raw)
    tmp_in.close()

    if ext == ".wav":
        return tmp_in.name

    tmp_out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_out.close()
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", tmp_in.name, "-ar", "24000", "-ac", "1", tmp_out.name, "-loglevel", "error"],
        capture_output=True,
    )
    os.unlink(tmp_in.name)
    if result.returncode != 0:
        os.unlink(tmp_out.name)
        raise RuntimeError(f"ffmpeg convert failed: {result.stderr.decode()}")
    return tmp_out.name


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
    _require_ready()
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
    _require_ready()
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
    if _load_error:
        return JSONResponse(
            {"status": "error", "error": _load_error, "device": DEVICE},
            status_code=500,
        )
    if not _ready.is_set():
        progress = _progress_snapshot()
        return JSONResponse(
            {
                "status": "loading",
                "device": DEVICE,
                "message": _LOAD_MESSAGE,
                "progress": progress,
            },
            status_code=503,
        )
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
    _require_ready()
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


@app.get("/attestation.json")
async def attestation():
    path = WEB_DIR / "attestation.json"
    if path.exists():
        return FileResponse(path, media_type="application/json")
    return Response(content="{}", media_type="application/json")


@app.get("/")
async def index():
    if not _ready.is_set():
        loading_path = WEB_DIR / "loading.html"
        if loading_path.exists():
            return FileResponse(loading_path)
        return Response(
            content=_LOAD_MESSAGE,
            media_type="text/plain",
            status_code=503,
        )
    index_path = WEB_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return Response(content="Voice clone server running. Add web/index.html for the UI.", media_type="text/plain")


if VOICES_DIR.exists():
    app.mount("/voices", StaticFiles(directory=str(VOICES_DIR)), name="voice-files")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8004))
    threading.Thread(target=_load_model, name="model-loader", daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
