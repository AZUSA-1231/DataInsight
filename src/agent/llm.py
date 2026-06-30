from __future__ import annotations

import os
from pathlib import Path

from langchain_core.language_models import BaseChatModel

_ENV_FILE = Path(".env")


def _load_dotenv() -> None:
    """Load .env from the current directory into os.environ (no-op if absent).

    Only sets keys that are NOT already in the environment, so env vars take
    precedence over .env for deployment scenarios.
    """
    if not _ENV_FILE.exists():
        return
    try:
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


def get_llm(temperature: float | None = None) -> BaseChatModel:
    """Return a configured LangChain chat model from .env or environment variables.

    Load order: .env file first, then os.environ overrides.

    Required:
        DATAINSIGHT_LLM_MODEL     — model name
        DATAINSIGHT_LLM_API_KEY   — API key
        DATAINSIGHT_LLM_BASE_URL  — API base URL

    Optional:
        DATAINSIGHT_LLM_PROVIDER  — "openai" (default)
        DATAINSIGHT_LLM_TEMPERATURE — default 0
    """
    _load_dotenv()

    provider = os.environ.get("DATAINSIGHT_LLM_PROVIDER", "openai")
    model = os.environ.get("DATAINSIGHT_LLM_MODEL")
    api_key = os.environ.get("DATAINSIGHT_LLM_API_KEY")
    base_url = os.environ.get("DATAINSIGHT_LLM_BASE_URL")
    temp = (
        temperature
        if temperature is not None
        else float(os.environ.get("DATAINSIGHT_LLM_TEMPERATURE", "0"))
    )

    missing: list[str] = []
    if not model:
        missing.append("DATAINSIGHT_LLM_MODEL")
    if not api_key:
        missing.append("DATAINSIGHT_LLM_API_KEY")
    if not base_url:
        missing.append("DATAINSIGHT_LLM_BASE_URL")
    if missing:
        raise ValueError(
            f"Missing required configuration: {', '.join(missing)}\n"
            f"  Create a .env file in the project root with:\n"
            f"    DATAINSIGHT_LLM_MODEL=...\n"
            f"    DATAINSIGHT_LLM_API_KEY=...\n"
            f"    DATAINSIGHT_LLM_BASE_URL=...\n"
            f"  Or set them as environment variables."
        )
    # Narrow types for mypy — we've validated these are not None
    assert model is not None
    assert api_key is not None
    assert base_url is not None

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=api_key,  # type: ignore[arg-type]  # str accepted at runtime
            base_url=base_url,
            temperature=temp,
            timeout=120,
            max_retries=1,
        )

    raise ValueError(f"Unsupported LLM provider: {provider}")
