from __future__ import annotations

import csv
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.analysis import analysis_node
from src.agent.state import AgentState


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
            plan=make_plan(),
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
    """3-unit DAG chain with real subprocess: validates topological ordering,
    output.csv passing, and column resolution end-to-end."""
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
            "import sys, os, pandas as pd, json\n"
            "df = pd.read_csv(sys.argv[1])\n"
            "df['score_squared'] = df['score'] ** 2\n"
            "out_dir = sys.argv[2]\n"
            "df.to_csv(os.path.join(out_dir, 'output.csv'), index=False)\n"
            "print(json.dumps({"
            "'charts': [], "
            "'statistics': {'mean_sq': df['score_squared'].mean()}, "
            "'insights': ['computed score_squared']"
            "}))\n"
        )

        # Unit 2: read upstream data (has score_squared), compute category
        script_u2 = (
            "import sys, os, pandas as pd, json\n"
            "df = pd.read_csv(sys.argv[1])\n"
            "df['score_category'] = df['score'].apply("
            "lambda x: 'high' if x > 90 else 'low')\n"
            "out_dir = sys.argv[2]\n"
            "df.to_csv(os.path.join(out_dir, 'output.csv'), index=False)\n"
            "print(json.dumps({"
            "'charts': [], "
            "'statistics': {'high': int((df['score_category'] == 'high').sum())}, "
            "'insights': ['computed score_category']"
            "}))\n"
        )

        # Unit 3: read upstream data (has score_category), final stats
        script_u3 = (
            "import sys, os, pandas as pd, json\n"
            "df = pd.read_csv(sys.argv[1])\n"
            "out_dir = sys.argv[2]\n"
            "df.to_csv(os.path.join(out_dir, 'output.csv'), index=False)\n"
            "print(json.dumps({"
            "'charts': [], "
            "'statistics': {'rows': len(df)}, "
            "'insights': ['final analysis']"
            "}))\n"
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

        # Verify unit 3 had access to upstream columns (score_squared, score_category)
        ur3 = unit_results[3]
        assert ur3["statistics"]["rows"] == 5  # all 5 rows passed through

        # Verify call order: exactly 3 LLM invocations (no retries)
        assert mock_llm.invoke.call_count == 3

    finally:
        os.unlink(csv_path)
