import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("TRUSTGATE_DB", os.path.join(tempfile.mkdtemp(), "t.db"))
from fastapi.testclient import TestClient
import app as a

ACC = {"creator": ("asha", "Creator@123"), "reviewer": ("ravi", "Reviewer@123"), "admin": ("meena", "Admin@123")}
def client(role):
    c = TestClient(a.app); u, p = ACC[role]
    assert c.post("/api/login", json={"username": u, "password": p, "role": role}).status_code == 200
    return c

def test_everything_requires_sign_in():
    c = TestClient(a.app)
    for path in ("/api/me", "/api/drafts", "/api/facts", "/api/audit", "/api/analytics", "/api/ai/status"):
        assert c.get(path).status_code == 401, path
    assert c.post("/api/drafts", json={"title": "x", "text": "y"}).status_code == 401

def test_login_returns_server_side_role_and_sets_httponly_cookie():
    c = TestClient(a.app)
    r = c.post("/api/login", json={"username": "Ravi", "password": "Reviewer@123", "role": "reviewer"})
    assert r.json() == {"username": "ravi", "name": "Ravi", "role": "reviewer"}
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=lax" in r.headers["set-cookie"].lower()
    assert c.get("/api/me").json()["role"] == "reviewer"

def test_wrong_password_and_unknown_user_give_the_same_error():
    c = TestClient(a.app)
    r1 = c.post("/api/login", json={"username": "asha", "password": "nope", "role": "creator"})
    r2 = c.post("/api/login", json={"username": "ghost", "password": "nope", "role": "creator"})
    assert r1.status_code == r2.status_code == 401 and r1.json() == r2.json()

def test_role_must_match_the_account():
    r = TestClient(a.app).post("/api/login", json={"username": "asha", "password": "Creator@123", "role": "admin"})
    assert r.status_code == 403 and "Creator" in r.json()["detail"]

def test_browser_cannot_claim_a_role_with_headers():
    c = client("creator")
    r = c.post("/api/facts", json={"kind": "banned", "subject": "x"}, headers={"X-Role": "admin", "X-User": "Meena"})
    assert r.status_code == 403
    assert c.get("/api/audit", headers={"X-Role": "admin"}).status_code == 403

def test_role_permissions():
    assert client("admin").post("/api/facts", json={"kind": "banned", "subject": "zz-test"}).status_code == 200
    assert client("reviewer").post("/api/facts", json={"kind": "banned", "subject": "x"}).status_code == 403
    assert client("admin").post("/api/drafts", json={"title": "t", "text": "x"}).status_code == 403
    assert client("creator").get("/api/analytics").status_code == 403
    assert client("reviewer").get("/api/audit").status_code == 200

def test_creators_only_see_their_own_drafts():
    asha = client("creator"); did = asha.post("/api/drafts", json={"title": "Mine", "text": "Save 15% today"}).json()["id"]
    a.q("INSERT INTO users(username,name,role,salt,pwd_hash) VALUES('bo','Bo','creator',?,?)", ("00" * 16, a.hash_pw("Bo@12345", bytes(16))))
    bo = TestClient(a.app); assert bo.post("/api/login", json={"username": "bo", "password": "Bo@12345", "role": "creator"}).status_code == 200
    assert did not in [d["id"] for d in bo.get("/api/drafts").json()]
    assert bo.get(f"/api/drafts/{did}").status_code == 403
    assert bo.post(f"/api/drafts/{did}/comments", json={"text": "hi"}).status_code == 403
    assert did in [d["id"] for d in client("reviewer").get("/api/drafts").json()]

def test_logout_ends_the_session():
    c = client("creator"); assert c.get("/api/me").status_code == 200
    assert c.post("/api/logout").status_code == 200
    assert c.get("/api/me").status_code == 401

def test_expired_session_is_rejected():
    c = client("creator"); a.q("UPDATE sessions SET expires=0"); assert c.get("/api/me").status_code == 401

def test_repeated_failures_lock_the_username_temporarily():
    c = TestClient(a.app)
    for _ in range(5): assert c.post("/api/login", json={"username": "lockme", "password": "x", "role": "creator"}).status_code == 401
    r = c.post("/api/login", json={"username": "lockme", "password": "x", "role": "creator"}); assert r.status_code == 429

def test_passwords_are_stored_hashed():
    u = a.one("SELECT * FROM users WHERE username='asha'")
    assert "Creator@123" not in str(u) and len(u["pwd_hash"]) == 64 and len(u["salt"]) == 32
