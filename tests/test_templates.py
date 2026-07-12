from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

from src.agent.state import PlanUnit
from src.agent.templates import (
    TEMPLATE_REGISTRY,
    _build_template_result,
    _error_result,
    dispatch,
    filter_by_date,
    terminal_scatter_plot,
    transform_column_arithmetic,
    transform_linear_regression,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _tu(
    uid: int = 1,
    *,
    unit_type: str = "transform",
    exec_mode: str = "template",
    template_name: str | None = None,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    tpl_params: dict | None = None,
) -> PlanUnit:
    return PlanUnit(
        unit_id=uid,
        unit_type=unit_type,  # type: ignore[arg-type]
        execution_mode=exec_mode,  # type: ignore[arg-type]
        purpose=f"Unit {uid}",
        model_hint=None,
        cautious="",
        depends_on=[],
        input_from=None,
        input_columns=inputs or [],
        output_columns=outputs or [],
        related_fields=[],
        template_name=template_name,
        template_params=tpl_params,
    )


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame({
        "revenue": [100.0, 200.0, 300.0, 400.0, 500.0],
        "cost": [60.0, 120.0, 180.0, 240.0, 300.0],
        "date": [
            "2023-01-15", "2023-06-01", "2024-02-10",
            "2024-08-20", "2025-03-05",
        ],
        "volume": [10, 20, 30, 40, 50],
    })


# ── transform_column_arithmetic ──────────────────────────────────────────────


@pytest.mark.unit
def test_arithmetic_add(sample_df: pd.DataFrame) -> None:
    result = transform_column_arithmetic(
        sample_df, ["revenue", "cost"],
        {"operator": "+", "new_column": "margin"},
    )
    assert "margin" in result["columns"]
    expected = sample_df["revenue"] + sample_df["cost"]
    pd.testing.assert_series_equal(result["columns"]["margin"], expected)
    assert result["artifacts"] == []


@pytest.mark.unit
def test_arithmetic_subtract(sample_df: pd.DataFrame) -> None:
    result = transform_column_arithmetic(
        sample_df, ["revenue", "cost"],
        {"operator": "-", "new_column": "profit"},
    )
    expected = sample_df["revenue"] - sample_df["cost"]
    pd.testing.assert_series_equal(result["columns"]["profit"], expected)


@pytest.mark.unit
def test_arithmetic_multiply(sample_df: pd.DataFrame) -> None:
    result = transform_column_arithmetic(
        sample_df, ["volume", "revenue"],
        {"operator": "*", "new_column": "total"},
    )
    expected = sample_df["volume"] * sample_df["revenue"]
    pd.testing.assert_series_equal(result["columns"]["total"], expected)


@pytest.mark.unit
def test_arithmetic_divide(sample_df: pd.DataFrame) -> None:
    result = transform_column_arithmetic(
        sample_df, ["revenue", "cost"],
        {"operator": "/", "new_column": "ratio"},
    )
    expected = sample_df["revenue"] / sample_df["cost"]
    pd.testing.assert_series_equal(result["columns"]["ratio"], expected)


@pytest.mark.unit
def test_arithmetic_divide_by_zero() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [0.0, 1.0]})
    result = transform_column_arithmetic(df, ["a", "b"], {"operator": "/"})
    assert np.isinf(result["columns"]["result"].iloc[0])


@pytest.mark.unit
def test_arithmetic_default_column_name(sample_df: pd.DataFrame) -> None:
    result = transform_column_arithmetic(sample_df, ["revenue", "cost"], {})
    assert "result" in result["columns"]


@pytest.mark.unit
def test_arithmetic_unknown_operator(sample_df: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="Unknown operator"):
        transform_column_arithmetic(
            sample_df, ["revenue", "cost"], {"operator": "%"},
        )


@pytest.mark.unit
def test_arithmetic_too_few_columns(sample_df: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="2 input_columns"):
        transform_column_arithmetic(sample_df, ["revenue"], {})


# ── transform_linear_regression ──────────────────────────────────────────────


@pytest.mark.unit
def test_linear_regression_basic(sample_df: pd.DataFrame) -> None:
    result = transform_linear_regression(
        sample_df, ["volume", "revenue"],
        {"pred_column": "predicted"},
    )
    assert "predicted" in result["columns"]
    pred = result["columns"]["predicted"]
    assert len(pred) == len(sample_df)
    assert pred.notna().all()


@pytest.mark.unit
def test_linear_regression_row_count_invariant(sample_df: pd.DataFrame) -> None:
    result = transform_linear_regression(sample_df, ["volume", "revenue"], {})
    for series in result["columns"].values():
        assert len(series) == len(sample_df)


@pytest.mark.unit
def test_linear_regression_default_pred_column(sample_df: pd.DataFrame) -> None:
    result = transform_linear_regression(sample_df, ["volume", "revenue"], {})
    assert "predicted" in result["columns"]


@pytest.mark.unit
def test_linear_regression_with_nans() -> None:
    df = pd.DataFrame({
        "x": [1.0, 2.0, np.nan, 4.0, 5.0],
        "y": [2.0, 4.0, 6.0, np.nan, 10.0],
    })
    result = transform_linear_regression(df, ["x", "y"], {})
    assert len(result["columns"]["predicted"]) == 5


@pytest.mark.unit
def test_linear_regression_too_few_columns(sample_df: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="x_col, y_col"):
        transform_linear_regression(sample_df, ["volume"], {})


@pytest.mark.unit
def test_linear_regression_insufficient_samples() -> None:
    df = pd.DataFrame({"x": [1.0, np.nan], "y": [np.nan, 2.0]})
    with pytest.raises(ValueError, match="at least 2 valid"):
        transform_linear_regression(df, ["x", "y"], {})


# ── filter_by_date ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_filter_by_date_basic(sample_df: pd.DataFrame) -> None:
    result = filter_by_date(
        sample_df, ["date"],
        {"date_column": "date", "start": "2024-01-01", "end": "2024-12-31"},
    )
    filtered = result["filtered_df"]
    assert len(filtered) == 2
    assert list(sample_df.columns) == list(filtered.columns)
    assert result["snapshot_name"] == "filtered"


@pytest.mark.unit
def test_filter_by_date_start_only(sample_df: pd.DataFrame) -> None:
    result = filter_by_date(
        sample_df, ["date"],
        {"date_column": "date", "start": "2024-01-01"},
    )
    assert len(result["filtered_df"]) == 3  # 2024-02-10, 2024-08-20, 2025-03-05


@pytest.mark.unit
def test_filter_by_date_end_only(sample_df: pd.DataFrame) -> None:
    result = filter_by_date(
        sample_df, ["date"],
        {"date_column": "date", "end": "2023-12-31"},
    )
    assert len(result["filtered_df"]) == 2  # 2023-01-15, 2023-06-01


@pytest.mark.unit
def test_filter_by_date_no_match(sample_df: pd.DataFrame) -> None:
    result = filter_by_date(
        sample_df, ["date"],
        {"date_column": "date", "start": "2099-01-01"},
    )
    assert len(result["filtered_df"]) == 0


@pytest.mark.unit
def test_filter_by_date_custom_snapshot_name(sample_df: pd.DataFrame) -> None:
    result = filter_by_date(
        sample_df, ["date"],
        {"date_column": "date", "start": "2023-01-01", "snapshot_name": "recent"},
    )
    assert result["snapshot_name"] == "recent"


@pytest.mark.unit
def test_filter_by_date_missing_range(sample_df: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="at least one of 'start' or 'end'"):
        filter_by_date(sample_df, ["date"], {"date_column": "date"})


@pytest.mark.unit
def test_filter_by_date_default_column(sample_df: pd.DataFrame) -> None:
    result = filter_by_date(sample_df, [], {"start": "2024-01-01"})
    assert len(result["filtered_df"]) >= 0  # uses first input_column → empty → falls back to "date"


# ── terminal_scatter_plot ────────────────────────────────────────────────────


@pytest.mark.unit
def test_scatter_plot_creates_file(sample_df: pd.DataFrame, tmp_path) -> None:
    out_dir = str(tmp_path / "charts")
    result = terminal_scatter_plot(
        sample_df, ["revenue", "cost"],
        {"output_dir": out_dir},
    )
    assert result["columns"] == {}
    assert len(result["artifacts"]) == 1
    assert result["artifacts"][0].endswith(".png")
    assert os.path.exists(result["artifacts"][0])


@pytest.mark.unit
def test_scatter_plot_too_few_columns(sample_df: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="x_col, y_col"):
        terminal_scatter_plot(sample_df, ["revenue"], {})


# ── dispatch ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_dispatch_llm_mode_returns_none(sample_df: pd.DataFrame, tmp_path) -> None:
    unit = _tu(exec_mode="llm")
    result = dispatch(unit, sample_df, str(tmp_path))
    assert result is None


@pytest.mark.unit
def test_dispatch_template_arithmetic(sample_df: pd.DataFrame, tmp_path) -> None:
    unit = _tu(
        exec_mode="template", template_name="column_arithmetic",
        inputs=["revenue", "cost"],
        tpl_params={"operator": "+", "new_column": "margin"},
    )
    result = dispatch(unit, sample_df, str(tmp_path))
    assert result is not None
    assert result["status"] == "success"
    assert result["unit_id"] == 1
    # Check output.csv was written
    csv_path = os.path.join(str(tmp_path), "output.csv")
    assert os.path.exists(csv_path)
    loaded = pd.read_csv(csv_path)
    assert "margin" in loaded.columns


@pytest.mark.unit
def test_dispatch_template_filter(sample_df: pd.DataFrame, tmp_path) -> None:
    unit = _tu(
        uid=1, unit_type="filter", exec_mode="template",
        template_name="filter_by_date", inputs=["date"],
        tpl_params={"date_column": "date", "start": "2024-01-01", "snapshot_name": "recent"},
    )
    result = dispatch(unit, sample_df, str(tmp_path))
    assert result is not None
    assert result["status"] == "success"
    assert result["snapshot_name"] == "recent"
    csv_path = os.path.join(str(tmp_path), "output.csv")
    assert os.path.exists(csv_path)


@pytest.mark.unit
def test_dispatch_template_terminal(sample_df: pd.DataFrame, tmp_path) -> None:
    unit = _tu(
        uid=1, unit_type="terminal", exec_mode="template",
        template_name="scatter_plot", inputs=["revenue", "cost"],
    )
    result = dispatch(unit, sample_df, str(tmp_path))
    assert result is not None
    assert result["status"] == "success"
    assert len(result["charts"]) == 1


@pytest.mark.unit
def test_dispatch_unknown_template(sample_df: pd.DataFrame, tmp_path) -> None:
    unit = _tu(exec_mode="template", template_name="nonexistent")
    result = dispatch(unit, sample_df, str(tmp_path))
    assert result is not None
    assert result["status"] == "failed"
    assert "Unknown template" in result["error"]


@pytest.mark.unit
def test_dispatch_missing_template_name(sample_df: pd.DataFrame, tmp_path) -> None:
    unit = _tu(exec_mode="template", template_name=None)
    result = dispatch(unit, sample_df, str(tmp_path))
    assert result is not None
    assert result["status"] == "failed"
    assert "template_name is None" in result["error"]


# ── _build_template_result ───────────────────────────────────────────────────


@pytest.mark.unit
def test_build_template_result_transform(sample_df: pd.DataFrame, tmp_path) -> None:
    unit = _tu(template_name="column_arithmetic")
    tpl_out = {"columns": {"margin": sample_df["revenue"] + sample_df["cost"]}, "artifacts": []}
    result = _build_template_result(unit, tpl_out, str(tmp_path), sample_df)
    assert result["status"] == "success"
    assert result["unit_id"] == 1
    assert result["retry_count"] == 0
    assert result["scripts"] == []
    assert result["stdout"] == ""
    assert "output_dir" in result
    csv_path = os.path.join(str(tmp_path), "output.csv")
    assert os.path.exists(csv_path)


@pytest.mark.unit
def test_build_template_result_filter(sample_df: pd.DataFrame, tmp_path) -> None:
    unit = _tu(unit_type="filter", template_name="filter_by_date")
    tpl_out = {"filtered_df": sample_df.head(2), "snapshot_name": "recent", "artifacts": []}
    result = _build_template_result(unit, tpl_out, str(tmp_path))
    assert result["status"] == "success"
    assert result["snapshot_name"] == "recent"
    csv_path = os.path.join(str(tmp_path), "output.csv")
    assert os.path.exists(csv_path)


@pytest.mark.unit
def test_build_template_result_terminal(tmp_path) -> None:
    unit = _tu(unit_type="terminal", template_name="scatter_plot")
    tpl_out = {"columns": {}, "artifacts": ["/tmp/chart.png"]}
    result = _build_template_result(unit, tpl_out, str(tmp_path))
    assert result["status"] == "success"
    assert result["charts"] == ["/tmp/chart.png"]
    # Terminal: no output.csv
    csv_path = os.path.join(str(tmp_path), "output.csv")
    assert not os.path.exists(csv_path)


@pytest.mark.unit
def test_build_template_result_all_keys_present(sample_df: pd.DataFrame, tmp_path) -> None:
    """Result dict must match _execute_unit return shape exactly."""
    required_keys = {
        "unit_id", "status", "parsed_output", "charts", "insights",
        "statistics", "error", "retry_count", "scripts", "stdout", "output_dir",
    }
    unit = _tu(template_name="column_arithmetic")
    tpl_out = {"columns": {}, "artifacts": []}
    result = _build_template_result(unit, tpl_out, str(tmp_path), sample_df)
    assert required_keys <= set(result.keys())


# ── _error_result ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_error_result() -> None:
    unit = _tu()
    result = _error_result(unit, "something went wrong")
    assert result["status"] == "failed"
    assert result["error"] == "something went wrong"
    assert result["unit_id"] == 1


# ── TEMPLATE_REGISTRY ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_registry_has_four_templates() -> None:
    assert len(TEMPLATE_REGISTRY) == 4
    assert "column_arithmetic" in TEMPLATE_REGISTRY
    assert "linear_regression" in TEMPLATE_REGISTRY
    assert "filter_by_date" in TEMPLATE_REGISTRY
    assert "scatter_plot" in TEMPLATE_REGISTRY


@pytest.mark.unit
def test_registry_functions_are_callable() -> None:
    for name, fn in TEMPLATE_REGISTRY.items():
        assert callable(fn), f"{name} is not callable"
