from __future__ import annotations

from unittest.mock import patch

import pytest

from src.agent.state import PlannerInstruction


@pytest.mark.unit
class TestDialogueRoutes:
    def test_send_message_chat_action(self, api_client, test_session):
        """BT responds conversationally → action=chat, no instruction."""
        with patch(
            "src.api.routes.dialogue.business_track_node",
            return_value=(
                {"feedback": None},
                {"_bt_response": "您想从哪个维度分析销售数据？", "_bt_tool_called": False},
            ),
        ):
            resp = api_client.post(
                f"/api/sessions/{test_session}/dialogue",
                json={"message": "分析销售数据"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "chat"
        assert "哪个维度" in body["message"]
        assert body["instruction"] is None

    def test_send_message_confirm_action(self, api_client, test_session):
        """BT calls submit_planner_instruction → action=confirm, instruction present."""
        instr = PlannerInstruction(
            core_question="按地区分析销售趋势",
            analysis_type="descriptive",
            complexity="moderate",
            target_columns=["sales"],
            group_by=["region"],
            instruction_nl="用户需要按地区分析销售趋势。",
        )
        with patch(
            "src.api.routes.dialogue.business_track_node",
            return_value=(
                {"planner_instruction": instr, "analysis_intent": None, "feedback": None},
                {"_bt_response": "好的，我提交分析指令给Planner。", "_bt_tool_called": True},
            ),
        ):
            resp = api_client.post(
                f"/api/sessions/{test_session}/dialogue",
                json={"message": "按地区分析销售趋势"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "confirm"
        assert body["instruction"] is not None
        assert body["instruction"]["core_question"] == "按地区分析销售趋势"

    def test_send_message_with_workspace(
        self, api_client, test_session, sample_plan
    ):
        """BT with workspace → is_contextualized=True."""
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(
            test_session,
            {"plan": sample_plan, "unified_columns": ["销量", "地区", "日期"]},
        )

        with patch(
            "src.api.routes.dialogue.business_track_node",
            return_value=(
                {
                    "planner_instruction": PlannerInstruction(
                        core_question="修改地区分析",
                        analysis_type="comparative",
                        instruction_nl="用户要修改第1个分析单元。",
                    ),
                    "analysis_intent": None,
                    "feedback": None,
                },
                {"_bt_response": "我理解了，需要修改第1个单元。", "_bt_tool_called": True},
            ),
        ):
            resp = api_client.post(
                f"/api/sessions/{test_session}/dialogue",
                json={"message": "把地区分析拆成华东和华南"},
            )
        assert resp.status_code == 200
        assert resp.json()["is_contextualized"] is True

    def test_send_message_session_not_found(self, api_client):
        resp = api_client.post(
            "/api/sessions/DEADBEEF/dialogue",
            json={"message": "hello"},
        )
        assert resp.status_code == 404

    def test_stream_intent_chat_action(self, api_client, test_session):
        """SSE stream with conversational response → action=chat, no tool_call event."""
        with patch(
            "src.api.routes.dialogue.business_track_node",
            return_value=(
                {"planner_instruction": None, "analysis_intent": None, "feedback": None},
                {"_bt_response": "好的，我来帮您分析。", "_bt_tool_called": False},
            ),
        ):
            resp = api_client.get(
                f"/api/sessions/{test_session}/dialogue/stream",
                params={"message": "分析销售"},
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.text
        assert "event: status" in body
        assert "event: token" in body
        assert "event: done" in body
        assert '"action":"chat"' in body or '"action": "chat"' in body
        # No tool_call since BT didn't call a tool
        assert "event: tool_call" not in body

    def test_stream_intent_tool_call_event(self, api_client, test_session):
        """SSE stream with tool call → tool_call event + action=confirm."""
        instr = PlannerInstruction(
            core_question="分析销售数据",
            analysis_type="descriptive",
            complexity="simple",
            instruction_nl="用户需要基本的销售数据分析。",
        )
        with patch(
            "src.api.routes.dialogue.business_track_node",
            return_value=(
                {"planner_instruction": instr, "analysis_intent": None, "feedback": None},
                {"_bt_response": "好的，我已提交分析指令。", "_bt_tool_called": True},
            ),
        ):
            resp = api_client.get(
                f"/api/sessions/{test_session}/dialogue/stream",
                params={"message": "分析销售"},
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.text
        assert "event: status" in body
        assert "event: token" in body
        assert "event: tool_call" in body
        assert "submit_planner_instruction" in body
        assert "event: done" in body
        assert '"action":"confirm"' in body or '"action": "confirm"' in body
