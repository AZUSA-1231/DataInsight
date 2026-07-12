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
def sample_csv_with_dates() -> str:
    """Temp CSV with date/region/revenue/cost/volume columns for template testing."""
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "region", "revenue", "cost", "volume"])
        writer.writerow(["2023-01-15", "East", "1000", "600", "100"])
        writer.writerow(["2023-03-20", "West", "1500", "900", "150"])
        writer.writerow(["2023-06-10", "East", "2000", "1200", "200"])
        writer.writerow(["2024-01-05", "North", "800", "480", "80"])
        writer.writerow(["2024-05-18", "South", "2200", "1320", "220"])
        writer.writerow(["2024-09-30", "East", "1800", "1080", "180"])
        writer.writerow(["2025-02-14", "West", "2500", "1500", "250"])
        writer.writerow(["2025-07-01", "North", "1200", "720", "120"])
    yield path
    os.unlink(path)


@pytest.fixture
def sample_csv_100_rows() -> str:
    """Temp CSV with 100+ rows for MVP integration test (deterministic, seed=42)."""
    import random as _random

    _random.seed(42)

    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "region", "revenue", "cost", "volume"])

        regions = ["East", "West", "North", "South"]
        for i in range(120):
            year = 2023 + (i % 3)
            month = ((i * 3) % 12) + 1
            day = ((i * 7) % 28) + 1
            date = f"{year}-{month:02d}-{day:02d}"

            region = regions[i % 4]
            base_revenue = 800 + (i % 5) * 600 + _random.uniform(-100, 400)
            revenue = int(max(500, base_revenue))
            cost = int(revenue * (0.55 + _random.uniform(-0.08, 0.12)))
            volume = int(revenue / 8 + _random.uniform(-10, 30))

            writer.writerow([date, region, revenue, cost, volume])

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
                name="销量",
                dtype="float64",
                null_count=0,
                null_pct=0.0,
                unique_count=50,
                unique_pct=50.0,
            ),
            ColumnProfile(
                name="地区",
                dtype="object",
                null_count=2,
                null_pct=2.0,
                unique_count=4,
                unique_pct=4.0,
            ),
            ColumnProfile(
                name="日期",
                dtype="object",
                null_count=0,
                null_pct=0.0,
                unique_count=100,
                unique_pct=100.0,
            ),
        ],
        statistics={
            "销量": {"mean": 500.0, "std": 150.0, "min": 100.0, "max": 900.0},
            "地区": {"count": 98, "unique": 4, "top": "East", "freq": 30},
        },
        head_sample=[
            {"销量": 500.0, "地区": "East", "日期": "2024-01-15"},
            {"销量": 300.0, "地区": "West", "日期": "2024-01-16"},
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
    """A minimal Plan (1 analysis unit) for analysis and graph tests."""
    from src.agent.state import Plan, PlanUnit

    return Plan(
        units=[
            PlanUnit(
                unit_id=1,
                purpose="按区域分析销售趋势",
                model="线性回归",
                cautious="region列有2%缺失值",
                related_fields=[],
            )
        ],
        alignment_notes="基于当前数据，能够部分回答用户问题。",
    )


@pytest.fixture
def sample_plan_multi() -> object:
    """A Plan with 3 analysis units for multi-unit execution tests."""
    from src.agent.state import Plan, PlanUnit

    return Plan(
        units=[
            PlanUnit(
                unit_id=1,
                purpose="相关性分析",
                model="皮尔逊相关",
                cautious="样本量可能不足",
                related_fields=[],
            ),
            PlanUnit(
                unit_id=2,
                purpose="聚类分析",
                model="KMeans",
                cautious="需先标准化",
                related_fields=[],
            ),
            PlanUnit(
                unit_id=3,
                purpose="趋势预测",
                model="线性回归",
                cautious="时间序列需验证平稳性",
                related_fields=[],
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
        units = overrides.get("units")
        if units is None:
            units = [
                PlanUnit(
                    unit_id=1,
                    purpose="按区域分析销售趋势",
                    model="线性回归",
                    cautious="region列有2%缺失值",
                    related_fields=[],
                )
            ]

        alignment_notes = overrides.get("alignment_notes")
        if alignment_notes is None:
            alignment_notes = "基于当前数据，本报告能够部分回答用户问题。"

        return Plan(
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


@pytest.fixture
def sample_planner_instruction() -> object:
    """A minimal PlannerInstruction for BT Agent and Planner Agent tests."""
    from src.agent.state import PlannerInstruction, Suggestion, UnitSuggestion

    return PlannerInstruction(
        core_question="Why did Q2 sales drop by 15%?",
        analysis_type="diagnostic",
        complexity="moderate",
        target_columns=["sales"],
        group_by=["region", "date"],
        filter_hint=None,
        unit_suggestions=[
            UnitSuggestion(
                purpose="按地区和季度分析销售趋势",
                model="线性回归",
                related_fields=["sales", "region", "date"],
                cautious="region列有2%空值",
            )
        ],
        is_revision=False,
        target_unit_ids=[],
        revision_notes=None,
        suggestions=[
            Suggestion(
                category="dimension",
                content="按时间维度分解以发现季节性模式",
                rationale="15%下降可能是某个时间点集中发生的",
            )
        ],
        caution_notes="相关性不等于因果关系",
        instruction_nl=(
            "用户想要诊断Q2销售下降15%的原因。数据包含sales、region、"
            "date等列。我建议按地区和日期维度分解，同时检查不同产品类别的"
            "表现差异。需要注意region列有少量空值，清洗时应处理。"
        ),
    )


@pytest.fixture
def bt_tool_call_msg() -> object:
    """Build a mock AIMessage simulating a BT submit_planner_instruction tool call."""
    from langchain_core.messages import AIMessage

    return AIMessage(
        content="好的，我已经理解了您的需求。让我将分析指令提交给Planner。",
        tool_calls=[
            {
                "name": "submit_planner_instruction",
                "args": {
                    "core_question": "Why did Q2 sales drop by 15%?",
                    "analysis_type": "diagnostic",
                    "complexity": "moderate",
                    "target_columns": ["sales"],
                    "group_by": ["region", "date"],
                    "filter_hint": None,
                    "unit_suggestions": [],
                    "is_revision": False,
                    "target_unit_ids": [],
                    "revision_notes": None,
                    "suggestions": [],
                    "caution_notes": None,
                    "instruction_nl": "用户需要诊断Q2销售下降15%的根因。按地区和日期分解趋势。",
                },
                "id": "call_test_001",
            }
        ],
    )


@pytest.fixture
def bt_chat_msg() -> object:
    """Build a mock AIMessage simulating a BT conversational response."""
    from langchain_core.messages import AIMessage

    return AIMessage(
        content="您想从哪个维度分析销售数据呢？是按地区、按时间趋势，还是按产品类别？"
    )


@pytest.fixture
def api_client():
    """FastAPI TestClient for API route tests."""
    from fastapi.testclient import TestClient

    from src.api.app import app
    from src.api.session import SessionStore

    # TestClient doesn't trigger lifespan — init session store manually
    app.state.sessions = SessionStore()
    return TestClient(app)


@pytest.fixture
def test_session(api_client):
    """Create a test session and return its ID."""
    resp = api_client.post("/api/sessions", json={"user_requirement": "分析销售数据"})
    assert resp.status_code == 200
    return resp.json()["session_id"]
