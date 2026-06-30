from __future__ import annotations

import csv
import os
import tempfile

import pytest


@pytest.fixture
def sample_csv_path() -> str:
    """Create a temporary CSV with realistic messy data for testing."""
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "age", "salary", "dept", "hire_date"])
        writer.writerow(["Alice", "30", "75000", "Engineering", "2020-01-15"])
        writer.writerow(["Bob", "", "82000", "Sales", "2019-06-01"])
        writer.writerow(["Charlie", "45", "", "Engineering", ""])
        writer.writerow(["Diana", "28", "65000", "", "2022-03-10"])
        writer.writerow(["Eve", "0", "92000", "Marketing", "2018-11-20"])
    yield path
    os.unlink(path)


@pytest.fixture
def sample_xlsx_path() -> str:
    """Create a temporary XLSX file for testing Excel support."""
    import pandas as pd

    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    df = pd.DataFrame(
        {
            "name": ["Alice", "Bob", "Charlie"],
            "score": [95, 87, None],
            "grade": ["A", "B", "B"],
        }
    )
    df.to_excel(path, index=False)
    yield path
    os.unlink(path)


@pytest.fixture
def set_llm_env() -> None:
    """Set minimal env vars so LLM factory doesn't error (real key not needed for mock tests)."""
    os.environ["DATAINSIGHT_LLM_MODEL"] = "gpt-4o"
    os.environ["DATAINSIGHT_LLM_API_KEY"] = "sk-test-mock"
    os.environ["DATAINSIGHT_LLM_BASE_URL"] = "https://api.openai.com/v1"


@pytest.fixture
def sample_execution_result() -> dict:
    """A successful execution_result for report_gen and graph integration tests."""
    return {
        "retry_count": 0,
        "attempts": [],
        "script_path": "/tmp/datainsight_test_script.py",
        "output_dir": "/tmp/datainsight_test_out",
        "stdout": '{"cleaned_shape": {"rows": 100, "cols": 5}}',
        "parsed_output": {
            "cleaned_shape": {"rows": 100, "cols": 5},
            "cleaning_actions": ["Dropped 3 rows with null values", "Imputed age with median"],
            "charts": ["out/sales_trend.png", "out/revenue_by_region.png"],
            "statistics": {"correlations": {"sales": {"revenue": 0.85}}},
            "insights": ["Sales peaked in Q3", "Revenue correlates with marketing spend"],
        },
    }


@pytest.fixture
def sample_data_profile() -> object:
    """A minimal DataProfile for decision_match and report_gen tests."""
    from src.agent.state import ColumnProfile, DataProfile

    return DataProfile(
        file_path="/tmp/test.csv",
        shape=(100, 5),
        columns=[
            ColumnProfile(
                name="sales",
                dtype="float64",
                null_count=0,
                null_pct=0.0,
                unique_count=50,
                unique_pct=50.0,
            ),
            ColumnProfile(
                name="region",
                dtype="object",
                null_count=2,
                null_pct=2.0,
                unique_count=4,
                unique_pct=4.0,
            ),
            ColumnProfile(
                name="date",
                dtype="object",
                null_count=0,
                null_pct=0.0,
                unique_count=100,
                unique_pct=100.0,
            ),
        ],
        statistics={
            "sales": {"mean": 500.0, "std": 150.0, "min": 100.0, "max": 900.0},
            "region": {"count": 98, "unique": 4, "top": "East", "freq": 30},
        },
        head_sample=[
            {"sales": 500.0, "region": "East", "date": "2024-01-15"},
            {"sales": 300.0, "region": "West", "date": "2024-01-16"},
        ],
    )


@pytest.fixture
def sample_analysis_intent() -> object:
    """A minimal AnalysisIntent for decision_match and report_gen tests."""
    from src.agent.state import AnalysisIntent

    return AnalysisIntent(
        core_question="Why did Q2 sales drop by 15%?",
        target_variable="sales",
        analysis_type="diagnostic",
        dimensions=["time period", "region", "product category"],
        comparison_baseline="Q1 of same year",
    )


@pytest.fixture
def sample_execution_plan() -> object:
    """A minimal ExecutionPlan for execution, report_gen, and graph tests."""
    from src.agent.state import ExecutionPlan

    return ExecutionPlan(
        feasibility_map=[
            {
                "intent_dimension": "region",
                "matched_columns": ["region"],
                "feasibility": "可直接实现",
                "confidence": "High",
                "reasoning": "Column 'region' directly matches the intent dimension",
            }
        ],
        model_selections=[
            {
                "analysis_step": "Sales trend analysis",
                "method": "pandas.DataFrame.corr + scipy.stats.ttest_ind",
                "reasoning": "Continuous target with categorical dimension — t-test appropriate",
                "feasibility": "可直接实现",
            }
        ],
        preprocessing_steps=[
            {
                "step": 1,
                "action": "drop_null_rows",
                "target_columns": ["region"],
                "urgency": "高优先",
                "reason": "2% nulls in region column — small loss acceptable",
            }
        ],
        analysis_steps=[
            {
                "step": 1,
                "action": "compute_correlation",
                "target_columns": ["sales", "region"],
                "method": "pandas.DataFrame.corr",
                "expected_output": "correlation matrix",
            }
        ],
        alignment_notes="基于当前数据，本报告能够部分回答用户问题。",
    )


@pytest.fixture
def temp_output_dir() -> str:
    """Create a temporary directory for chart output in execution tests."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="datainsight_test_") as tmpdir:
        yield tmpdir
