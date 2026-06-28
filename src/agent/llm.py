from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel


def get_llm(temperature: float | None = None) -> BaseChatModel:
    """Return a configured LangChain chat model from environment variables.

    Required env vars:
        DATAINSIGHT_LLM_MODEL     — model name
        DATAINSIGHT_LLM_API_KEY   — API key
        DATAINSIGHT_LLM_BASE_URL  — API base URL

    Optional:
        DATAINSIGHT_LLM_PROVIDER  — "openai" (default)
        DATAINSIGHT_LLM_TEMPERATURE — default 0
    """
    provider = os.environ.get("DATAINSIGHT_LLM_PROVIDER", "openai")
    model = os.environ.get("DATAINSIGHT_LLM_MODEL")
    api_key = os.environ.get("DATAINSIGHT_LLM_API_KEY")
    base_url = os.environ.get("DATAINSIGHT_LLM_BASE_URL")
    temp = temperature if temperature is not None else float(
        os.environ.get("DATAINSIGHT_LLM_TEMPERATURE", "0")
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
            f"Missing required environment variables: {', '.join(missing)}"
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
