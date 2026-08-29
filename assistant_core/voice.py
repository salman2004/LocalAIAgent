"""UI-support functions backing the web frontend's voice features -
transcribe (mic audio -> text, forwarded to the vendored whisper-server)
and speak (text -> WAV bytes, via a per-utterance Piper subprocess).

These are plumbing for main.py's /voice/* endpoints, NOT LLM-visible
tools - the model never calls these directly, only the browser does.
"""

from __future__ import annotations

import asyncio
import audioop
import io
import wave

import httpx

from assistant_core.config import get_config

OUTPUT_SAMPLE_RATE = 44100


def _resample_wav(wav_bytes: bytes, out_rate: int) -> bytes:
    """Piper outputs at its voice model's native rate (22050Hz for
    en_US-lessac-medium). Resampling here, once, server-side, means the
    browser/OS never has to - which turned out to matter: this device's
    Bluetooth output sounded distorted at 22050Hz even with zero Web Audio
    API involvement client-side, so the OS's own resampler for this
    specific device/rate combination was the actual remaining suspect.
    """
    with wave.open(io.BytesIO(wav_bytes), "rb") as src:
        params = src.getparams()
        frames = src.readframes(params.nframes)

    if params.framerate == out_rate:
        return wav_bytes

    converted, _ = audioop.ratecv(
        frames, params.sampwidth, params.nchannels, params.framerate, out_rate, None
    )

    out = io.BytesIO()
    with wave.open(out, "wb") as dst:
        dst.setnchannels(params.nchannels)
        dst.setsampwidth(params.sampwidth)
        dst.setframerate(out_rate)
        dst.writeframes(converted)
    return out.getvalue()


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
    return _resample_wav(stdout, OUTPUT_SAMPLE_RATE)
