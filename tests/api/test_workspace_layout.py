from __future__ import annotations


def _layout(*nodes: dict[str, object], zoom: float = 1.0) -> dict[str, object]:
    return {
        "version": 1,
        "viewport": {"x": 12, "y": -8, "zoom": zoom},
        "nodes": list(nodes),
    }


def test_layout_defaults_to_empty_and_round_trips(api_client, test_session, sample_plan):
    empty = api_client.get(f"/api/sessions/{test_session}/workspace/layout")
    assert empty.status_code == 200
    assert empty.json() == {
        "version": 1,
        "viewport": {"x": 0.0, "y": 0.0, "zoom": 1.0},
        "nodes": [],
    }

    set_plan = api_client.put(
        f"/api/sessions/{test_session}/workspace", json=sample_plan.model_dump()
    )
    assert set_plan.status_code == 200
    saved = api_client.put(
        f"/api/sessions/{test_session}/workspace/layout",
        json=_layout({"unit_id": 1, "x": 320, "y": 180, "collapsed": True}),
    )
    assert saved.status_code == 200
    assert saved.json()["nodes"] == [
        {"unit_id": 1, "x": 320.0, "y": 180.0, "collapsed": True}
    ]

    store = api_client.app.state.sessions
    store._sessions.pop(test_session, None)
    reloaded = api_client.get(f"/api/sessions/{test_session}/workspace/layout")
    assert reloaded.status_code == 200
    assert reloaded.json()["nodes"][0]["unit_id"] == 1


def test_layout_rejects_duplicate_units(api_client, test_session, sample_plan):
    api_client.put(
        f"/api/sessions/{test_session}/workspace", json=sample_plan.model_dump()
    )
    response = api_client.put(
        f"/api/sessions/{test_session}/workspace/layout",
        json=_layout(
            {"unit_id": 1, "x": 0, "y": 0},
            {"unit_id": 1, "x": 100, "y": 0},
        ),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "DUPLICATE_LAYOUT_UNIT"


def test_layout_rejects_unknown_units(api_client, test_session, sample_plan):
    api_client.put(
        f"/api/sessions/{test_session}/workspace", json=sample_plan.model_dump()
    )
    response = api_client.put(
        f"/api/sessions/{test_session}/workspace/layout",
        json=_layout({"unit_id": 99, "x": 0, "y": 0}),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "UNKNOWN_LAYOUT_UNIT"


def test_layout_rejects_invalid_viewport_and_coordinates(api_client, test_session):
    invalid_zoom = api_client.put(
        f"/api/sessions/{test_session}/workspace/layout",
        json=_layout(zoom=5),
    )
    assert invalid_zoom.status_code == 422
    assert invalid_zoom.json()["detail"]["code"] == "INVALID_WORKSPACE_LAYOUT"

    invalid_coordinate = api_client.put(
        f"/api/sessions/{test_session}/workspace/layout",
        json=_layout({"unit_id": 1, "x": 1_000_001, "y": 0}),
    )
    assert invalid_coordinate.status_code == 422
    assert invalid_coordinate.json()["detail"]["code"] == "LAYOUT_COORDINATE_OUT_OF_RANGE"
