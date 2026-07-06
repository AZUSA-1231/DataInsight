from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestReportRoutes:
    def test_generate_report(self, api_client, test_session, sample_plan, sample_analysis_result):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(
            test_session,
            {"plan": sample_plan, "analysis_result": sample_analysis_result},
        )

        with patch(
            "src.api.routes.report.report_gen_node",
            return_value={"final_report": "# Analysis Report\n\nTest report content."},
        ):
            resp = api_client.post(f"/api/sessions/{test_session}/report/generate")
        assert resp.status_code == 200
        body = resp.json()
        assert "# Analysis Report" in body["report"]
        assert body["error"] is None

    def test_generate_report_no_data(self, api_client, test_session):
        with patch(
            "src.api.routes.report.report_gen_node",
            return_value={"final_report": "# Partial Report\n\nIncomplete data."},
        ):
            resp = api_client.post(f"/api/sessions/{test_session}/report/generate")
        assert resp.status_code == 200

    def test_get_report_empty(self, api_client, test_session):
        resp = api_client.get(f"/api/sessions/{test_session}/report")
        assert resp.status_code == 200
        assert resp.json()["report"] is None

    def test_get_report_with_content(self, api_client, test_session):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(test_session, {"final_report": "# Cached Report"})

        resp = api_client.get(f"/api/sessions/{test_session}/report")
        assert resp.status_code == 200
        assert resp.json()["report"] == "# Cached Report"

    def test_session_not_found(self, api_client):
        resp = api_client.post("/api/sessions/DEADBEEF/report/generate")
        assert resp.status_code == 404
