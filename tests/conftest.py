from __future__ import annotations

import csv
import os
import tempfile
from collections.abc import Callable
from typing import Any

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


@pytest.fixture(autouse=True)
def set_llm_env() -> None:
    """Set minimal env vars so LLM factory doesn't error (real key not needed for mock tests)."""
    os.environ["DATAINSIGHT_LLM_MODEL"] = "gpt-4o"
    os.environ["DATAINSIGHT_LLM_API_KEY"] = "sk-test-mock"
    os.environ["DATAINSIGHT_LLM_BASE_URL"] = "https://api.openai.com/v1"
    os.environ["DATAINSIGHT_TIMEOUT_CLEANING"] = "60"
    os.environ["DATAINSIGHT_TIMEOUT_ANALYSIS"] = "30"


@pytest.fixture
def sample_analysis_result() -> dict:
    """A successful analysis_result (new unit_results shape) for report_gen and graph tests."""
    return {
        "status": "complete",
        "unit_results": [
            {
                "unit_id": 1,
                "status": "success",
                "parsed_output": {
                    "charts": ["out/sales_trend.png", "out/revenue_by_region.png"],
                    "statistics": {"correlations": {"sales": {"revenue": 0.85}}},
                    "insights": ["Sales peaked in Q3", "Revenue correlates with marketing spend"],
                },
                "charts": ["out/sales_trend.png", "out/revenue_by_region.png"],
                "insights": ["Sales peaked in Q3", "Revenue correlates with marketing spend"],
                "statistics": {"correlations": {"sales": {"revenue": 0.85}}},
                "error": None,
                "retry_count": 0,
                "scripts": ["/tmp/datainsight_u1_script.py"],
                "stdout": '{"charts": ["out/sales_trend.png"], "statistics": {}, "insights": []}',
                "output_dir": "/tmp/datainsight_test_out/unit_1",
            }
        ],
    }


@pytest.fixture
def sample_data_profile() -> object:
    """A minimal DataProfile for planner and report_gen tests."""
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
    """A minimal AnalysisIntent for planner and report_gen tests."""
    from src.agent.state import AnalysisIntent, Suggestion

    return AnalysisIntent(
        core_question="Why did Q2 sales drop by 15%?",
        target_variable="sales",
        analysis_type="diagnostic",
        dimensions=["time period", "region", "product category"],
        comparison_baseline="Q1 of same year",
        expanded_question=(
            "Analyze Q2 sales decline of 15% vs Q1 — diagnose root causes "
            "across time trends, regional breakdown, and product category mix shifts"
        ),
        complexity="moderate",
        suggestions=[
            Suggestion(
                category="dimension",
                content="按时间维度分解以发现季节性模式或具体下滑时间点",
                rationale="15%的下降可能是某个时间点集中发生的",
            ),
            Suggestion(
                category="dimension",
                content="按地区细分以发现地理差异",
                rationale="地区差异是销售波动的常见原因",
            ),
            Suggestion(
                category="method",
                content="使用相关性分析识别与销售下降关联的因素",
                rationale="多变量相关性有助于定位根因",
            ),
        ],
        caution_notes="相关性不等于因果关系；外部因素（政策、竞争）可能未体现在数据中",
    )


@pytest.fixture
def sample_plan() -> object:
    """A minimal Plan (1 analysis unit) for preprocessing, analysis, and graph tests."""
    from src.agent.state import Plan, PlanUnit

    return Plan(
        cleaning=PlanUnit(
            unit_id=0,
            purpose="处理缺失值和异常值",
            cautious="0值可能是实际销售数据而非缺失",
        ),
        units=[
            PlanUnit(
                unit_id=1,
                purpose="按区域分析销售趋势",
                model="线性回归",
                cautious="region列有2%缺失值",
            )
        ],
        alignment_notes="基于当前数据，能够部分回答用户问题。",
    )


@pytest.fixture
def sample_plan_multi() -> object:
    """A Plan with 3 analysis units for multi-unit execution tests."""
    from src.agent.state import Plan, PlanUnit

    return Plan(
        cleaning=PlanUnit(
            unit_id=0,
            purpose="处理缺失值和异常值",
            cautious="0值可能是实际销售数据",
        ),
        units=[
            PlanUnit(
                unit_id=1,
                purpose="相关性分析",
                model="皮尔逊相关",
                cautious="样本量可能不足",
            ),
            PlanUnit(
                unit_id=2,
                purpose="聚类分析",
                model="KMeans",
                cautious="需先标准化",
            ),
            PlanUnit(
                unit_id=3,
                purpose="趋势预测",
                model="线性回归",
                cautious="时间序列需验证平稳性",
            ),
        ],
        alignment_notes="三个分析维度覆盖了用户问题的核心方面。",
    )


@pytest.fixture
def make_plan() -> Callable[..., object]:
    """Factory fixture for Plan with sensible defaults.

    Uses ``is not None`` checks so callers can pass ``None`` to clear
    fields (e.g. ``units=None`` to signal no analysis units).
    """

    from src.agent.state import Plan, PlanUnit

    def _make(**overrides: Any) -> Plan:
        cleaning = overrides.get("cleaning")
        if cleaning is None:
            cleaning = PlanUnit(
                unit_id=0,
                purpose="处理缺失值和异常值",
                cautious="0值可能是实际销售数据而非缺失",
            )

        units = overrides.get("units")
        if units is None:
            units = [
                PlanUnit(
                    unit_id=1,
                    purpose="按区域分析销售趋势",
                    model="线性回归",
                    cautious="region列有2%缺失值",
                )
            ]

        alignment_notes = overrides.get("alignment_notes")
        if alignment_notes is None:
            alignment_notes = "基于当前数据，本报告能够部分回答用户问题。"

        return Plan(
            cleaning=cleaning,
            units=units,
            alignment_notes=alignment_notes,
        )

    return _make


@pytest.fixture
def temp_output_dir() -> str:
    """Create a temporary directory for chart output in execution tests."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="datainsight_test_") as tmpdir:
        yield tmpdir
