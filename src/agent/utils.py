from __future__ import annotations

import atexit
import logging
import os
import re
import shutil

logger = logging.getLogger(__name__)

_TEMP_PATHS: list[str] = []


def _cleanup_temp_paths() -> None:
    """Remove registered temp files and directories, ignoring errors."""
    for path in _TEMP_PATHS:
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            elif os.path.isfile(path):
                os.unlink(path)
        except OSError:
            pass


atexit.register(_cleanup_temp_paths)


def register_temp_path(path: str) -> None:
    """Register a temp file or directory for cleanup at process exit."""
    _TEMP_PATHS.append(path)


def _extract_code_block(text: str) -> str:
    """Extract Python code from a markdown code fence if present."""
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _extract_json(text: str) -> str:
    """Extract JSON object from text — handles markdown fences and multi-line output.

    Tries in order: (1) markdown code fence, (2) outermost braces.
    Returns the extracted JSON string on success, or the original text on failure.
    """
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text
