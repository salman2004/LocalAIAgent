"""UI-support functions backing the web frontend's voice features -
transcribe (mic audio -> text, forwarded to the vendored whisper-server)
and speak (text -> WAV bytes, via a per-utterance Piper subprocess).

These are plumbing for main.py's /voice/* endpoints, NOT LLM-visible
tools - the model never calls these directly, only the browser does.
"""

from __future__ import annotations

import asyncio

import httpx

from assistant_core.config import get_config


async def transcribe(audio_bytes: bytes, filename: str) -> str:
    cfg = get_config().speech_to_text
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{cfg.base_url}/inference",
            files={"file": (filename, audio_bytes)},
            data={"response_format": "json"},
        )
    resp.raise_for_status()
    return resp.json().get("text", "").strip()


async def speak(text: str) -> bytes:
    cfg = get_config().text_to_speech
    proc = await asyncio.create_subprocess_exec(
        cfg.exe_path,
        "--model",
        cfg.voice_model_path,
        "--config",
        cfg.voice_config_path,
        "--output_file",
        "-",
        "--quiet",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=text.encode("utf-8"))
    if proc.returncode != 0:
        raise RuntimeError(
            f"piper exited with code {proc.returncode}: {stderr.decode(errors='replace')}"
        )
    return stdout
