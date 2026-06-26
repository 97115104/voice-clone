"""OpenAI-compatible TTS API routes."""
from __future__ import annotations

import base64
import json
import tempfile
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from server import auth, db, tts_engine, voice_catalog

router = APIRouter(prefix="/v1", tags=["v1"])


class SpeechRequest(BaseModel):
    model: str
    input: str
    response_format: str = "wav"
    stream: bool = False
    exaggeration: float = Field(default=0.5, ge=0.0, le=2.0)
    cfg_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    temperature: float = Field(default=0.8, ge=0.05, le=2.0)


def _created_ts(row: dict | None = None) -> int:
    if row and row.get("created_at"):
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            return int(dt.timestamp())
        except Exception:
            pass
    return int(time.time())


def _model_entry(model_id: str, owned_by: str, created_at: int | None = None) -> dict:
    return {
        "id": model_id,
        "object": "model",
        "created": created_at or int(time.time()),
        "owned_by": owned_by,
    }


@router.get("/models")
async def list_models(api_key: Annotated[dict, Depends(auth.require_api_key)]):
    tts_engine.require_ready()
    data = []
    for voice in voice_catalog.list_all_voices(api_key["id"]):
        owned = voice["owned_by"]
        created = _created_ts(voice) if voice.get("created_at") else None
        data.append(_model_entry(voice["id"], owned, created))
    return {"object": "list", "data": data}


@router.get("/voices")
async def list_voices(api_key: Annotated[dict, Depends(auth.require_api_key)]):
    tts_engine.require_ready()
    return {"object": "list", "data": voice_catalog.list_all_voices(api_key["id"])}


@router.post("/voices")
async def upload_voice(
    api_key: Annotated[dict, Depends(auth.require_api_key)],
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
):
    tts_engine.require_ready()
    voice_id = f"voice-{db.new_id()[:12]}"
    dest = db.VOICES_UPLOAD_DIR / f"{voice_id}.wav"

    suffix = Path(file.filename or "voice.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        tts_engine.normalize_audio_file(tmp_path, dest)
    finally:
        tmp_path.unlink(missing_ok=True)

    row = db.create_uploaded_voice(
        voice_id=voice_id,
        api_key_id=api_key["id"],
        name=name or voice_id,
        file_path=str(dest),
    )
    return {"id": voice_id, "object": "voice", "name": row.get("name") or voice_id}


@router.delete("/voices/{voice_id}")
async def delete_voice(voice_id: str, api_key: Annotated[dict, Depends(auth.require_api_key)]):
    row = db.delete_uploaded_voice(voice_id, api_key["id"])
    if not row:
        raise HTTPException(status_code=404, detail="Voice not found")
    Path(row["file_path"]).unlink(missing_ok=True)
    return {"deleted": True, "id": voice_id}


@router.post("/audio/speech")
async def create_speech(req: SpeechRequest, api_key: Annotated[dict, Depends(auth.require_api_key)]):
    tts_engine.require_ready()
    if not req.input.strip():
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": "input is required", "type": "invalid_request_error", "code": "missing_input"}},
        )

    fmt = req.response_format.lower()
    if fmt not in {"wav", "mp3", "opus"}:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": f"Unsupported response_format: {fmt}", "type": "invalid_request_error", "code": "invalid_format"}},
        )

    cache_key, data_url = tts_engine.resolve_voice_model(req.model, api_key["id"])
    req_id = db.create_request(api_key_id=api_key["id"], model=req.model, prompt_full=req.input)
    t0 = time.time()

    try:
        tts_engine.prepare_conditionals_cached(cache_key, data_url, req.exaggeration)

        if req.stream:
            sentences = tts_engine.split_sentences(req.input)
            total = len(sentences)

            def generate():
                try:
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
                        chunk = {
                            "object": "speech.chunk",
                            "index": i,
                            "total": total,
                            "audio": audio_b64,
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                    db.finish_request(req_id, status="completed", latency_ms=int((time.time() - t0) * 1000))
                except Exception as exc:
                    db.finish_request(req_id, status="error", latency_ms=int((time.time() - t0) * 1000), error=str(exc))
                    raise

            return StreamingResponse(generate(), media_type="text/event-stream")

        wav, sr = tts_engine.infer(req.input, req.exaggeration, req.cfg_weight, req.temperature)
        audio_bytes = tts_engine.tensor_to_bytes(wav, sr, fmt)
        db.finish_request(req_id, status="completed", latency_ms=int((time.time() - t0) * 1000))
        media_type = {"mp3": "audio/mpeg", "opus": "audio/ogg", "wav": "audio/wav"}.get(fmt, "audio/wav")
        return Response(content=audio_bytes, media_type=media_type)
    except HTTPException:
        db.finish_request(req_id, status="error", latency_ms=int((time.time() - t0) * 1000), error="request failed")
        raise
    except Exception as exc:
        db.finish_request(req_id, status="error", latency_ms=int((time.time() - t0) * 1000), error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
