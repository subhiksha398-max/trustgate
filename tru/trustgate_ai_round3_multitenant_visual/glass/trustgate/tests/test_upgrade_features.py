import base64, io, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("TRUSTGATE_DB", os.path.join(tempfile.mkdtemp(), "upgrade.db"))
from fastapi.testclient import TestClient
from PIL import Image
import app as a
import rules


def login(role):
    user = {"creator": ("asha", "Creator@123"), "reviewer": ("ravi", "Reviewer@123"), "admin": ("meena", "Admin@123")}[role]
    c = TestClient(a.app)
    assert c.post("/api/login", json={"username": user[0], "password": user[1], "role": role}).status_code == 200
    return c


def png_b64(color=(12, 95, 255)):
    out = io.BytesIO()
    Image.new("RGB", (640, 360), color).save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode()


def test_tone_heuristics_are_review_only():
    found = rules.check("Act now and get our revolutionary product", [], "2026-01-01")
    assert any(x["type"] == "High-pressure sales language" and x["classification"] == rules.HUMAN_REVIEW for x in found)
    assert any(x["type"] == "Promotional superlative" and x["status"] == "needs_review" for x in found)


def test_review_report_contains_evidence_and_is_not_publication_claim():
    creator = login("creator")
    r = creator.post("/api/drafts", json={"title": "Review report test", "text": "SOLARA FLAT 50% OFF"})
    assert r.status_code == 200
    report = creator.get(f"/api/drafts/{r.json()['id']}/report")
    assert report.status_code == 200
    assert "Review report" in report.text and "approved evidence" in report.text.lower()
    assert "Approval is not publication" in report.text
    assert "Promo Policy v2" in report.text


def test_visual_reference_upload_requires_admin_and_checks_duplicate():
    creator = login("creator")
    assert creator.get("/api/visual-assets").status_code == 403
    admin = login("admin")
    payload = {"name": "Approved campaign artwork", "filename": "reference.png", "file_b64": png_b64()}
    r = admin.post("/api/visual-assets", json=payload)
    assert r.status_code == 200
    assert any(x["name"] == "Approved campaign artwork" for x in admin.get("/api/visual-assets").json())
    duplicate = admin.post("/api/visual-assets", json=payload)
    assert duplicate.status_code == 409
    did = creator.post("/api/drafts", json={"title": "Image match", "filename": "copy.png", "file_b64": png_b64()}).json()["id"]
    version = creator.get(f"/api/drafts/{did}").json()["versions"][0]
    assert any(x["name"] == "Approved visual reference" and x["status"] == "passed" for x in version["image_checks"])


def test_security_headers_are_present():
    response = login("creator").get("/api/me")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_production_mode_disables_public_registration(monkeypatch):
    monkeypatch.setenv("TRUSTGATE_PRODUCTION", "1")
    response = TestClient(a.app).post("/api/register", json={"name": "New User", "email": "new@example.com", "password": "Secure12345"})
    assert response.status_code == 403
    assert "disabled in production" in response.json()["detail"]


def test_secure_cookie_flag_can_be_enabled(monkeypatch):
    monkeypatch.setenv("TRUSTGATE_COOKIE_SECURE", "1")
    c = TestClient(a.app)
    response = c.post("/api/login", json={"username": "asha", "password": "Creator@123", "role": "creator"})
    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


def test_reviewer_can_open_read_only_fact_evidence():
    reviewer = login("reviewer")
    fact = a.one("SELECT id FROM facts WHERE source='Promo Policy v2' LIMIT 1")
    assert fact
    response = reviewer.get(f"/api/facts/{fact['id']}/evidence")
    assert response.status_code == 200
    assert response.json()["fact"]["source"] == "Promo Policy v2"
    assert isinstance(response.json()["history"], list)


def test_publishing_webhook_requires_approval_and_uses_signed_payload(monkeypatch):
    import json, urllib.request
    creator = login("creator")
    draft = creator.post("/api/drafts", json={"title": "Approved launch copy", "text": "Welcome to Solara."}).json()
    reviewer = login("reviewer")
    monkeypatch.setenv("TRUSTGATE_PUBLISH_WEBHOOK_URL", "https://cms.example.test/trustgate")
    monkeypatch.setenv("TRUSTGATE_PUBLISH_WEBHOOK_TOKEN", "test-publish-secret")
    assert reviewer.get("/api/publishing/status").json()["enabled"] is True
    assert reviewer.post(f"/api/drafts/{draft['id']}/publish", json={}).status_code == 409

    approved = reviewer.post(f"/api/drafts/{draft['id']}/decision", json={"decision": "approve", "comment": "Looks good.", "expected_version": 1})
    assert approved.status_code == 200
    captured = {}
    class FakeResponse:
        status = 202
        def __enter__(self): return self
        def __exit__(self, *args): return False
    def fake_urlopen(req, timeout=10):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["payload"] = json.loads(req.data.decode())
        return FakeResponse()
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    sent = reviewer.post(f"/api/drafts/{draft['id']}/publish", json={})
    assert sent.status_code == 200 and sent.json()["published"] is False
    assert captured["payload"]["event"] == "trustgate.content.approved"
    assert captured["payload"]["version"] == 1
    assert "X-trustgate-signature" in captured["headers"]
    assert reviewer.post(f"/api/drafts/{draft['id']}/publish", json={}).status_code == 409
    # The test suite shares a temporary SQLite DB across modules; remove this fixture's audit row.
    a.q("DELETE FROM audit WHERE detail LIKE ?", (f"draft {draft['id']}%",))
