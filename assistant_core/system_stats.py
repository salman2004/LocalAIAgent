"""System resource stats and backend-service health for the web UI's HUD
widgets. CPU/RAM come from psutil; GPU comes from Windows' own "GPU
Engine" performance counters (works for any GPU vendor, unlike a
vendor-specific SDK) - that's slow enough (a few hundred ms, since it
shells out to PowerShell) that it's cached and only refreshed every few
seconds rather than on every poll from the frontend.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import psutil

from assistant_core.config import get_config

GPU_CACHE_SECONDS = 3
_gpu_cache: dict = {"value": None, "ts": 0.0}


async def _read_gpu_percent() -> float | None:
    now = time.monotonic()
    if now - _gpu_cache["ts"] < GPU_CACHE_SECONDS:
        return _gpu_cache["value"]

    value = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "(Get-Counter -Counter '\\GPU Engine(*)\\Utilization Percentage' "
            "-ErrorAction Stop).CounterSamples "
            "| Measure-Object -Property CookedValue -Sum "
            "| Select-Object -ExpandProperty Sum",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        value = min(100.0, float(stdout.decode(errors="replace").strip()))
    except (OSError, asyncio.TimeoutError, ValueError):
        value = None

    _gpu_cache["value"] = value
    _gpu_cache["ts"] = now
    return value


async def get_resource_stats() -> dict:
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_percent": psutil.virtual_memory().percent,
        "gpu_percent": await _read_gpu_percent(),
    }


async def get_service_status() -> dict:
    cfg = get_config()
    checks = {
        "llm": f"{cfg.llm.base_url}/health",
        "embedding": f"{cfg.embeddings.base_url}/health",
        "stt": f"{cfg.speech_to_text.base_url}/",
    }
    results: dict[str, bool] = {}
    async with httpx.AsyncClient(timeout=1.5) as client:
        for name, url in checks.items():
            try:
                resp = await client.get(url)
                results[name] = resp.status_code < 500
            except httpx.HTTPError:
                results[name] = False
    return results


async def get_status() -> dict:
    stats, services = await asyncio.gather(get_resource_stats(), get_service_status())
    return {**stats, "services": services}
