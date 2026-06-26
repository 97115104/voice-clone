"""Chatterbox TTS engine: model loading, inference, and voice resolution."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import soundfile as sf
import torch
from chatterbox.tts import ChatterboxTTS
from fastapi import HTTPException
from huggingface_hub import HfApi, hf_hub_download
from tqdm.auto import tqdm

from server import db

ROOT = Path(__file__).resolve().parent
VOICES_DIR = ROOT / "voices"
VOICE_EXCLUDE = {"warmup.wav", "default.txt", "README.md"}

_ready = threading.Event()
_load_error: str | None = None
tts: ChatterboxTTS | None = None
SAMPLE_RATE: int | None = None

DEVICE = os.environ.get("TTS_DEVICE") or (
    "cuda" if torch.cuda.is_available()
    else "mps" if hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    else "cpu"
)
EXAGGERATION = float(os.environ.get("CB_EXAGGERATION", "0.5"))
CFG_WEIGHT = float(os.environ.get("CB_CFG_WEIGHT", "0.5"))
TEMPERATURE = float(os.environ.get("CB_TEMPERATURE", "0.8"))

LOAD_MESSAGE = (
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

_CONDS_CACHE: dict[str, object] = {}
_CONDS_CACHE_MAX = 4

_MD_STRIP = [
    (re.compile(r"```[\s\S]*?```"), ""),
    (re.compile(r"`[^`]+`"), ""),
    (re.compile(r"\*+([^*]+)\*+"), r"\1"),
    (re.compile(r"^#+\s*", re.MULTILINE), ""),
    (re.compile(r"\[([^\]]+)\]\([^\)]+\)"), r"\1"),
]


def _set_progress(**kwargs) -> None:
    with _progress_lock:
        _load_progress.update(kwargs)
        total = _load_progress["bytes_total"]
        if total > 0:
            _load_progress["percent"] = min(
                99, round(100 * _load_progress["bytes_done"] / total)
            )


def progress_snapshot() -> dict:
    with _progress_lock:
        return dict(_load_progress)


def is_ready() -> bool:
    return _ready.is_set()


def get_load_error() -> str | None:
    return _load_error


def require_ready() -> None:
    if _load_error:
        raise HTTPException(status_code=500, detail=_load_error)
    if not _ready.is_set():
        raise HTTPException(status_code=503, detail="Model still loading")


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


def load_model() -> None:
    global tts, SAMPLE_RATE, _load_error
    try:
        print(f"[chatterbox] loading model on {DEVICE}...", flush=True)
        t0 = time.time()
        model_dir = _download_model_files()
        _set_progress(phase="loading", current_file="weights", percent=99)
        tts = ChatterboxTTS.from_local(model_dir, DEVICE)
        SAMPLE_RATE = tts.sr
        print(f"[chatterbox] model loaded in {time.time()-t0:.1f}s  sr={SAMPLE_RATE}", flush=True)

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


def list_preset_voices() -> list[dict]:
    voices = []
    if not VOICES_DIR.exists():
        return voices
    for path in sorted(VOICES_DIR.iterdir()):
        if path.name in VOICE_EXCLUDE or path.suffix.lower() not in {".mp3", ".wav"}:
            continue
        voices.append({"name": path.stem, "ext": path.suffix.lstrip(".").lower(), "path": path})
    return voices


def preset_voice_path(name: str) -> Path | None:
    for ext in (".wav", ".mp3"):
        path = VOICES_DIR / f"{name}{ext}"
        if path.exists() and path.name not in VOICE_EXCLUDE:
            return path
    return None


def file_to_data_url(path: Path) -> str:
    mime = "audio/mpeg" if path.suffix.lower() == ".mp3" else "audio/wav"
    b64 = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


def resolve_voice_model(model: str, api_key_id: str | None) -> tuple[str, str]:
    """Return (cache_key, data_url) for the given model id."""
    preset = preset_voice_path(model)
    if preset:
        data_url = file_to_data_url(preset)
        return f"preset:{model}", data_url

    uploaded = db.get_uploaded_voice(model, api_key_id)
    if uploaded:
        path = Path(uploaded["file_path"])
        if path.exists():
            data_url = file_to_data_url(path)
            return f"upload:{model}", data_url

    raise HTTPException(
        status_code=404,
        detail={"error": {"message": f"Model '{model}' not found.", "type": "invalid_request_error", "code": "model_not_found"}},
    )


def decode_voice(data_url: str) -> str:
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


def normalize_audio_file(src_path: Path, dest_path: Path) -> None:
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src_path), "-ar", "24000", "-ac", "1", str(dest_path), "-loglevel", "error"],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg convert failed: {result.stderr.decode()}")


def prepare_conditionals_cached(cache_key: str, data_url: str, exaggeration: float) -> None:
    key = hashlib.md5(f"{cache_key}:{exaggeration:.3f}".encode()).hexdigest()
    if key in _CONDS_CACHE:
        tts.conds = _CONDS_CACHE[key]
        return
    ref_path = decode_voice(data_url)
    try:
        tts.prepare_conditionals(ref_path, exaggeration=exaggeration)
    finally:
        os.unlink(ref_path)
    if len(_CONDS_CACHE) >= _CONDS_CACHE_MAX:
        del _CONDS_CACHE[next(iter(_CONDS_CACHE))]
    _CONDS_CACHE[key] = tts.conds


def prepare_conditionals_from_path(ref_path: str, exaggeration: float) -> None:
    key = hashlib.md5(f"path:{ref_path}:{exaggeration:.3f}".encode()).hexdigest()
    if key in _CONDS_CACHE:
        tts.conds = _CONDS_CACHE[key]
        return
    tts.prepare_conditionals(ref_path, exaggeration=exaggeration)
    if len(_CONDS_CACHE) >= _CONDS_CACHE_MAX:
        del _CONDS_CACHE[next(iter(_CONDS_CACHE))]
    _CONDS_CACHE[key] = tts.conds


def tensor_to_bytes(wav: torch.Tensor, sr: int, fmt: str) -> bytes:
    arr = wav.squeeze(0).cpu().numpy()
    wav_buf = io.BytesIO()
    sf.write(wav_buf, arr, sr, format="WAV")
    wav_bytes = wav_buf.getvalue()
    if fmt in ("mp3", "opus"):
        codec = "libmp3lame" if fmt == "mp3" else "libopus"
        out_fmt = "mp3" if fmt == "mp3" else "ogg"
        result = subprocess.run(
            ["ffmpeg", "-f", "wav", "-i", "pipe:0",
             "-c:a", codec, "-f", out_fmt, "pipe:1", "-loglevel", "error"],
            input=wav_bytes, capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()}")
        return result.stdout
    return wav_bytes


def infer(text: str, exaggeration: float, cfg_weight: float, temperature: float) -> tuple[torch.Tensor, int]:
    wav = tts.generate(
        text,
        exaggeration=exaggeration,
        cfg_weight=cfg_weight,
        temperature=temperature,
    )
    return wav, SAMPLE_RATE


def split_sentences(text: str) -> list[str]:
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


def health_payload() -> dict:
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
