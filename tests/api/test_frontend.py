from __future__ import annotations


def test_built_frontend_is_served_at_root_and_project_urls(api_client, test_session) -> None:
    root = api_client.get("/")
    assert root.status_code == 200
    assert "DataInsight" in root.text
    assert "static/app.js" not in root.text

    project = api_client.get(f"/projects/{test_session}")
    assert project.status_code == 200
    assert "DataInsight" in project.text

    api = api_client.get("/api/sessions")
    assert api.status_code == 200
    assert "projects" in api.json()
