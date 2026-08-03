from __future__ import annotations

import pytest


def _terminal(unit_id: int, name: str) -> dict[str, object]:
    return {
        "unit_id": unit_id,
        "operation": "terminal",
        "execution_mode": "template",
        "purpose": name,
        "cautious": "",
        "depends_on": [],
        "input_snapshot": "test",
        "input_columns": ["test.name"],
    }


@pytest.mark.unit
def test_v2_workspace_rejects_unknown_column(api_client, test_session, sample_csv_path):
    with open(sample_csv_path, "rb") as file:
        upload = api_client.post(
            f"/api/sessions/{test_session}/data/upload",
            files={"file": ("test.csv", file, "text/csv")},
        )
    assert upload.status_code == 200

    response = api_client.put(
        f"/api/sessions/{test_session}/workspace",
        json={
            "units": [
                {
                    **_terminal(1, "inspect"),
                    "input_columns": ["test.missing"],
                }
            ],
            "alignment_notes": "",
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "INVALID_PLAN"
    assert any(issue["code"] == "MISSING_COLUMN" for issue in detail["issues"])


@pytest.mark.unit
def test_v2_delete_keeps_remaining_unit_ids(api_client, test_session, sample_csv_path):
    with open(sample_csv_path, "rb") as file:
        upload = api_client.post(
            f"/api/sessions/{test_session}/data/upload",
            files={"file": ("test.csv", file, "text/csv")},
        )
    assert upload.status_code == 200

    response = api_client.put(
        f"/api/sessions/{test_session}/workspace",
        json={
            "units": [_terminal(1, "one"), _terminal(2, "two"), _terminal(3, "three")],
            "alignment_notes": "",
        },
    )
    assert response.status_code == 200

    response = api_client.delete(
        f"/api/sessions/{test_session}/workspace/units/2"
    )
    assert response.status_code == 200
    assert [unit["unit_id"] for unit in response.json()["plan"]["units"]] == [1, 3]


@pytest.mark.unit
def test_edit_marks_unit_and_downstream_results_stale(
    api_client, test_session, sample_csv_path
):
    with open(sample_csv_path, "rb") as file:
        upload = api_client.post(
            f"/api/sessions/{test_session}/data/upload",
            files={"file": ("test.csv", file, "text/csv")},
        )
    assert upload.status_code == 200

    plan = {
        "units": [
            {
                "unit_id": 1,
                "operation": "derive_column",
                "execution_mode": "template",
                "purpose": "derive",
                "cautious": "",
                "depends_on": [],
                "input_snapshot": "test",
                "input_columns": ["test.age"],
                "output_columns": ["test.double_age"],
            },
            {
                "unit_id": 2,
                "operation": "terminal",
                "execution_mode": "template",
                "purpose": "report",
                "cautious": "",
                "depends_on": [1],
                "input_snapshot": "test",
                "input_columns": ["test.double_age"],
            },
        ],
        "alignment_notes": "",
    }
    response = api_client.put(
        f"/api/sessions/{test_session}/workspace", json=plan
    )
    assert response.status_code == 200

    store = api_client.app.state.sessions
    store.update(
        test_session,
        {
            "analysis_result": {
                "status": "complete",
                "unit_results": [
                    {"unit_id": 1, "status": "success", "stale": False},
                    {"unit_id": 2, "status": "success", "stale": False},
                    {"unit_id": 99, "status": "success", "stale": True},
                ],
            }
        },
    )

    response = api_client.put(
        f"/api/sessions/{test_session}/workspace/units/1",
        json={"purpose": "revised derive"},
    )
    assert response.status_code == 200
    state = store.get(test_session)
    assert state is not None
    assert [result["stale"] for result in state.analysis_result["unit_results"]] == [
        True,
        True,
        True,
    ]


@pytest.mark.unit
def test_replacing_workspace_marks_retained_results_stale(
    api_client, test_session, sample_csv_path
):
    with open(sample_csv_path, "rb") as file:
        upload = api_client.post(
            f"/api/sessions/{test_session}/data/upload",
            files={"file": ("test.csv", file, "text/csv")},
        )
    assert upload.status_code == 200

    plan = {"units": [_terminal(1, "one")], "alignment_notes": ""}
    response = api_client.put(f"/api/sessions/{test_session}/workspace", json=plan)
    assert response.status_code == 200

    store = api_client.app.state.sessions
    store.update(
        test_session,
        {
            "analysis_result": {
                "status": "complete",
                "unit_results": [{"unit_id": 1, "status": "success", "stale": False}],
            }
        },
    )

    replacement = {
        "units": [_terminal(1, "replacement")],
        "alignment_notes": "changed",
    }
    response = api_client.put(
        f"/api/sessions/{test_session}/workspace", json=replacement
    )
    assert response.status_code == 200
    state = store.get(test_session)
    assert state is not None
    assert state.analysis_result["unit_results"][0]["stale"] is True
