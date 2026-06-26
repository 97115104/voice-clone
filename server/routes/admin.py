"""Admin routes: login, API keys, requests."""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from server import auth, db, tts_engine, voice_catalog

router = APIRouter(prefix="/admin", tags=["admin"])


class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    current: str
    new: str


class KeyCreateBody(BaseModel):
    name: str | None = None
    owner_email: str | None = None
    scopes: list[str] | None = None


class KeyPatchBody(BaseModel):
    active: bool | None = None
    name: str | None = None
    scopes: list[str] | None = None


@router.post("/login")
async def login(body: LoginBody):
    admin = db.get_admin_by_username(body.username)
    if not admin or not auth.verify_password(body.password, admin["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = auth.sign_admin_token(admin["username"], admin["id"])
    return {"token": token}


@router.post("/password")
async def change_password(body: PasswordBody, admin: Annotated[dict, Depends(auth.require_admin)]):
    if len(body.new) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    if not auth.verify_password(body.current, admin["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    db.update_admin_password(admin["id"], auth.hash_password(body.new))
    return {"ok": True}


@router.get("/keys")
async def list_keys(_admin: Annotated[dict, Depends(auth.require_admin)]):
    keys = db.list_api_keys()
    for key in keys:
        key.pop("key_hash", None)
    return {"keys": keys}


@router.post("/keys", status_code=201)
async def create_key(body: KeyCreateBody, _admin: Annotated[dict, Depends(auth.require_admin)]):
    raw, key_hash, prefix = auth.generate_api_key()
    scopes = json.dumps(body.scopes if body.scopes else ["speech"])
    row = db.create_api_key(
        prefix=prefix,
        key_hash=key_hash,
        raw_key=raw,
        name=body.name,
        owner_email=body.owner_email,
        scopes=scopes,
    )
    return {"key": raw, "id": row["id"], "prefix": prefix}


@router.patch("/keys/{key_id}")
async def patch_key(key_id: str, body: KeyPatchBody, _admin: Annotated[dict, Depends(auth.require_admin)]):
    if not db.get_api_key_by_id(key_id):
        raise HTTPException(status_code=404, detail="Key not found")
    updates = {}
    if body.active is not None:
        updates["active"] = body.active
    if body.name is not None:
        updates["name"] = body.name
    if body.scopes is not None:
        updates["scopes"] = json.dumps(body.scopes)
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    db.update_api_key(key_id, **updates)
    return {"ok": True}


@router.delete("/keys/{key_id}")
async def delete_key(key_id: str, _admin: Annotated[dict, Depends(auth.require_admin)]):
    db.delete_api_key(key_id)
    return {"deleted": True}


@router.get("/requests")
async def list_requests(_admin: Annotated[dict, Depends(auth.require_admin)], limit: int = 100):
    return {"requests": db.list_requests(limit)}


@router.get("/requests/{req_id}")
async def get_request(req_id: str, _admin: Annotated[dict, Depends(auth.require_admin)]):
    row = db.get_request(req_id)
    if not row:
        raise HTTPException(status_code=404, detail="Request not found")
    return {"request": row}


@router.get("/settings")
async def get_settings(_admin: Annotated[dict, Depends(auth.require_admin)]):
    return {
        "tunnel_url": db.get_setting("tunnel_url"),
    }


@router.get("/voices")
async def admin_list_voices(_admin: Annotated[dict, Depends(auth.require_admin)]):
    return {"voices": voice_catalog.list_all_voices()}


@router.post("/voices", status_code=201)
async def admin_upload_voice(
    _admin: Annotated[dict, Depends(auth.require_admin)],
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
):
    import tempfile
    from pathlib import Path

    from server import tts_engine

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
        api_key_id=None,
        name=name or voice_id,
        file_path=str(dest),
    )
    return {"id": voice_id, "object": "voice", "name": row.get("name") or voice_id}


@router.delete("/voices/{voice_id}")
async def admin_delete_voice(voice_id: str, _admin: Annotated[dict, Depends(auth.require_admin)]):
    from pathlib import Path

    if tts_engine.preset_voice_path(voice_id):
        raise HTTPException(status_code=400, detail="Preset voices cannot be deleted")
    row = db.delete_uploaded_voice_by_id(voice_id)
    if not row:
        raise HTTPException(status_code=404, detail="Voice not found")
    Path(row["file_path"]).unlink(missing_ok=True)
    return {"deleted": True}
