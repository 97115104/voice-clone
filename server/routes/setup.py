"""Setup routes: status and tunnel URL registration."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from server import auth, db, tts_engine

router = APIRouter(prefix="/setup", tags=["setup"])


class TunnelBody(BaseModel):
    url: str


@router.get("/status")
async def status(request: Request):
    payload = {
        "tunnel_url": db.get_setting("tunnel_url"),
        "model": {
            "ready": tts_engine.is_ready(),
            "error": tts_engine.get_load_error(),
            "progress": tts_engine.progress_snapshot() if not tts_engine.is_ready() else None,
        },
    }
    if auth.is_local_request(request):
        bootstrap = db.get_bootstrap_key()
        if bootstrap and bootstrap.get("raw_key"):
            payload["bootstrap_api_key"] = bootstrap["raw_key"]
    return payload


@router.post("/tunnel")
async def register_tunnel(body: TunnelBody, _admin: Annotated[dict, Depends(auth.require_admin)]):
    if not body.url.strip():
        raise HTTPException(status_code=400, detail="url required")
    db.set_setting("tunnel_url", body.url.strip())
    return {"ok": True, "url": body.url.strip()}
