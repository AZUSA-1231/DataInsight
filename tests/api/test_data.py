from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestDataPoolRoutes:
    def test_upload_csv(self, api_client, test_session, sample_csv_path):
        mock_data_track = {
            "data_profile": None,
            "unified_columns": ["name", "age", "salary", "dept", "hire_date"],
        }
        with (
            patch("src.api.routes.data.data_track_node", return_value=mock_data_track),
            open(sample_csv_path, "rb") as f,
        ):
            resp = api_client.post(
                f"/api/sessions/{test_session}/data/upload",
                files={"file": ("test.csv", f, "text/csv")},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["file_name"] == "test.csv"
        assert body["col_count"] == 0  # row_count also 0 because data_profile is None
        assert body["unified_columns"] == ["name", "age", "salary", "dept", "hire_date"]

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
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(test_session, {"data_profile": sample_data_profile})

        resp = api_client.get(f"/api/sessions/{test_session}/data/profile")
        assert resp.status_code == 200
        body = resp.json()
        assert body["shape"] == [100, 5]

    def test_get_profile_no_data(self, api_client, test_session):
        resp = api_client.get(f"/api/sessions/{test_session}/data/profile")
        assert resp.status_code == 404

    def test_get_columns(self, api_client, test_session):
        from src.api.session import SessionStore

        store: SessionStore = api_client.app.state.sessions
        store.update(test_session, {"unified_columns": ["销量", "地区", "日期"]})

        resp = api_client.get(f"/api/sessions/{test_session}/data/columns")
        assert resp.status_code == 200
        assert resp.json()["unified_columns"] == ["销量", "地区", "日期"]

    def test_re_upload_overwrites(self, api_client, test_session, sample_csv_path):
        mock_data_track_1 = {
            "data_profile": None,
            "unified_columns": ["name", "age", "salary"],
        }
        mock_data_track_2 = {
            "data_profile": None,
            "unified_columns": ["name", "age", "salary", "dept", "hire_date"],
        }
        with patch(
            "src.api.routes.data.data_track_node",
            side_effect=[mock_data_track_1, mock_data_track_2],
        ):
            with open(sample_csv_path, "rb") as f:
                resp1 = api_client.post(
                    f"/api/sessions/{test_session}/data/upload",
                    files={"file": ("test.csv", f, "text/csv")},
                )
            with open(sample_csv_path, "rb") as f:
                resp2 = api_client.post(
                    f"/api/sessions/{test_session}/data/upload",
                    files={"file": ("test2.csv", f, "text/csv")},
                )

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp2.json()["file_name"] == "test2.csv"
