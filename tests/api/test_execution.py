from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestExecutionRoutes:
    def test_run_execution(self, api_client, test_session, sample_plan):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(test_session, {"plan": sample_plan})

        mock_analysis = {"analysis_result": {"status": "complete"}}
        with patch(
            "src.api.routes.execution.analysis_node", return_value=mock_analysis
        ):
            resp = api_client.post(f"/api/sessions/{test_session}/execution/run")
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    def test_run_execution_no_plan(self, api_client, test_session):
        resp = api_client.post(f"/api/sessions/{test_session}/execution/run")
        assert resp.status_code == 400

    def test_run_execution_already_running(self, api_client, test_session, sample_plan):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(
            test_session,
            {"plan": sample_plan, "analysis_result": {"status": "running"}},
        )
        resp = api_client.post(f"/api/sessions/{test_session}/execution/run")
        assert resp.status_code == 409

    def test_get_status_idle(self, api_client, test_session):
        resp = api_client.get(f"/api/sessions/{test_session}/execution/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "idle"

    def test_get_status_running(self, api_client, test_session):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(
            test_session,
            {"analysis_result": {"status": "running"}},
        )
        resp = api_client.get(f"/api/sessions/{test_session}/execution/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        assert resp.json()["progress"] == "analysis"

    def test_get_status_completed(self, api_client, test_session, sample_analysis_result):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(
            test_session,
            {"analysis_result": sample_analysis_result},
        )
        resp = api_client.get(f"/api/sessions/{test_session}/execution/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_get_status_failed(self, api_client, test_session):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(
            test_session,
            {
                "analysis_result": {"status": "failed", "error": "Script timeout"},
                "error": "Script timeout",
            },
        )
        resp = api_client.get(f"/api/sessions/{test_session}/execution/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        assert "Script timeout" in resp.json()["error"]

    def test_get_results(self, api_client, test_session, sample_analysis_result):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(
            test_session,
            {"analysis_result": sample_analysis_result},
        )
        resp = api_client.get(f"/api/sessions/{test_session}/execution/results")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["units"]) == 1
        assert body["units"][0]["unit_id"] == 1
        assert body["units"][0]["status"] == "success"

    def test_serve_chart_path_traversal_blocked(self, api_client, test_session):
        """Starlette normalizes .. before routing — request won't reach handler."""
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(
            test_session,
            {"analysis_result": {"output_dir": "/tmp/test"}},
        )
        # Starlette normalizes the URL, so 404 (route mismatch) is expected
        resp = api_client.get(
            f"/api/sessions/{test_session}/execution/charts/..%2F..%2Fetc%2Fpasswd"
        )
        assert resp.status_code in (403, 404)

    def test_serve_chart_not_found(self, api_client, test_session):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(
            test_session,
            {"analysis_result": {"output_dir": "/tmp/nonexistent_dir_12345"}},
        )
        resp = api_client.get(
            f"/api/sessions/{test_session}/execution/charts/missing.png"
        )
        assert resp.status_code == 404

    def test_serve_nested_session_chart(
        self, api_client, test_session, tmp_path
    ):
        chart = tmp_path / test_session / "analysis" / "unit_4" / "scatter.png"
        chart.parent.mkdir(parents=True)
        chart.write_bytes(b"fake-png")

        with patch("src.api.routes.execution.OUTPUT_DIR", tmp_path):
            resp = api_client.get(
                f"/api/sessions/{test_session}/execution/charts/"
                "analysis/unit_4/scatter.png"
            )

        assert resp.status_code == 200
        assert resp.content == b"fake-png"

    # --- M4: unit rerun ---

    def test_rerun_unit_success(self, api_client, test_session, sample_plan):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(
            test_session,
            {
                "plan": sample_plan,
                "analysis_result": {
                    "status": "complete",
                    "output_dir": "/tmp/rerun_test",
                    "unit_results": [
                        {"unit_id": 1, "status": "success", "charts": [],
                         "insights": [], "stdout": "", "stderr": "", "error": None},
                    ],
                },
            },
        )

        mock_result = {
            "unit_id": 1,
            "status": "success",
            "parsed_output": {"charts": [], "statistics": {}, "insights": ["rerun ok"]},
            "charts": [],
            "insights": ["rerun ok"],
            "statistics": {},
            "error": None,
            "retry_count": 0,
            "scripts": [],
            "stdout": "",
            "output_dir": "/tmp/rerun_test/unit_1",
        }

        with patch(
            "src.api.routes.execution._execute_unit", return_value=mock_result
        ):
            resp = api_client.post(
                f"/api/sessions/{test_session}/execution/units/1/rerun"
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["unit_id"] == 1
        assert body["status"] == "success"

    def test_rerun_unit_not_found(self, api_client, test_session, sample_plan):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(test_session, {"plan": sample_plan})

        resp = api_client.post(
            f"/api/sessions/{test_session}/execution/units/99/rerun"
        )
        assert resp.status_code == 404

    def test_rerun_unit_no_plan(self, api_client, test_session):
        resp = api_client.post(
            f"/api/sessions/{test_session}/execution/units/1/rerun"
        )
        assert resp.status_code == 400

    def test_rerun_unit_session_not_found(self, api_client):
        resp = api_client.post(
            "/api/sessions/DEADBEEF/execution/units/1/rerun"
        )
        assert resp.status_code == 404

    def test_rerun_unit_marks_stale(self, api_client, test_session, sample_plan_multi):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(
            test_session,
            {
                "plan": sample_plan_multi,
                "analysis_result": {
                    "status": "complete",
                    "output_dir": "/tmp/rerun_test",
                    "unit_results": [
                        {"unit_id": 1, "status": "success", "charts": [],
                         "insights": [], "stdout": "", "stderr": "", "error": None},
                        {"unit_id": 2, "status": "success", "charts": [],
                         "insights": [], "stdout": "", "stderr": "", "error": None},
                        {"unit_id": 3, "status": "success", "charts": [],
                         "insights": [], "stdout": "", "stderr": "", "error": None},
                    ],
                },
            },
        )

        mock_result = {
            "unit_id": 1,
            "status": "success",
            "parsed_output": {},
            "charts": [],
            "insights": [],
            "statistics": {},
            "error": None,
            "retry_count": 0,
            "scripts": [],
            "stdout": "",
            "output_dir": "/tmp/rerun_test/unit_1",
        }

        # sample_plan_multi has 3 independent units (no depends_on)
        # So rerunning unit 1 should have no stale dependents
        with patch(
            "src.api.routes.execution._execute_unit", return_value=mock_result
        ):
            resp = api_client.post(
                f"/api/sessions/{test_session}/execution/units/1/rerun"
            )
        assert resp.status_code == 200
        body = resp.json()
        # stale_units should be empty since units are independent
        assert body["stale_units"] == []
