from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel


def _load_dotenv() -> None:
    """Load .env from the current directory into os.environ (no-op if absent).

    Only sets keys that are NOT already in the environment, so env vars take
    precedence over .env for deployment scenarios.
    """
    load_dotenv(override=False)


def get_llm(
    temperature: float | None = None, node: str | None = None
) -> BaseChatModel:
    """Return a configured LangChain chat model from .env or environment variables.

    Load order: .env file first, then os.environ overrides.

    Required:
        DATAINSIGHT_LLM_MODEL     — model name
        DATAINSIGHT_LLM_API_KEY   — API key
        DATAINSIGHT_LLM_BASE_URL  — API base URL

    Optional:
        DATAINSIGHT_LLM_PROVIDER  — "openai" (default)
        DATAINSIGHT_LLM_TEMPERATURE — default 0
        DATAINSIGHT_LLM_MODEL_<NODE>  — per-node model override (upper-cased)
        DATAINSIGHT_LLM_API_KEY_<NODE>
        DATAINSIGHT_LLM_BASE_URL_<NODE>

    When ``node`` is provided (e.g. ``"planner"``), per-node env vars
    (``DATAINSIGHT_LLM_MODEL_PLANNER``, etc.) take precedence over the
    base vars. This allows different pipeline stages to target different
    models (strong model for planner, cheap model for executor).
    """
    _load_dotenv()

    provider = os.environ.get("DATAINSIGHT_LLM_PROVIDER", "openai")

    suffix = f"_{node.upper()}" if node else ""

    model = os.environ.get(f"DATAINSIGHT_LLM_MODEL{suffix}") or os.environ.get(
        "DATAINSIGHT_LLM_MODEL"
    )
    api_key = os.environ.get(f"DATAINSIGHT_LLM_API_KEY{suffix}") or os.environ.get(
        "DATAINSIGHT_LLM_API_KEY"
    )
    base_url = os.environ.get(f"DATAINSIGHT_LLM_BASE_URL{suffix}") or os.environ.get(
        "DATAINSIGHT_LLM_BASE_URL"
    )
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
