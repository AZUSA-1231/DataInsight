from __future__ import annotations

import pytest

from src.agent.utils import _extract_code_block


@pytest.mark.unit
def test_extract_code_block_no_fence() -> None:
    code = "print('hello')\n"
    assert _extract_code_block(code) == code.strip()


@pytest.mark.unit
def test_extract_code_block_with_fence() -> None:
    text = "Some text\n```python\nprint('hello')\n```\nMore text"
    assert _extract_code_block(text) == "print('hello')"


@pytest.mark.unit
def test_extract_code_block_no_language_tag() -> None:
    text = "```\nprint('hello')\n```"
    assert _extract_code_block(text) == "print('hello')"
