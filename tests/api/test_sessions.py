from __future__ import annotations

import pytest


@pytest.mark.unit
class TestSessionRoutes:
    def test_create_session(self, api_client):
        resp = api_client.post("/api/sessions", json={"user_requirement": "分析销售数据"})
        assert resp.status_code == 200
        body = resp.json()
        assert "session_id" in body
        assert len(body["session_id"]) == 32  # UUID hex

    def test_create_session_default(self, api_client):
        resp = api_client.post("/api/sessions", json={})
        assert resp.status_code == 200
        assert "session_id" in resp.json()

    def test_get_session(self, api_client, test_session):
        resp = api_client.get(f"/api/sessions/{test_session}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == test_session
        assert body["has_data"] is False
        assert body["has_intent"] is False
        assert body["has_plan"] is False
        assert body["has_results"] is False
        assert body["has_report"] is False
        assert body["error"] is None

    def test_get_session_not_found(self, api_client):
        resp = api_client.get("/api/sessions/DEADBEEF")
        assert resp.status_code == 404

    def test_delete_session(self, api_client, test_session):
        resp = api_client.delete(f"/api/sessions/{test_session}")
        assert resp.status_code == 200
        # Verify it's gone
        get_resp = api_client.get(f"/api/sessions/{test_session}")
        assert get_resp.status_code == 404

    def test_delete_session_not_found(self, api_client):
        resp = api_client.delete("/api/sessions/DEADBEEF")
        assert resp.status_code == 404
