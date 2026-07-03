from __future__ import annotations

import pytest

from src.agent.utils import _extract_code_block, _extract_json


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


# ── _extract_json ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_extract_json_single_line() -> None:
    assert _extract_json('{"a": 1}') == '{"a": 1}'


@pytest.mark.unit
def test_extract_json_multi_line() -> None:
    text = '{\n  "a": 1,\n  "b": 2\n}'
    assert _extract_json(text) == '{\n  "a": 1,\n  "b": 2\n}'


@pytest.mark.unit
def test_extract_json_with_preamble() -> None:
    text = 'encoding: utf-8\n{"status": "ok"}'
    assert _extract_json(text) == '{"status": "ok"}'


@pytest.mark.unit
def test_extract_json_in_markdown_fence() -> None:
    text = '```json\n{"key": "value"}\n```'
    assert _extract_json(text) == '{"key": "value"}'


@pytest.mark.unit
def test_extract_json_nested_braces() -> None:
    text = '{"outer": {"inner": [1, 2, 3]}}'
    assert _extract_json(text) == '{"outer": {"inner": [1, 2, 3]}}'
