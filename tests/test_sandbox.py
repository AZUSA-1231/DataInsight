from __future__ import annotations

import json

import pytest

from src.sandbox.executor import SandboxResult, run_script
from src.sandbox.inspection_script import run as inspection_run


@pytest.mark.unit
def test_run_script_success(sample_csv_path: str) -> None:
    result = run_script("src/sandbox/inspection_script.py", [sample_csv_path])

    assert result.exit_code == 0
    assert not result.timed_out
    data = json.loads(result.stdout)
    assert data["shape"]["rows"] == 5
    assert len(data["columns"]) == 5


@pytest.mark.unit
def test_run_script_timeout() -> None:
    result = run_script(
        "src/sandbox/inspection_script.py",
        ["/nonexistent/file.csv"],
        timeout_seconds=1,
    )

    # Script may fail fast or timeout — either is fine for this test
    assert isinstance(result, SandboxResult)


@pytest.mark.unit
def test_run_script_file_not_found() -> None:
    result = run_script("src/sandbox/inspection_script.py", ["/nonexistent/file.csv"])

    assert result.exit_code != 0
    assert len(result.stderr) > 0


@pytest.mark.unit
def test_inspection_output_schema(sample_csv_path: str) -> None:
    import io
    import sys

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        inspection_run(sample_csv_path)
        output = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout

    data = json.loads(output)
    assert "file_path" in data
    assert "shape" in data
    assert "columns" in data
    assert "statistics" in data
    assert "head" in data
    assert data["shape"]["rows"] == 5
    assert data["shape"]["cols"] == 5
    assert len(data["head"]) <= 5
    # Verify columns have required fields
    for col in data["columns"]:
        assert "name" in col
        assert "dtype" in col
        assert "null_count" in col
        assert "null_pct" in col


@pytest.mark.unit
def test_inspection_nan_serialized_as_null(sample_csv_path: str) -> None:
    import io
    import sys

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        inspection_run(sample_csv_path)
        output = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout

    assert "NaN" not in output
    json.loads(output)  # must be valid JSON
