from __future__ import annotations

import csv
import os
import tempfile
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.agent.nodes.analysis import analysis_node
from src.agent.state import AgentState, PlanUnit


@pytest.mark.integration
def test_smoke_analysis_real_sandbox(
    set_llm_env: None, make_plan: object, temp_output_dir: str
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
            'print(\'{"charts": ["out/chart1.png"],'
            ' "statistics": {"count": 2},'
            ' "insights": ["Two rows analyzed"]}\')'
        )

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=valid_script)

        state = AgentState(
            file_path=csv_path,
            user_requirement="Smoke test",
            plan=make_plan(
                units=[
                    PlanUnit(
                        unit_id=1,
                        purpose="Smoke test terminal",
                        unit_type="terminal",
                    )
                ]
            ),
        )

        with patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm):
            result = analysis_node(state)

        assert result.get("error") is None
        an_result = result["analysis_result"]
        assert an_result["status"] == "complete"
        assert len(an_result["unit_results"]) == 1
        ur = an_result["unit_results"][0]
        assert ur["status"] == "success"
        assert ur["statistics"]["count"] == 2
        assert ur["insights"] == ["Two rows analyzed"]
        assert ur["retry_count"] == 0
    finally:
        os.unlink(csv_path)


@pytest.mark.integration
def test_smoke_dag_chain_real_sandbox(
    set_llm_env: None, temp_output_dir: str
) -> None:
    """3-unit in-process DAG validates function contracts and checkpoints."""
    _ = set_llm_env

    from src.agent.state import Plan, PlanUnit

    fd, csv_path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "score"])
        writer.writerow(["Alice", "95"])
        writer.writerow(["Bob", "87"])
        writer.writerow(["Carol", "92"])
        writer.writerow(["Dave", "78"])
        writer.writerow(["Eve", "88"])

    try:
        # Unit 1: compute score_squared from score
        script_u1 = (
            "def _unit(df, input_columns, params):\n"
            "    values = df['score'] ** 2\n"
            "    return {'columns': {'score_squared': values}, 'artifacts': []}\n"
        )

        # Unit 2: read upstream data (has score_squared), compute category
        script_u2 = (
            "def _unit(df, input_columns, params):\n"
            "    values = df['score'].gt(90).map({True: 'high', False: 'low'})\n"
            "    return {'columns': {'score_category': values}, 'artifacts': []}\n"
        )

        # Unit 3: read upstream data (has score_category), final stats
        script_u3 = (
            "def _unit(df, input_columns, params):\n"
            "    return {'columns': {}, 'artifacts': []}\n"
        )

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            MagicMock(content=script_u1),
            MagicMock(content=script_u2),
            MagicMock(content=script_u3),
        ]

        plan = Plan(
            units=[
                PlanUnit(
                    unit_id=1,
                    purpose="Compute score_squared",
                    model="auto",
                    cautious="",
                    depends_on=[],
                    input_columns=[],
                    output_columns=["score_squared"],
                    related_fields=["score"],
                ),
                PlanUnit(
                    unit_id=2,
                    purpose="Categorize scores",
                    model="auto",
                    cautious="",
                    depends_on=[1],
                    input_columns=["score_squared"],
                    output_columns=["score_category"],
                    related_fields=["score"],
                ),
                PlanUnit(
                    unit_id=3,
                    purpose="Final statistics",
                    model="auto",
                    cautious="",
                    depends_on=[2],
                    input_columns=["score_category"],
                    output_columns=[],
                    related_fields=["score"],
                ),
            ],
            alignment_notes="DAG chain smoke test",
        )

        state = AgentState(
            file_path=csv_path,
            user_requirement="DAG chain smoke test",
            plan=plan,
            unified_columns=["name", "score"],
        )

        with patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm):
            result = analysis_node(state)

        assert result.get("error") is None, f"DAG chain errors: {result.get('error')}"
        an_result = result["analysis_result"]
        assert an_result["status"] == "complete", (
            f"Expected complete, got {an_result['status']}: "
            f"{[ur.get('error') for ur in an_result['unit_results']]}"
        )
        assert len(an_result["unit_results"]) == 3

        unit_results = {ur["unit_id"]: ur for ur in an_result["unit_results"]}
        for uid in (1, 2, 3):
            assert unit_results[uid]["status"] == "success", (
                f"Unit {uid} failed: {unit_results[uid].get('error')}"
            )

        # Verify the final checkpoint contains both upstream columns.
        checkpoint = os.path.join(
            an_result["output_dir"], "checkpoints", "wide_l3.parquet"
        )
        final_df = pd.read_parquet(checkpoint)
        assert final_df["score_squared"].tolist() == [9025, 7569, 8464, 6084, 7744]
        assert final_df["score_category"].tolist() == ["high", "low", "high", "low", "low"]

        # Verify call order: exactly 3 LLM invocations (no retries)
        assert mock_llm.invoke.call_count == 3

    finally:
        os.unlink(csv_path)
