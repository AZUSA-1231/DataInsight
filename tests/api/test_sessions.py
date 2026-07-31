from __future__ import annotations

import json

import pandas as pd
import pytest

from src.api.session import SessionStore


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
        assert body["persisted_at"] is not None

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


@pytest.mark.unit
def test_session_persist_roundtrip(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session_id = store.create("分析销售数据")
    store.update(
        session_id,
        {
            "analysis_result": {
                "status": "complete",
                "unit_results": [
                    {
                        "unit_id": 1,
                        "status": "success",
                        "source_code": "def _unit(...): ...",
                        "model_used": "test-model",
                        "_result_df": pd.DataFrame({"value": [1, 2]}),
                    }
                ],
            },
            "final_report": "# Persisted report",
        },
    )

    restored = SessionStore(tmp_path / "sessions").get(session_id)

    assert restored is not None
    assert restored.user_requirement == "分析销售数据"
    assert restored.final_report == "# Persisted report"
    assert restored.analysis_result is not None
    result = restored.analysis_result["unit_results"][0]
    assert result["source_code"] == "def _unit(...): ..."
    assert "_result_df" not in result
    assert restored.persisted_at is not None


@pytest.mark.unit
def test_session_state_file_is_valid_json(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session_id = store.create()

    state_path = tmp_path / "sessions" / session_id / "state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert payload["file_path"] == ""
    assert payload["persisted_at"] is not None
