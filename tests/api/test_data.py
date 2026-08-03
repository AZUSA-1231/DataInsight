from __future__ import annotations

import pytest


@pytest.mark.unit
class TestDataPoolRoutes:
    def test_upload_csv(self, api_client, test_session, sample_csv_path):
        with open(sample_csv_path, "rb") as f:
            resp = api_client.post(
                f"/api/sessions/{test_session}/data/upload",
                files={"file": ("test.csv", f, "text/csv")},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["file_name"] == "test.csv"
        assert body["row_count"] == 5
        assert body["col_count"] == 5
        assert body["snapshot_name"] == "test"
        assert body["checkpoint_id"] == "cp_source_test"
        assert body["unified_columns"] == [
            "test.name",
            "test.age",
            "test.salary",
            "test.dept",
            "test.hire_date",
        ]
        assert len(body["columns"]) == 5

        store = api_client.app.state.sessions
        state = store.get(test_session)
        assert state is not None
        assert len(state.data_sources) == 1
        assert len(state.snapshot_registry) == 1
        assert len(state.checkpoint_registry) == 1
        assert "__di_row_id" not in state.snapshot_registry["snap_test"].name

    def test_upload_invalid_extension(self, api_client, test_session):
        fake_content = b"not,xlsx,content"
        resp = api_client.post(
            f"/api/sessions/{test_session}/data/upload",
            files={"file": ("data.json", fake_content, "application/json")},
        )
        assert resp.status_code == 422

    def test_upload_no_filename(self, api_client, test_session):
        resp = api_client.post(
            f"/api/sessions/{test_session}/data/upload",
            files={"file": ("", b"")},
        )
        assert resp.status_code == 422

    def test_upload_session_not_found(self, api_client, sample_csv_path):
        with open(sample_csv_path, "rb") as f:
            resp = api_client.post(
                "/api/sessions/DEADBEEF/data/upload",
                files={"file": ("test.csv", f, "text/csv")},
            )
        assert resp.status_code == 404

    def test_get_profile(self, api_client, test_session, sample_data_profile):
        store = api_client.app.state.sessions
        store.update(test_session, {"data_profile": sample_data_profile})

        resp = api_client.get(f"/api/sessions/{test_session}/data/profile")
        assert resp.status_code == 200
        assert resp.json()["shape"] == [100, 5]

    def test_get_profile_no_data(self, api_client, test_session):
        resp = api_client.get(f"/api/sessions/{test_session}/data/profile")
        assert resp.status_code == 404

    def test_get_columns_compatibility_projection(self, api_client, test_session):
        store = api_client.app.state.sessions
        store.update(test_session, {"unified_columns": ["sales", "region", "date"]})

        resp = api_client.get(f"/api/sessions/{test_session}/data/columns")
        assert resp.status_code == 200
        assert resp.json()["unified_columns"] == ["sales", "region", "date"]

    def test_upload_appends_sources(self, api_client, test_session, sample_csv_path):
        with open(sample_csv_path, "rb") as f:
            resp1 = api_client.post(
                f"/api/sessions/{test_session}/data/upload",
                files={"file": ("test.csv", f, "text/csv")},
            )
        with open(sample_csv_path, "rb") as f:
            resp2 = api_client.post(
                f"/api/sessions/{test_session}/data/upload",
                files={"file": ("test.csv", f, "text/csv")},
            )

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["snapshot_name"] == "test"
        assert resp2.json()["snapshot_name"] == "test_2"

        sources = api_client.get(f"/api/sessions/{test_session}/data/sources")
        assert sources.status_code == 200
        assert [item["snapshot_name"] for item in sources.json()["sources"]] == [
            "test",
            "test_2",
        ]

        snapshots = api_client.get(f"/api/sessions/{test_session}/data/snapshots")
        assert snapshots.status_code == 200
        assert len(snapshots.json()["snapshots"]) == 2

    def test_old_session_schema_is_explicitly_rejected(
        self, api_client, test_session
    ):
        store = api_client.app.state.sessions
        state_path = store._base_dir / test_session / "state.json"
        state_path.write_text(
            '{"file_path":"old.csv","user_requirement":"legacy"}',
            encoding="utf-8",
        )
        store._sessions.pop(test_session, None)

        resp = api_client.get(f"/api/sessions/{test_session}")
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "INCOMPATIBLE_SESSION_SCHEMA"

        for path in (
            f"/api/sessions/{test_session}/data/sources",
            f"/api/sessions/{test_session}/workspace",
            f"/api/sessions/{test_session}/execution/status",
            f"/api/sessions/{test_session}/report",
            f"/api/sessions/{test_session}/dashboard",
        ):
            response = api_client.get(path)
            assert response.status_code == 409, (path, response.text)
            assert response.json()["detail"]["code"] == "INCOMPATIBLE_SESSION_SCHEMA"

        assert '"file_path"' in state_path.read_text(encoding="utf-8")
