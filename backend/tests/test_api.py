"""API integration tests — exercises all major endpoints end-to-end.

Run with: python3 -m pytest backend/tests/test_api.py -v
Requires: p51_automator database running with seed data.
"""
import pytest
import httpx

BASE = "http://localhost:8001/api/v1"


@pytest.fixture(scope="module")
def admin_token():
    """Login as admin and return JWT token."""
    r = httpx.post(f"{BASE}/auth/jwt/login", data={"username": "admin", "password": "admin"})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


class TestAuth:
    def test_login_valid(self):
        r = httpx.post(f"{BASE}/auth/jwt/login", data={"username": "admin", "password": "admin"})
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_login_invalid(self):
        r = httpx.post(f"{BASE}/auth/jwt/login", data={"username": "admin", "password": "wrong"})
        assert r.status_code == 400

    def test_unauthenticated(self):
        r = httpx.get(f"{BASE}/users/me")
        assert r.status_code == 401


class TestUsers:
    def test_get_me(self, admin_headers):
        r = httpx.get(f"{BASE}/users/me", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["user_name"] == "admin"
        assert data["is_superuser"] is True

    def test_list_users(self, admin_headers):
        r = httpx.get(f"{BASE}/manage/users", headers=admin_headers)
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_create_and_login_user(self, admin_headers):
        import time
        uname = f"testapi_{int(time.time())}"

        # Create
        r = httpx.post(f"{BASE}/manage/users", headers=admin_headers, json={
            "user_name": uname,
            "full_name": "API Test User",
            "email": f"{uname}@test.com",
            "password": "testpass",
            "group_id": 2,
        })
        assert r.status_code == 201, f"Create failed: {r.text}"
        user_id = r.json()["user_id"]

        # Login as new user
        r = httpx.post(f"{BASE}/auth/jwt/login", data={"username": uname, "password": "testpass"})
        assert r.status_code == 200

        # Update
        r = httpx.put(f"{BASE}/manage/users/{user_id}", headers=admin_headers, json={
            "full_name": "Updated Name",
        })
        assert r.status_code == 200
        assert r.json()["full_name"] == "Updated Name"

        # Password reset
        r = httpx.put(f"{BASE}/manage/users/{user_id}", headers=admin_headers, json={
            "password": "newpass123",
        })
        assert r.status_code == 200

        # Login with new password
        r = httpx.post(f"{BASE}/auth/jwt/login", data={"username": uname, "password": "newpass123"})
        assert r.status_code == 200


class TestGroups:
    def test_list_groups(self, admin_headers):
        r = httpx.get(f"{BASE}/manage/groups", headers=admin_headers)
        assert r.status_code == 200
        groups = r.json()
        assert len(groups) >= 2
        names = [g["group_name"] for g in groups]
        assert "System" in names

    def test_create_group(self, admin_headers):
        import time
        name = f"Test Group {int(time.time())}"
        r = httpx.post(f"{BASE}/manage/groups", headers=admin_headers, json={
            "group_name": name,
        })
        assert r.status_code == 201
        assert r.json()["group_name"] == name


class TestSettings:
    def test_webapp_options_public(self):
        r = httpx.get(f"{BASE}/settings/webapp_options")
        assert r.status_code == 200
        data = r.json()
        assert "app_title" in data
        assert "navbar_color" in data

    def test_get_settings(self, admin_headers):
        r = httpx.get(f"{BASE}/settings", headers=admin_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_upsert_setting(self, admin_headers):
        r = httpx.put(f"{BASE}/settings/test_key", headers=admin_headers, json={"value": "test_val"})
        assert r.status_code == 200
        assert r.json()["value"] == "test_val"

        # Clean up
        r = httpx.delete(f"{BASE}/settings/test_key", headers=admin_headers)
        assert r.status_code == 200


class TestWorkflows:
    def test_list_types(self, admin_headers):
        r = httpx.get(f"{BASE}/workflow-types", headers=admin_headers)
        assert r.status_code == 200
        types = r.json()
        assert len(types) == 4
        names = [t["type_name"] for t in types]
        assert "Email Topic Monitor" in names
        assert "Calendar Digest" in names

    def test_create_workflow(self, admin_headers):
        r = httpx.post(f"{BASE}/workflows", headers=admin_headers, json={
            "type_id": 3,
            "name": "API Test Calendar",
            "config": {"calendars": ["Work"], "days": 3},
        })
        assert r.status_code == 200
        wf = r.json()
        assert wf["name"] == "API Test Calendar"
        assert wf["type_id"] == 3

    def test_list_workflows(self, admin_headers):
        r = httpx.get(f"{BASE}/workflows", headers=admin_headers)
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_update_workflow(self, admin_headers):
        # Create one first
        r = httpx.post(f"{BASE}/workflows", headers=admin_headers, json={
            "type_id": 1,
            "name": "Temp Workflow",
            "config": {"account": "iCloud"},
        })
        wf_id = r.json()["workflow_id"]

        # Update name
        r = httpx.put(f"{BASE}/workflows/{wf_id}", headers=admin_headers, json={
            "name": "Renamed Workflow",
        })
        assert r.status_code == 200
        assert r.json()["name"] == "Renamed Workflow"

        # Delete
        r = httpx.delete(f"{BASE}/workflows/{wf_id}", headers=admin_headers)
        assert r.status_code == 200


class TestDashboard:
    def test_stats(self, admin_headers):
        r = httpx.get(f"{BASE}/dashboard/stats", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert "total_workflows" in data
        assert "total_runs" in data
        assert "scheduler_running" in data


class TestScheduler:
    def test_status(self, admin_headers):
        r = httpx.get(f"{BASE}/scheduler/status", headers=admin_headers)
        assert r.status_code == 200
        assert "running" in r.json()


class TestArtifacts:
    def test_download_existing(self, admin_headers):
        """Test downloading an artifact that exists from a previous run."""
        # Get runs for workflow 1 (email monitor)
        r = httpx.get(f"{BASE}/workflows/1/runs", headers=admin_headers)
        if r.status_code != 200 or not r.json():
            pytest.skip("No runs available to test artifact download")

        run_id = r.json()[0]["run_id"]
        r = httpx.get(f"{BASE}/runs/{run_id}/artifacts", headers=admin_headers)
        if r.status_code != 200 or not r.json():
            pytest.skip("No artifacts available")

        artifact_id = r.json()[0]["artifact_id"]
        r = httpx.get(f"{BASE}/artifacts/{artifact_id}/download", headers=admin_headers)
        assert r.status_code == 200
        assert len(r.content) > 0

    def test_download_nonexistent(self, admin_headers):
        r = httpx.get(f"{BASE}/artifacts/99999/download", headers=admin_headers)
        assert r.status_code == 404
