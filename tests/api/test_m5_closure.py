from pathlib import Path
from unittest.mock import patch

from src.agent.nodes.analysis import analysis_node
from src.agent.state import Plan

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "cycle5"


def _upload(api_client, session_id: str, name: str) -> None:
    path = FIXTURE_DIR / name
    with path.open("rb") as file:
        response = api_client.post(
            f"/api/sessions/{session_id}/data/upload",
            files={"file": (name, file, "text/csv")},
        )
    assert response.status_code == 200, response.text


def test_multi_source_profiles_and_public_lineage(api_client, test_session):
    _upload(api_client, test_session, "orders.csv")
    _upload(api_client, test_session, "customers.csv")

    profiles = api_client.get(f"/api/sessions/{test_session}/data/profile")
    assert profiles.status_code == 200
    body = profiles.json()
    assert [item["snapshot_name"] for item in body["profiles"]] == [
        "orders",
        "customers",
    ]
    assert all("node_id" not in item for item in body["profiles"])

    specific = api_client.get(
        f"/api/sessions/{test_session}/data/profile?snapshot_id=snap_orders"
    )
    assert specific.status_code == 200
    assert specific.json()["snapshot_name"] == "orders"
    assert specific.json()["shape"] == [5, 6]

    columns = api_client.get(f"/api/sessions/{test_session}/data/columns").json()
    assert "orders.customer_id" in columns["unified_columns"]
    assert "customers.segment" in columns["unified_columns"]

    lineage = api_client.get(f"/api/sessions/{test_session}/data/lineage")
    assert lineage.status_code == 200
    lineage_body = lineage.json()
    assert any(item["ref"] == "orders.customer_id" for item in lineage_body["columns"])
    assert all("node_id" not in item for item in lineage_body["columns"])


def test_workspace_accepts_complete_v2_workflow(api_client, test_session):
    _upload(api_client, test_session, "orders.csv")
    _upload(api_client, test_session, "customers.csv")
    plan = {
        "units": [
            {
                "unit_id": 1,
                "operation": "derive_column",
                "execution_mode": "template",
                "purpose": "derive revenue",
                "depends_on": [],
                "input_snapshot": "orders",
                "input_columns": ["orders.price", "orders.quantity"],
                "output_columns": ["orders.revenue"],
                "template_name": "column_arithmetic",
                "template_params": {"operator": "*", "new_column": "revenue"},
            },
            {
                "unit_id": 2,
                "operation": "filter",
                "execution_mode": "template",
                "purpose": "east orders",
                "depends_on": [1],
                "input_snapshot": "orders",
                "input_columns": ["orders.region"],
                "output_snapshot": "east_orders",
                "template_name": "filter_by_date",
                "template_params": {"condition": "region == 'East'"},
            },
            {
                "unit_id": 3,
                "operation": "join",
                "execution_mode": "template",
                "purpose": "attach customer segment",
                "depends_on": [2],
                "inputs": [
                    {"role": "left", "snapshot": "east_orders"},
                    {"role": "right", "snapshot": "customers"},
                ],
                "keys": [
                    {"left": "east_orders.customer_id", "right": "customers.customer_id"}
                ],
                "select": [
                    {"from": "east_orders.order_id", "as": "order_id"},
                    {"from": "east_orders.revenue", "as": "revenue"},
                    {"from": "customers.segment", "as": "segment"},
                ],
                "how": "left",
                "output_snapshot": "east_orders_with_customers",
            },
            {
                "unit_id": 4,
                "operation": "terminal",
                "execution_mode": "template",
                "purpose": "plot revenue by segment",
                "depends_on": [3],
                "input_snapshot": "east_orders_with_customers",
                "input_columns": [
                    "east_orders_with_customers.revenue",
                    "east_orders_with_customers.segment",
                ],
                "template_name": "scatter_plot",
            },
        ],
        "alignment_notes": "Join warnings and unmatched customers must be disclosed.",
    }
    response = api_client.put(
        f"/api/sessions/{test_session}/workspace", json=plan
    )
    assert response.status_code == 200, response.text
    returned = response.json()["plan"]
    assert [unit["operation"] for unit in returned["units"]] == [
        "derive_column",
        "filter",
        "join",
        "terminal",
    ]


def test_workspace_shape_errors_are_structured(api_client, test_session):
    response = api_client.put(
        f"/api/sessions/{test_session}/workspace",
        json={"units": [{"unit_id": 1, "purpose": "missing operation"}]},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_PLAN"
    assert response.json()["detail"]["issues"][0]["code"] == "PLAN_SHAPE_INVALID"


def test_join_execution_exposes_warnings_and_lineage(
    api_client, test_session, tmp_path
):
    with patch("src.api.routes.data.OUTPUT_DIR", tmp_path):
        _upload(api_client, test_session, "orders.csv")
        _upload(api_client, test_session, "customers.csv")
    plan_payload = {
        "units": [
            {
                "unit_id": 1,
                "operation": "join",
                "execution_mode": "template",
                "purpose": "attach customer segment",
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
                    {"from": "orders.quantity", "as": "quantity"},
                    {"from": "customers.segment", "as": "segment"},
                ],
                "how": "left",
                "output_snapshot": "orders_with_customers",
            },
            {
                "unit_id": 2,
                "operation": "terminal",
                "execution_mode": "template",
                "purpose": "plot joined data",
                "depends_on": [1],
                "input_snapshot": "orders_with_customers",
                "input_columns": [
                    "orders_with_customers.price",
                    "orders_with_customers.quantity",
                ],
                "template_name": "scatter_plot",
            },
        ],
        "alignment_notes": "Disclose unmatched customer keys.",
    }
    response = api_client.put(
        f"/api/sessions/{test_session}/workspace", json=plan_payload
    )
    assert response.status_code == 200, response.text

    store = api_client.app.state.sessions
    state = store.get(test_session)
    assert state is not None
    plan = Plan.model_validate(response.json()["plan"])
    analysis_dir = tmp_path / test_session / "analysis"
    store.update(
        test_session,
        {
            "plan": plan,
            "analysis_result": {
                "status": "running",
                "output_dir": str(analysis_dir),
                "unit_results": [],
            },
        },
    )

    with patch("src.api.routes.data.OUTPUT_DIR", tmp_path), patch(
        "src.api.routes.execution.OUTPUT_DIR", tmp_path
    ):
        result = analysis_node(store.get(test_session))
        store.update(test_session, result)
        execution = api_client.get(
            f"/api/sessions/{test_session}/execution/results"
        )
        lineage = api_client.get(f"/api/sessions/{test_session}/data/lineage")

    assert execution.status_code == 200
    units = execution.json()["units"]
    assert [unit["status"] for unit in units] == ["success", "success"]
    assert any(
        warning["code"] == "JOIN_UNMATCHED_KEYS"
        for warning in units[0]["warnings"]
    )
    assert units[0]["row_count_before"] == 5
    assert units[0]["row_count_after"] == 5
    assert any(
        item["ref"] == "orders_with_customers.segment"
        and "customers.segment" in item["derived_from"]
        for item in lineage.json()["columns"]
    )
