from __future__ import annotations

import os
from typing import Any

from langchain_core.language_models import BaseChatModel


def get_llm(temperature: float | None = None) -> BaseChatModel:
    """Return a configured LangChain chat model from environment variables.

    Reads:
        DATAINSIGHT_LLM_PROVIDER  — "openai" (default)
        DATAINSIGHT_LLM_MODEL     — model name
        DATAINSIGHT_LLM_API_KEY   — API key
        DATAINSIGHT_LLM_BASE_URL  — optional base URL
        DATAINSIGHT_LLM_TEMPERATURE — default 0 (deterministic)

    Raises:
        ValueError if required env vars are missing.
    """
    provider = os.environ.get("DATAINSIGHT_LLM_PROVIDER", "openai")
    model = os.environ.get("DATAINSIGHT_LLM_MODEL")
    api_key = os.environ.get("DATAINSIGHT_LLM_API_KEY")
    base_url = os.environ.get("DATAINSIGHT_LLM_BASE_URL", None)
    temp = temperature if temperature is not None else float(
        os.environ.get("DATAINSIGHT_LLM_TEMPERATURE", "0")
    )

    missing: list[str] = []
    if not model:
        missing.append("DATAINSIGHT_LLM_MODEL")
    if not api_key:
        missing.append("DATAINSIGHT_LLM_API_KEY")
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": api_key,
            "temperature": temp,
            "timeout": 120,
            "max_retries": 1,
        }
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)

    raise ValueError(f"Unsupported LLM provider: {provider}")
