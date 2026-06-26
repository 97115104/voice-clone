"""Unified voice catalog: presets from disk + uploaded voices from DB."""
from __future__ import annotations

from server import db, tts_engine


def list_all_voices(api_key_id: str | None = None) -> list[dict]:
    voices: list[dict] = []
    for preset in tts_engine.list_preset_voices():
        voices.append({
            "id": preset["name"],
            "name": preset["name"],
            "ext": preset["ext"],
            "source": "preset",
            "object": "voice",
            "owned_by": "voice-clone",
        })
    for row in db.list_uploaded_voices(api_key_id):
        voices.append({
            "id": row["id"],
            "name": row.get("name") or row["id"],
            "ext": "wav",
            "source": "upload",
            "object": "voice",
            "owned_by": "shared" if not row.get("api_key_id") else "user",
            "created_at": row.get("created_at"),
        })
    return voices


def resolve_voice_audio_path(voice_id: str, api_key_id: str | None = None):
    """Return a Path to the voice audio file, or None if not found."""
    preset = tts_engine.preset_voice_path(voice_id)
    if preset:
        return preset
    uploaded = db.get_uploaded_voice(voice_id, api_key_id)
    if uploaded:
        from pathlib import Path
        path = Path(uploaded["file_path"])
        if path.exists():
            return path
    return None
