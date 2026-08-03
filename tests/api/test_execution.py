from __future__ import annotations

from unittest.mock import patch

from src.agent.state import Plan


def _terminal_plan() -> Plan:
    return Plan.model_validate(
        {
            "units": [
                {
                    "unit_id": 1,
                    "operation": "terminal",
                    "execution_mode": "template",
                    "purpose": "inspect orders",
                    "input_snapshot": "orders",
                    "input_columns": ["orders.amount"],
                }
            ],
            "alignment_notes": "",
        }
    )


class TestExecutionRoutes:
    def test_run_execution_accepts_plan(self, api_client, test_session):
        store = api_client.app.state.sessions
        store.update(test_session, {"plan": _terminal_plan()})
        response = api_client.post(
            f"/api/sessions/{test_session}/execution/run"
        )
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"

    def test_run_execution_no_plan(self, api_client, test_session):
        response = api_client.post(
            f"/api/sessions/{test_session}/execution/run"
        )
        assert response.status_code == 400

    def test_run_execution_already_running(self, api_client, test_session):
        store = api_client.app.state.sessions
        store.update(
            test_session,
            {"plan": _terminal_plan(), "analysis_result": {"status": "running"}},
        )
        response = api_client.post(
            f"/api/sessions/{test_session}/execution/run"
        )
        assert response.status_code == 409

    def test_get_status_and_results(self, api_client, test_session):
        store = api_client.app.state.sessions
        store.update(
            test_session,
            {
                "analysis_result": {
                    "status": "complete",
                    "unit_results": [
                        {
                            "unit_id": 1,
                            "status": "success",
                            "stdout": "",
                            "stderr": "",
                            "charts": [],
                            "insights": [],
                            "run_id": "run_test",
                            "input_checkpoint_ids": ["cp_source_orders"],
                        }
                    ],
                }
            },
        )
        status = api_client.get(
            f"/api/sessions/{test_session}/execution/status"
        )
        results = api_client.get(
            f"/api/sessions/{test_session}/execution/results"
        )
        assert status.json()["status"] == "completed"
        assert results.json()["units"][0]["input_checkpoint_ids"] == [
            "cp_source_orders"
        ]

    def test_rerun_route_returns_checkpoint_metadata(
        self, api_client, test_session
    ):
        store = api_client.app.state.sessions
        plan = _terminal_plan()
        store.update(test_session, {"plan": plan})
        state = store.get(test_session)
        assert state is not None
        patch_result = {
            "analysis_result": {
                "status": "complete",
                "run_id": "run_new",
                "unit_results": [
                    {
                        "unit_id": 1,
                        "status": "success",
                        "charts": [],
                        "insights": [],
                        "input_checkpoint_ids": ["cp_source_orders"],
                    }
                ],
            },
            "snapshot_registry": state.snapshot_registry,
            "checkpoint_registry": state.checkpoint_registry,
            "column_graph": state.column_graph,
            "stale_unit_ids": [],
            "rerun_result": {
                "unit_id": 1,
                "status": "success",
                "charts": [],
                "insights": [],
                "input_checkpoint_ids": ["cp_source_orders"],
                "output_checkpoint_id": "cp_run_new_u1",
            },
        }
        with patch(
            "src.api.routes.execution.rerun_dag", return_value=patch_result
        ) as rerun:
            response = api_client.post(
                f"/api/sessions/{test_session}/execution/units/1/rerun"
            )
        assert response.status_code == 200
        assert response.json()["output_checkpoint_id"] == "cp_run_new_u1"
        rerun.assert_called_once()

    def test_rerun_missing_session(self, api_client):
        response = api_client.post(
            "/api/sessions/00000000000000000000000000000000/"
            "execution/units/1/rerun"
        )
        assert response.status_code == 404

    def test_serve_chart_path_traversal_blocked(self, api_client, test_session):
        response = api_client.get(
            f"/api/sessions/{test_session}/execution/charts/..%2F..%2Fetc%2Fpasswd"
        )
        assert response.status_code in (403, 404)

    def test_serve_nested_session_chart(self, api_client, test_session, tmp_path):
        chart = tmp_path / test_session / "analysis" / "unit_4" / "scatter.png"
        chart.parent.mkdir(parents=True)
        chart.write_bytes(b"fake-png")
        with patch("src.api.routes.execution.OUTPUT_DIR", tmp_path):
            response = api_client.get(
                f"/api/sessions/{test_session}/execution/charts/"
                "analysis/unit_4/scatter.png"
            )
        assert response.status_code == 200
        assert response.content == b"fake-png"
