"""Template functions for deterministic in-process unit execution.

Each template follows the per-unit-type contract defined in the Cycle 4 PRD:

  Transform: (df, input_columns, params) -> {"columns": {name: Series}, "artifacts": []}
  Filter:    (df, input_columns, params)
             -> {"filtered_df": DataFrame, "snapshot_name": str, "artifacts": []}
  Terminal:  (df, input_columns, params) -> {"columns": {}, "artifacts": [path, ...]}

``dispatch()`` routes by ``execution_mode`` and returns a result dict matching
``_execute_unit``'s return shape, or ``None`` for LLM-mode units (caller falls
through to the existing LLM→sandbox→ReAct path).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from src.agent.state import ExecutionMode, PlanUnit

logger = logging.getLogger(__name__)

TemplateFunc = Callable[[pd.DataFrame, list[str], dict[str, Any]], dict[str, Any]]


# ── Transform templates ──────────────────────────────────────────────────────


def transform_column_arithmetic(
    df: pd.DataFrame,
    input_columns: list[str],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Element-wise arithmetic on two columns.

    ``input_columns``: [col_a, col_b]
    ``params``: {"operator": "+|-|*|/", "new_column": "result"}
    """
    if len(input_columns) < 2:
        raise ValueError(
            f"column_arithmetic requires 2 input_columns, got {len(input_columns)}"
        )

    col_a, col_b = input_columns[0], input_columns[1]
    operator = params.get("operator", "+")
    new_column = params.get("new_column", "result")

    ops: dict[str, Callable[[pd.Series, pd.Series], pd.Series]] = {
        "+": lambda a, b: a + b,
        "-": lambda a, b: a - b,
        "*": lambda a, b: a * b,
        "/": lambda a, b: a / b,
    }

    op_fn = ops.get(operator)
    if op_fn is None:
        raise ValueError(f"Unknown operator '{operator}'. Use +, -, *, /")

    return {"columns": {new_column: op_fn(df[col_a], df[col_b])}, "artifacts": []}


def transform_linear_regression(
    df: pd.DataFrame,
    input_columns: list[str],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Linear regression: fit X → y, return predictions as a new column.

    ``input_columns``: [x_column, y_column]
    ``params``: {"pred_column": "predicted"}
    """
    try:
        from sklearn.linear_model import LinearRegression
    except ImportError as err:
        raise ImportError(
            "scikit-learn is required for the linear_regression template. "
            "Install it with: pip install scikit-learn"
        ) from err

    if len(input_columns) < 2:
        raise ValueError(
            f"linear_regression requires [x_col, y_col] in input_columns, "
            f"got {len(input_columns)}"
        )

    x_col, y_col = input_columns[0], input_columns[1]
    pred_column = params.get("pred_column", "predicted")

    x_vals = df[[x_col]].values.astype(float)
    y_vals = df[y_col].values.astype(float)

    mask = ~(np.isnan(x_vals.flatten()) | np.isnan(y_vals))
    if mask.sum() < 2:
        raise ValueError(
            f"linear_regression needs at least 2 valid (non-NaN) samples, "
            f"got {mask.sum()}"
        )

    x_clean = x_vals[mask].reshape(-1, 1)
    y_clean = y_vals[mask]

    model = LinearRegression()
    model.fit(x_clean, y_clean)

    predicted = np.full(len(df), np.nan)
    predicted[mask] = model.predict(x_clean)

    return {
        "columns": {pred_column: pd.Series(predicted, index=df.index)},
        "artifacts": [],
    }


# ── Filter templates ─────────────────────────────────────────────────────────


def filter_by_date(
    df: pd.DataFrame,
    input_columns: list[str],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Filter rows by date range.

    ``input_columns``: optional, overridden by ``params["date_column"]``
    ``params``: {"date_column": str, "start": str, "end": str, "snapshot_name": str}
    """
    date_column = params.get("date_column", input_columns[0] if input_columns else "date")
    start = params.get("start")
    end = params.get("end")
    snapshot_name = params.get("snapshot_name", "filtered")

    if start is None and end is None:
        raise ValueError("filter_by_date requires at least one of 'start' or 'end'")

    date_series = pd.to_datetime(df[date_column], errors="coerce")

    mask = pd.Series(True, index=df.index)
    if start is not None:
        mask &= date_series >= pd.Timestamp(start)
    if end is not None:
        mask &= date_series <= pd.Timestamp(end)

    return {
        "filtered_df": df[mask].copy(),
        "snapshot_name": snapshot_name,
        "artifacts": [],
    }


# ── Terminal templates ───────────────────────────────────────────────────────


def terminal_scatter_plot(
    df: pd.DataFrame,
    input_columns: list[str],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Scatter plot of two columns, saved as PNG.

    ``input_columns``: [x_col, y_col]
    ``params``: {"title": str, "x_label": str, "y_label": str, "output_dir": str}
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if len(input_columns) < 2:
        raise ValueError(
            f"scatter_plot requires [x_col, y_col] in input_columns, "
            f"got {len(input_columns)}"
        )

    x_col, y_col = input_columns[0], input_columns[1]
    title = params.get("title", f"{y_col} vs {x_col}")
    x_label = params.get("x_label", x_col)
    y_label = params.get("y_label", y_col)
    output_dir = params.get("output_dir", ".")

    plt.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots()
    ax.scatter(df[x_col], df[y_col], alpha=0.6)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title)

    os.makedirs(output_dir, exist_ok=True)
    artifact_path = os.path.join(output_dir, "scatter.png")
    fig.savefig(artifact_path, dpi=100, bbox_inches="tight")
    plt.close(fig)

    return {"columns": {}, "artifacts": [artifact_path]}


# ── Registry ─────────────────────────────────────────────────────────────────

TEMPLATE_REGISTRY: dict[str, TemplateFunc] = {
    "column_arithmetic": transform_column_arithmetic,
    "linear_regression": transform_linear_regression,
    "filter_by_date": filter_by_date,
    "scatter_plot": terminal_scatter_plot,
}

# ── Dispatch ─────────────────────────────────────────────────────────────────


def dispatch(
    unit: PlanUnit, df: pd.DataFrame, output_dir: str
) -> dict[str, Any] | None:
    """Route a PlanUnit to its template or signal fall-through to LLM path.

    Returns:
        A full result dict (matching ``_execute_unit`` return shape) for
        template-mode units, or ``None`` for LLM-mode units (caller should
        fall through to the existing LLM→sandbox→ReAct path).
    """
    if unit.execution_mode == ExecutionMode.LLM:
        return None

    if unit.execution_mode != ExecutionMode.TEMPLATE:
        return _error_result(
            unit, f"Unknown execution_mode: {unit.execution_mode}"
        )

    if not unit.template_name:
        return _error_result(
            unit, "execution_mode=template but template_name is None"
        )

    template_fn = TEMPLATE_REGISTRY.get(unit.template_name)
    if template_fn is None:
        return _error_result(
            unit, f"Unknown template: '{unit.template_name}'"
        )

    params = dict(unit.template_params or {})
    params.setdefault("output_dir", output_dir)

    logger.info(
        "Template [%s] unit [%d]: executing in-process",
        unit.template_name, unit.unit_id,
    )

    try:
        template_output = template_fn(df, unit.input_columns, params)
    except Exception as e:
        logger.error(
            "Template [%s] unit [%d] failed: %s",
            unit.template_name, unit.unit_id, e,
        )
        return _error_result(
            unit, f"Template '{unit.template_name}' error: {e}"
        )

    return _build_template_result(unit, template_output, output_dir, df)


def _build_template_result(
    unit: PlanUnit,
    template_output: dict[str, Any],
    output_dir: str,
    df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build a result dict matching ``_execute_unit``'s return shape.

    Assembles the result DataFrame in-process (no CSV round-trip) and
    attaches it via ``_result_df`` so ``_save_unit_checkpoint`` can
    write the Parquet checkpoint directly.
    """
    artifacts: list[str] = list(template_output.get("artifacts", []))
    charts = [a for a in artifacts if a.lower().endswith(".png")]

    utype = unit.unit_type
    result_df: pd.DataFrame | None = None

    if utype == "transform" and df is not None:
        new_cols: dict[str, pd.Series] = template_output.get("columns", {})
        result_df = df.copy()
        for col_name, series in new_cols.items():
            result_df[col_name] = series
        # Also write output.csv for downstream LLM-mode units that read via file
        csv_path = os.path.join(output_dir, "output.csv")
        result_df.to_csv(csv_path, index=False)
    elif utype == "filter":
        filtered_df = template_output.get("filtered_df")
        if filtered_df is not None:
            result_df = filtered_df
            csv_path = os.path.join(output_dir, "output.csv")
            result_df.to_csv(csv_path, index=False)

    parsed_output: dict[str, Any] = {
        "charts": charts,
        "statistics": {},
        "insights": [f"Template: {unit.template_name}"],
    }

    result: dict[str, Any] = {
        "unit_id": unit.unit_id,
        "status": "success",
        "parsed_output": parsed_output,
        "charts": charts,
        "insights": parsed_output["insights"],
        "statistics": {},
        "error": None,
        "retry_count": 0,
        "scripts": [],
        "stdout": "",
        "output_dir": output_dir,
    }

    if utype == "filter" and "snapshot_name" in template_output:
        result["snapshot_name"] = template_output["snapshot_name"]

    if result_df is not None:
        result["_result_df"] = result_df
        result["_input_row_count"] = len(df) if df is not None else None

    return result


def _error_result(unit: PlanUnit, message: str) -> dict[str, Any]:
    """Build a failed result dict for template errors."""
    return {
        "unit_id": unit.unit_id,
        "status": "failed",
        "parsed_output": None,
        "charts": [],
        "insights": [],
        "statistics": {},
        "error": message,
        "retry_count": 0,
        "scripts": [],
        "stdout": "",
        "output_dir": "",
    }
