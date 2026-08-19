from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.agent.nodes.analysis import analysis_node

CYCLE5_FIXTURES = Path(__file__).parents[1] / "fixtures" / "cycle5"


def _upload(api_client, session_id: str, path: Path) -> None:
    with path.open("rb") as file:
        response = api_client.post(
            f"/api/sessions/{session_id}/data/upload",
            files={"file": (path.name, file, "text/csv")},
        )
    assert response.status_code == 200, response.text


def _derive(unit_id: int = 1) -> dict[str, object]:
    return {
        "unit_id": unit_id,
        "operation": "derive_column",
        "execution_mode": "template",
        "purpose": "derive revenue",
        "depends_on": [],
        "input_snapshot": "orders",
        "input_columns": ["orders.price", "orders.quantity"],
        "output_columns": ["orders.revenue"],
        "template_name": "column_arithmetic",
        "template_params": {"operator": "*", "new_column": "revenue"},
    }


def test_projection_exposes_planned_derive_without_registry_writes(
    api_client, test_session
):
    _upload(api_client, test_session, CYCLE5_FIXTURES / "orders.csv")
    store = api_client.app.state.sessions
    before = store.get(test_session)
    assert before is not None
    counts = (
        len(before.snapshot_registry),
        len(before.checkpoint_registry),
        len(before.column_graph.nodes),
    )

    plan = {
        "units": [
            _derive(),
            {
                "unit_id": 2,
                "operation": "terminal",
                "execution_mode": "template",
                "purpose": "inspect revenue",
                "depends_on": [1],
                "input_snapshot": "orders",
                "input_columns": ["orders.revenue"],
            },
        ],
        "alignment_notes": "",
    }
    saved = api_client.put(f"/api/sessions/{test_session}/workspace", json=plan)
    assert saved.status_code == 200, saved.text

    projection = api_client.get(
        f"/api/sessions/{test_session}/data/workspace-projection"
    )
    assert projection.status_code == 200, projection.text
    body = projection.json()
    orders = next(item for item in body["snapshots"] if item["name"] == "orders")
    revenue = next(item for item in body["columns"] if item["ref"] == "orders.revenue")
    assert orders["availability"] == "materialized"
    assert orders["row_count"] == 5
    assert revenue == {
        "ref": "orders.revenue",
        "name": "revenue",
        "snapshot": "orders",
        "dtype": None,
        "null_count": None,
        "null_pct": None,
        "source_column": None,
        "created_by_unit_id": 1,
        "availability": "planned",
    }

    after = store.get(test_session)
    assert after is not None
    assert (
        len(after.snapshot_registry),
        len(after.checkpoint_registry),
        len(after.column_graph.nodes),
    ) == counts


def test_projection_propagates_planned_schema_into_filter_output(
    api_client, test_session
):
    _upload(api_client, test_session, CYCLE5_FIXTURES / "orders.csv")
    plan = {
        "units": [
            _derive(),
            {
                "unit_id": 2,
                "operation": "filter",
                "execution_mode": "template",
                "purpose": "filter orders",
                "depends_on": [1],
                "input_snapshot": "orders",
                "input_columns": ["orders.revenue"],
                "output_snapshot": "east_orders",
                "template_name": "filter_by_date",
                "template_params": {"condition": "region == 'East'"},
            },
        ],
        "alignment_notes": "",
    }
    saved = api_client.put(f"/api/sessions/{test_session}/workspace", json=plan)
    assert saved.status_code == 200, saved.text

    body = api_client.get(
        f"/api/sessions/{test_session}/data/workspace-projection"
    ).json()
    filtered = next(item for item in body["snapshots"] if item["name"] == "east_orders")
    assert filtered["availability"] == "planned"
    assert filtered["row_count"] is None
    assert filtered["created_by_unit_id"] == 2
    assert "east_orders.revenue" in filtered["column_refs"]
    revenue = next(item for item in body["columns"] if item["ref"] == "east_orders.revenue")
    assert revenue["availability"] == "planned"
    assert revenue["dtype"] is None
    assert revenue["null_count"] is None


def test_projection_exposes_only_declared_planned_join_aliases(api_client, test_session):
    _upload(api_client, test_session, CYCLE5_FIXTURES / "orders.csv")
    _upload(api_client, test_session, CYCLE5_FIXTURES / "customers.csv")
    plan = {
        "units": [
            {
                "unit_id": 1,
                "operation": "join",
                "execution_mode": "template",
                "purpose": "attach customer data",
                "depends_on": [],
                "inputs": [
                    {"role": "left", "snapshot": "orders"},
                    {"role": "right", "snapshot": "customers"},
                ],
                "keys": [
                    {"left": "orders.customer_id", "right": "customers.customer_id"}
                ],
                "select": [
                    {"from": "orders.price", "as": "price"},
                    {"from": "customers.segment", "as": "segment"},
                ],
                "how": "left",
                "output_snapshot": "orders_with_customers",
            }
        ],
        "alignment_notes": "",
    }
    saved = api_client.put(f"/api/sessions/{test_session}/workspace", json=plan)
    assert saved.status_code == 200, saved.text

    body = api_client.get(
        f"/api/sessions/{test_session}/data/workspace-projection"
    ).json()
    joined = next(
        item for item in body["snapshots"] if item["name"] == "orders_with_customers"
    )
    assert joined["availability"] == "planned"
    assert joined["row_count"] is None
    assert joined["column_refs"] == [
        "orders_with_customers.price",
        "orders_with_customers.segment",
    ]
    assert all(
        item["availability"] == "planned"
        and item["null_count"] is None
        and item["null_pct"] is None
        for item in body["columns"]
        if item["snapshot"] == "orders_with_customers"
    )


def test_projection_marks_successful_output_materialized_and_stale_output_planned(
    api_client, test_session, tmp_path
):
    with patch("src.api.routes.data.OUTPUT_DIR", tmp_path):
        _upload(api_client, test_session, CYCLE5_FIXTURES / "orders.csv")
    plan = {"units": [_derive()], "alignment_notes": ""}
    saved = api_client.put(f"/api/sessions/{test_session}/workspace", json=plan)
    assert saved.status_code == 200, saved.text
    store = api_client.app.state.sessions
    state = store.get(test_session)
    assert state is not None
    store.update(
        test_session,
        {
            "analysis_result": {
                "status": "running",
                "output_dir": str(tmp_path / test_session / "analysis"),
                "unit_results": [],
            }
        },
    )
    state = store.get(test_session)
    assert state is not None
    result = analysis_node(state)
    store.update(test_session, result)

    body = api_client.get(
        f"/api/sessions/{test_session}/data/workspace-projection"
    ).json()
    materialized = next(item for item in body["columns"] if item["ref"] == "orders.revenue")
    assert materialized["availability"] == "materialized"
    assert materialized["dtype"] is not None

    current = store.get(test_session)
    assert current is not None
    analysis_result = current.analysis_result or {}
    store.update(
        test_session,
        {
            "analysis_result": {
                **analysis_result,
                "unit_results": [
                    {**item, "stale": True}
                    for item in analysis_result.get("unit_results", [])
                ],
            }
        },
    )
    stale_body = api_client.get(
        f"/api/sessions/{test_session}/data/workspace-projection"
    ).json()
    stale = next(item for item in stale_body["columns"] if item["ref"] == "orders.revenue")
    assert stale["availability"] == "planned"
    assert stale["null_count"] is None
