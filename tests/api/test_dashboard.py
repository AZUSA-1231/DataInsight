from __future__ import annotations

import pytest


@pytest.mark.unit
class TestDashboardRoutes:
    def test_get_empty_dashboard(self, api_client, test_session):
        resp = api_client.get(f"/api/sessions/{test_session}/dashboard")
        assert resp.status_code == 200
        assert resp.json()["pins"] == []

    def test_pin_chart(self, api_client, test_session):
        resp = api_client.post(
            f"/api/sessions/{test_session}/dashboard/pins",
            json={"unit_id": 1, "chart_path": "out/sales_trend.png", "label": "Sales Trend"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["unit_id"] == 1
        assert body["chart_path"] == "out/sales_trend.png"
        assert body["label"] == "Sales Trend"
        assert "pin_id" in body
        assert "pinned_at" in body

    def test_pin_multiple_and_list(self, api_client, test_session):
        api_client.post(
            f"/api/sessions/{test_session}/dashboard/pins",
            json={"unit_id": 1, "chart_path": "out/chart1.png", "label": "Chart 1"},
        )
        api_client.post(
            f"/api/sessions/{test_session}/dashboard/pins",
            json={"unit_id": 2, "chart_path": "out/chart2.png", "label": "Chart 2"},
        )

        resp = api_client.get(f"/api/sessions/{test_session}/dashboard")
        assert resp.status_code == 200
        pins = resp.json()["pins"]
        assert len(pins) == 2

    def test_unpin_chart(self, api_client, test_session):
        pin_resp = api_client.post(
            f"/api/sessions/{test_session}/dashboard/pins",
            json={"unit_id": 1, "chart_path": "out/chart1.png", "label": "Remove Me"},
        )
        pin_id = pin_resp.json()["pin_id"]

        delete_resp = api_client.delete(f"/api/sessions/{test_session}/dashboard/pins/{pin_id}")
        assert delete_resp.status_code == 200

        get_resp = api_client.get(f"/api/sessions/{test_session}/dashboard")
        assert len(get_resp.json()["pins"]) == 0

    def test_unpin_not_found(self, api_client, test_session):
        resp = api_client.delete(f"/api/sessions/{test_session}/dashboard/pins/no-such-pin")
        assert resp.status_code == 404

    def test_pin_session_not_found(self, api_client):
        resp = api_client.post(
            "/api/sessions/DEADBEEF/dashboard/pins",
            json={"unit_id": 1, "chart_path": "out/x.png", "label": "X"},
        )
        assert resp.status_code == 404
