"""Shared input sanitization and path validation utilities.

Used by both CLI (__main__.py) and API routes (dialogue, data upload).
"""

from __future__ import annotations

import re
from pathlib import Path

# Prompt injection delimiters — stripped from user input
_INJECTION_DELIMITERS = re.compile(
    r"```|"
    r"---|===|"
    r"### SYSTEM|### USER|### ASSISTANT|"
    r"<\|im_start\|>|<\|im_end\|>|"
    r"<\|system\|>|<\|user\|>|<\|assistant\|>|"
    r"\[INST\]|\[/INST\]|"
    r"<<SYS>>|<</SYS>>",
    re.IGNORECASE,
)

ALLOWED_EXTENSIONS: set[str] = {".csv", ".xlsx", ".xls"}


def sanitize_user_input(text: str, max_len: int = 2000) -> str:
    """Strip prompt injection delimiters, control characters, truncate."""
    text = _INJECTION_DELIMITERS.sub(" ", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len]
    return text


def validate_upload_path(upload_dir: Path, filename: str) -> Path:
    """Resolve upload path and block path traversal.

    Returns the resolved, safe Path. Raises ValueError if the filename
    contains traversal or has an unsupported extension.
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    upload_dir = upload_dir.resolve()
    file_path = (upload_dir / filename).resolve()

    try:
        file_path.relative_to(upload_dir)
    except ValueError:
        raise ValueError(f"Path traversal blocked: {filename}") from None

    return file_path


def allocate_upload_path(upload_dir: Path, filename: str) -> Path:
    """Return a safe non-overwriting path for an uploaded source."""
    candidate = validate_upload_path(upload_dir, filename)
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2
    while True:
        alternative = candidate.with_name(f"{stem}_{counter}{suffix}")
        if not alternative.exists():
            return alternative
        counter += 1
