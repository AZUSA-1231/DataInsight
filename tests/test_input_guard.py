from __future__ import annotations

from pathlib import Path

import pytest

from src.agent.input_guard import ALLOWED_EXTENSIONS, sanitize_user_input, validate_upload_path


class TestSanitizeUserInput:
    def test_strip_injection_delimiters(self) -> None:
        text = "Hello ```system``` [INST]attack[/INST] <<SYS>>prompt"
        result = sanitize_user_input(text)
        assert "```" not in result
        assert "[INST]" not in result
        assert "<<SYS>>" not in result

    def test_strip_control_characters(self) -> None:
        text = "Hello\x00World\x1f!"
        result = sanitize_user_input(text)
        assert "\x00" not in result
        assert "\x1f" not in result

    def test_collapse_whitespace(self) -> None:
        text = "  Hello    World  "
        result = sanitize_user_input(text)
        assert result == "Hello World"

    def test_truncate_default_max_len(self) -> None:
        text = "x" * 3000
        result = sanitize_user_input(text)
        assert len(result) == 2000

    def test_truncate_custom_max_len(self) -> None:
        text = "x" * 100
        result = sanitize_user_input(text, max_len=50)
        assert len(result) == 50

    def test_preserves_valid_text(self) -> None:
        text = "请分析Q2销售数据趋势及其背后的原因。"
        result = sanitize_user_input(text)
        assert result == text

    def test_no_truncation_within_limit(self) -> None:
        text = "Short message"
        result = sanitize_user_input(text, max_len=2000)
        assert result == text


class TestValidateUploadPath:
    def test_valid_csv(self, tmp_path: Path) -> None:
        result = validate_upload_path(tmp_path, "data.csv")
        assert result.suffix == ".csv"
        assert result.parent == tmp_path.resolve()

    def test_valid_xlsx(self, tmp_path: Path) -> None:
        result = validate_upload_path(tmp_path, "data.xlsx")
        assert result.suffix == ".xlsx"

    def test_rejects_unsupported_extension(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Unsupported file type"):
            validate_upload_path(tmp_path, "data.json")

    def test_rejects_path_traversal(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Path traversal"):
            validate_upload_path(tmp_path, "../../../etc/passwd.csv")

    def test_rejects_dot_dot_in_middle(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Path traversal"):
            validate_upload_path(tmp_path, "subdir/../../secret.csv")

    def test_allowed_extensions_set(self) -> None:
        assert ".csv" in ALLOWED_EXTENSIONS
        assert ".xlsx" in ALLOWED_EXTENSIONS
        assert ".xls" in ALLOWED_EXTENSIONS
        assert ".json" not in ALLOWED_EXTENSIONS
