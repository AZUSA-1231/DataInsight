from __future__ import annotations

import csv
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.preprocessing import preprocessing_node
from src.agent.state import AgentState


@pytest.mark.integration
def test_smoke_preprocessing_real_sandbox(
    set_llm_env: None, make_execution_plan: object, temp_output_dir: str
) -> None:
    """Mock LLM returns fixed code; subprocess executes it for real; JSON is parseable.

    This is the only test that does NOT mock ``run_script`` — it validates the
    full sandbox execution path end-to-end.
    """
    _ = set_llm_env

    fd, csv_path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "score"])
        writer.writerow(["Alice", "95"])
        writer.writerow(["Bob", "87"])

    try:
        valid_script = (
            "import sys\n"
            'print(\'{"cleaned_shape": {"rows": 2, "cols": 2},'
            ' "cleaning_actions": ["none"],'
            ' "cleaned_data_path": "/tmp/out/cleaned_data.csv"}\')'
        )

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=valid_script)

        state = AgentState(
            file_path=csv_path,
            user_requirement="Smoke test",
            execution_plan=make_execution_plan(),
        )

        with patch("src.agent.nodes.preprocessing.get_llm", return_value=mock_llm):
            result = preprocessing_node(state)

        assert result.get("error") is None
        parsed = result["preprocessing_result"]["parsed_output"]
        assert parsed["cleaned_shape"]["rows"] == 2
        assert parsed["cleaned_shape"]["cols"] == 2
        assert result["preprocessing_result"]["retry_count"] == 0
    finally:
        os.unlink(csv_path)
