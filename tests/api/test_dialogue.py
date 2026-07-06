from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestDialogueRoutes:
    def test_send_message_no_workspace(self, api_client, test_session, sample_analysis_intent):
        with patch(
            "src.api.routes.dialogue.business_track_node",
            return_value={"analysis_intent": sample_analysis_intent, "feedback": None},
        ):
            resp = api_client.post(
                f"/api/sessions/{test_session}/dialogue",
                json={"message": "按地区分析销售趋势"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_contextualized"] is False
        assert body["intent"]["core_question"] == "Why did Q2 sales drop by 15%?"

    def test_send_message_with_workspace(
        self, api_client, test_session, sample_plan, sample_analysis_intent
    ):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(
            test_session,
            {"plan": sample_plan, "unified_columns": ["销量", "地区", "日期"]},
        )

        with patch(
            "src.api.routes.dialogue.business_track_node",
            return_value={"analysis_intent": sample_analysis_intent, "feedback": None},
        ):
            resp = api_client.post(
                f"/api/sessions/{test_session}/dialogue",
                json={"message": "把地区分析拆成华东和华南"},
            )
        assert resp.status_code == 200
        assert resp.json()["is_contextualized"] is True

    def test_send_message_empty(self, api_client, test_session):
        """Empty message should still work (business_track handles it)."""
        resp = api_client.post(
            f"/api/sessions/{test_session}/dialogue",
            json={"message": ""},
        )
        assert resp.status_code in (200, 400, 422)

    def test_send_message_session_not_found(self, api_client):
        resp = api_client.post(
            "/api/sessions/DEADBEEF/dialogue",
            json={"message": "hello"},
        )
        assert resp.status_code == 404

    def test_stream_intent(self, api_client, test_session):
        """SSE stream endpoint returns text/event-stream content type."""
        mock_llm = MagicMock()

        async def _fake_stream(prompt):
            chunks = [
                "{", '"core_question"', ': "分析销售",', '"dimensions":',
                '[],', '"analysis_type":', '"descriptive",', '"suggestions":',
                "[],", '"complexity":', '"simple"}',
            ]
            for c in chunks:
                yield MagicMock(content=c)

        mock_llm.astream = _fake_stream

        with patch("src.api.routes.dialogue.get_llm", return_value=mock_llm):
            resp = api_client.get(
                f"/api/sessions/{test_session}/dialogue/stream",
                params={"message": "分析销售"},
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.text
        assert 'event": "token"' in body
        assert 'event": "done"' in body
