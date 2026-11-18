def test_requires_login(client):
    assert client.get("/api/v1/channels").status_code == 401
    assert client.get("/api/v1/media/videos/1/final.mp4").status_code == 401


def test_first_user_is_admin_then_registration_closes(client):
    r = client.post("/api/v1/auth/register", json={"email": "a@example.com", "password": "password123"})
    assert r.json()["role"] == "admin"
    assert client.post("/api/v1/auth/register", json={"email": "b@example.com", "password": "password123"}).status_code == 403


def test_viewer_cannot_change_settings(admin):
    admin.post("/api/v1/auth/users?role=viewer", json={"email": "v@example.com", "password": "password123"})
    admin.post("/api/v1/auth/logout")
    assert admin.post("/api/v1/auth/login", json={"email": "v@example.com", "password": "password123"}).status_code == 200
    assert admin.get("/api/v1/settings").status_code == 200
    assert admin.patch("/api/v1/settings", json={"monthly_budget_usd": 5}).status_code == 403


def test_provider_keys_are_never_returned(admin):
    provs = admin.get("/api/v1/providers").json()
    anthropic = next(p for p in provs if p["kind"] == "llm" and p["name"] == "anthropic")
    assert anthropic["model"]["model_name"] == "claude-opus-5-5"
    r = admin.patch(f"/api/v1/providers/{anthropic['id']}", json={"api_key": "sk-ant-super-secret-123456"})
    body = r.json()
    assert "super-secret" not in r.text and body["api_key_set"] is True
    assert "api_key_enc" not in body


def test_unattended_publishing_needs_explicit_confirmation(admin):
    assert admin.patch("/api/v1/settings", json={"unattended_publishing_enabled": True}).status_code == 400
    r = admin.patch("/api/v1/settings", json={"unattended_publishing_enabled": True, "confirm_unattended": True})
    assert r.status_code == 200 and r.json()["unattended_publishing_confirmed_at"]


def test_google_connect_returns_consent_url_with_minimal_scopes(admin):
    r = admin.post("/api/v1/channels/connect", json={"mode": "google"})
    url = r.json()["auth_url"]
    assert "youtube.upload" in url and "access_type=offline" in url
    assert "auth%2Fyoutube+" not in url and not url.endswith("auth%2Fyoutube")  # broad scope off by default


def test_oauth_callback_rejects_bad_state(client):
    r = client.get("/api/v1/auth/youtube/callback?code=x&state=forged", follow_redirects=False)
    assert r.status_code in (302, 307) and "oauth_error" in r.headers["location"]
