"""Loads config.yaml once and exposes it as a plain nested object.

Paths in config.yaml are relative to the repo root (the directory
containing config.yaml), not to whatever directory a script happens
to be run from.
"""

from __future__ import annotations

import functools
from pathlib import Path
from types import SimpleNamespace

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"


def _to_namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _to_namespace(v) for k, v in value.items()})
    return value


def _resolve_path(value: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    return str(path)


@functools.lru_cache(maxsize=1)
def get_config() -> SimpleNamespace:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    raw["llm"]["model_path"] = _resolve_path(raw["llm"]["model_path"])
    raw["embeddings"]["model_path"] = _resolve_path(raw["embeddings"]["model_path"])
    raw["rag"]["db_path"] = _resolve_path(raw["rag"]["db_path"])
    raw["speech_to_text"]["model_path"] = _resolve_path(raw["speech_to_text"]["model_path"])
    for root_spec in raw["workspace"]["roots"].values():
        root_spec["path"] = _resolve_path(root_spec["path"])

    return _to_namespace(raw)
