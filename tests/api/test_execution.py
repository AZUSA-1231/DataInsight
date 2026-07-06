from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestExecutionRoutes:
    def test_run_execution(self, api_client, test_session, sample_plan):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(test_session, {"plan": sample_plan})

        mock_preprocess = {"preprocessing_result": {"status": "complete"}}
        with patch(
            "src.api.routes.execution.preprocessing_node", return_value=mock_preprocess
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
            {"plan": sample_plan, "preprocessing_result": {"status": "running"}},
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
            {"preprocessing_result": {"status": "running"}},
        )
        resp = api_client.get(f"/api/sessions/{test_session}/execution/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        assert resp.json()["progress"] == "preprocessing"

    def test_get_status_completed(self, api_client, test_session, sample_analysis_result):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(
            test_session,
            {
                "preprocessing_result": {"status": "complete"},
                "analysis_result": sample_analysis_result,
            },
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
                "preprocessing_result": {"status": "failed", "error": "Script timeout"},
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
            {
                "preprocessing_result": {"status": "complete"},
                "analysis_result": sample_analysis_result,
            },
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
