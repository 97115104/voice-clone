"""
Standalone Chatterbox voice cloning server.

GitHub: https://github.com/resemble-ai/chatterbox
"""
from __future__ import annotations

import base64
import json
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from server import auth, db, tts_engine, voice_catalog
from server.routes import admin, setup, v1

ROOT = Path(__file__).resolve().parent
VOICES_DIR = ROOT / "voices"
WEB_DIR = ROOT.parent / "web"

_NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}


def _html_response(path: Path) -> FileResponse:
    return FileResponse(path, headers=_NO_CACHE)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    db.init_db()
    auth.seed_admin()
    auth.ensure_bootstrap_key()
    threading.Thread(target=tts_engine.load_model, name="model-loader", daemon=True).start()
    yield


app = FastAPI(title="Voice Clone", version="1.1.0", lifespan=_lifespan)
app.include_router(v1.router)
app.include_router(admin.router)
app.include_router(setup.router)


class TTSRequest(BaseModel):
    text: str
    voice: str
    exaggeration: float = 0.5
    cfg_weight: float = 0.5
    temperature: float = 0.8
    format: str = "wav"
    speed: float = 1.0
    nfe_steps: int = 0


@app.post("/tts/synthesize")
async def synthesize(req: TTSRequest, api_key: dict = Depends(auth.require_api_key)):
    tts_engine.require_ready()
    cache_key = f"legacy:{hash(req.voice)}"
    tts_engine.prepare_conditionals_cached(cache_key, req.voice, req.exaggeration)
    wav, sr = tts_engine.infer(req.text, req.exaggeration, req.cfg_weight, req.temperature)
    audio_bytes = tts_engine.tensor_to_bytes(wav, sr, req.format)
    media_type = {"mp3": "audio/mpeg", "opus": "audio/ogg", "wav": "audio/wav"}.get(req.format, "audio/wav")
    return Response(content=audio_bytes, media_type=media_type)


@app.post("/tts/stream")
async def stream(req: TTSRequest, api_key: dict = Depends(auth.require_api_key)):
    tts_engine.require_ready()
    sentences = tts_engine.split_sentences(req.text)
    total = len(sentences)
    cache_key = f"legacy:{hash(req.voice)}"
    tts_engine.prepare_conditionals_cached(cache_key, req.voice, req.exaggeration)

    def generate():
        for i, sentence in enumerate(sentences):
            wav = tts_engine.tts.generate(
                sentence,
                exaggeration=req.exaggeration,
                cfg_weight=req.cfg_weight,
                temperature=req.temperature,
            )
            audio_b64 = base64.b64encode(
                tts_engine.tensor_to_bytes(wav, tts_engine.SAMPLE_RATE, "wav")
            ).decode()
            yield f"data: {json.dumps({'i': i, 'total': total, 'audio': audio_b64})}\n\n"
        yield 'data: {"done":true}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/live")
async def live():
    return {"status": "up"}


@app.get("/health")
async def health():
    if tts_engine.get_load_error():
        return JSONResponse(
            {"status": "error", "error": tts_engine.get_load_error(), "device": tts_engine.DEVICE},
            status_code=500,
        )
    if not tts_engine.is_ready():
        return JSONResponse(
            {
                "status": "loading",
                "device": tts_engine.DEVICE,
                "message": tts_engine.LOAD_MESSAGE,
                "progress": tts_engine.progress_snapshot(),
            },
            status_code=503,
        )
    return tts_engine.health_payload()


@app.get("/api/voices")
async def list_voices(api_key: dict = Depends(auth.require_api_key)):
    tts_engine.require_ready()
    return voice_catalog.list_all_voices(api_key["id"])


@app.get("/api/voices/{voice_id}/audio")
async def voice_audio(voice_id: str, api_key: dict = Depends(auth.require_api_key)):
    tts_engine.require_ready()
    path = voice_catalog.resolve_voice_audio_path(voice_id, api_key["id"])
    if not path:
        raise HTTPException(status_code=404, detail="Voice not found")
    media = "audio/mpeg" if path.suffix.lower() == ".mp3" else "audio/wav"
    return FileResponse(path, media_type=media)


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


@app.get("/admin")
async def admin_page():
    path = WEB_DIR / "admin.html"
    if path.exists():
        return _html_response(path)
    raise HTTPException(status_code=404, detail="Admin UI not found")


@app.get("/")
async def index():
    if not tts_engine.is_ready():
        loading_path = WEB_DIR / "loading.html"
        if loading_path.exists():
            return _html_response(loading_path)
        return Response(
            content=tts_engine.LOAD_MESSAGE,
            media_type="text/plain",
            status_code=503,
            headers=_NO_CACHE,
        )
    index_path = WEB_DIR / "index.html"
    if index_path.exists():
        return _html_response(index_path)
    return Response(content="Voice clone server running. Add web/index.html for the UI.", media_type="text/plain")


if VOICES_DIR.exists():
    app.mount("/voices", StaticFiles(directory=str(VOICES_DIR)), name="voice-files")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8004))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
