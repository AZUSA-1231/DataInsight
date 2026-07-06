from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestWorkspaceRoutes:
    def test_get_empty_workspace(self, api_client, test_session):
        resp = api_client.get(f"/api/sessions/{test_session}/workspace")
        assert resp.status_code == 200
        assert resp.json()["plan"] is None

    def test_set_workspace(self, api_client, test_session, sample_plan):
        resp = api_client.put(
            f"/api/sessions/{test_session}/workspace",
            json=sample_plan.model_dump(),
        )
        assert resp.status_code == 200
        assert resp.json()["plan"] is not None

    def test_set_workspace_session_not_found(self, api_client, sample_plan):
        resp = api_client.put(
            "/api/sessions/DEADBEEF/workspace",
            json=sample_plan.model_dump(),
        )
        assert resp.status_code == 404

    def test_clear_workspace(self, api_client, test_session, sample_plan):
        api_client.put(
            f"/api/sessions/{test_session}/workspace",
            json=sample_plan.model_dump(),
        )
        resp = api_client.delete(f"/api/sessions/{test_session}/workspace")
        assert resp.status_code == 200

        get_resp = api_client.get(f"/api/sessions/{test_session}/workspace")
        assert get_resp.json()["plan"] is None

    def test_add_unit_to_empty_workspace(self, api_client, test_session):
        resp = api_client.post(
            f"/api/sessions/{test_session}/workspace/units",
            json={
                "purpose": "按地区分析销售额",
                "model": "线性回归",
                "related_fields": ["地区", "销售额"],
            },
        )
        assert resp.status_code == 200
        plan = resp.json()["plan"]
        assert len(plan["units"]) == 1
        assert plan["units"][0]["unit_id"] == 1
        assert plan["units"][0]["purpose"] == "按地区分析销售额"

    def test_add_multiple_units(self, api_client, test_session, sample_plan):
        api_client.put(
            f"/api/sessions/{test_session}/workspace",
            json=sample_plan.model_dump(),
        )
        resp = api_client.post(
            f"/api/sessions/{test_session}/workspace/units",
            json={"purpose": "第二个分析单元", "related_fields": []},
        )
        assert resp.status_code == 200
        plan = resp.json()["plan"]
        assert len(plan["units"]) == 2

    def test_update_unit(self, api_client, test_session, sample_plan):
        api_client.put(
            f"/api/sessions/{test_session}/workspace",
            json=sample_plan.model_dump(),
        )
        resp = api_client.put(
            f"/api/sessions/{test_session}/workspace/units/1",
            json={"purpose": "修正后的分析目的"},
        )
        assert resp.status_code == 200
        unit = resp.json()["plan"]["units"][0]
        assert unit["purpose"] == "修正后的分析目的"
        assert unit["model"] == "线性回归"  # unchanged

    def test_update_unit_not_found(self, api_client, test_session, sample_plan):
        api_client.put(
            f"/api/sessions/{test_session}/workspace",
            json=sample_plan.model_dump(),
        )
        resp = api_client.put(
            f"/api/sessions/{test_session}/workspace/units/99",
            json={"purpose": "不存在的单元"},
        )
        assert resp.status_code == 404

    def test_update_unit_no_workspace(self, api_client, test_session):
        resp = api_client.put(
            f"/api/sessions/{test_session}/workspace/units/1",
            json={"purpose": "无workspace"},
        )
        assert resp.status_code == 400

    def test_delete_unit(self, api_client, test_session, sample_plan_multi):
        api_client.put(
            f"/api/sessions/{test_session}/workspace",
            json=sample_plan_multi.model_dump(),
        )
        resp = api_client.delete(f"/api/sessions/{test_session}/workspace/units/1")
        assert resp.status_code == 200
        plan = resp.json()["plan"]
        assert len(plan["units"]) == 2
        # Unit IDs are re-indexed
        assert plan["units"][0]["unit_id"] == 1
        assert plan["units"][1]["unit_id"] == 2

    def test_delete_last_unit(self, api_client, test_session, sample_plan):
        api_client.put(
            f"/api/sessions/{test_session}/workspace",
            json=sample_plan.model_dump(),
        )
        resp = api_client.delete(f"/api/sessions/{test_session}/workspace/units/1")
        assert resp.status_code == 200
        plan = resp.json()["plan"]
        assert len(plan["units"]) == 0

    def test_generate_plan(self, api_client, test_session, sample_plan):
        """POST /plan/generate calls planner_node and returns result."""
        from src.agent.state import Plan, PlanUnit

        updated_plan = Plan(
            cleaning=PlanUnit(
                unit_id=0,
                purpose="处理缺失值",
                cautious="",
                related_fields=[],
            ),
            units=[
                PlanUnit(
                    unit_id=1,
                    purpose="AI修正后的分析目的",
                    model="线性回归",
                    cautious="数据有异常值",
                    related_fields=["销量", "地区"],
                )
            ],
            alignment_notes="已根据数据特征调整分析计划。",
        )

        api_client.put(
            f"/api/sessions/{test_session}/workspace",
            json=sample_plan.model_dump(),
        )
        with patch(
            "src.api.routes.workspace.planner_node",
            return_value={"plan": updated_plan},
        ):
            resp = api_client.post(f"/api/sessions/{test_session}/plan/generate")
        assert resp.status_code == 200
        plan = resp.json()["plan"]
        assert plan["units"][0]["related_fields"] == ["销量", "地区"]

    def test_generate_plan_no_workspace(self, api_client, test_session):
        """planner_node should handle empty workspace (generate fresh Plan)."""
        from src.agent.state import Plan, PlanUnit

        new_plan = Plan(
            cleaning=PlanUnit(
                unit_id=0,
                purpose="清洗数据",
                cautious="",
                related_fields=[],
            ),
            units=[
                PlanUnit(
                    unit_id=1,
                    purpose="AI生成的趋势分析",
                    model="linear",
                    cautious="检查季节性",
                    related_fields=["销量", "日期"],
                )
            ],
            alignment_notes="基于业务意图生成的分析计划。",
        )
        with patch(
            "src.api.routes.workspace.planner_node",
            return_value={"plan": new_plan},
        ):
            resp = api_client.post(f"/api/sessions/{test_session}/plan/generate")
        assert resp.status_code == 200
        assert len(resp.json()["plan"]["units"]) == 1
