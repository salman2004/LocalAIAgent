"""Internal helper: prints config.yaml values as JSON so the PowerShell
launch scripts can stay in sync with a single source of truth instead of
duplicating port/path defaults.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant_core.config import get_config  # noqa: E402

cfg = get_config()
print(
    json.dumps(
        {
            "llm_base_url": cfg.llm.base_url,
            "llm_model_path": cfg.llm.model_path,
            "llm_context_size": cfg.llm.context_size,
            "embeddings_base_url": cfg.embeddings.base_url,
            "embeddings_model_path": cfg.embeddings.model_path,
            "embeddings_context_size": cfg.embeddings.context_size,
            "speech_to_text_base_url": cfg.speech_to_text.base_url,
            "speech_to_text_model_path": cfg.speech_to_text.model_path,
        }
    )
)
