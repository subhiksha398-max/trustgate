import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("TRUSTGATE_DB", os.path.join(tempfile.mkdtemp(), "t.db"))
from fastapi.testclient import TestClient
import app as a

def reg(c, name="Nila Kumar", email="nila@example.com", pw="Passw0rd1"):
    return c.post("/api/register", json={"name": name, "email": email, "password": pw})

def test_register_creates_creator_and_signs_in():
    c = TestClient(a.app); r = reg(c, "Kiran Das", "kiran@example.com")
    assert r.status_code == 200 and r.json()["role"] == "creator"
    assert "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/api/me").json()["username"] == "kiran@example.com"

def test_registered_user_can_log_in_with_email_and_password():
    reg(TestClient(a.app), "Mala R", "Mala@Example.com")
    c = TestClient(a.app)
    assert c.post("/api/login", json={"username": "mala@example.com", "password": "Passw0rd1", "role": "creator"}).status_code == 200
    assert c.post("/api/login", json={"username": "mala@example.com", "password": "Passw0rd1", "role": "admin"}).status_code == 403

def test_duplicates_and_bad_input_are_rejected():
    c = TestClient(a.app); reg(c, "Dev Anand", "dev@example.com")
    assert reg(c, "Dev Two", "DEV@example.com").status_code == 409
    assert reg(c, "dev anand", "dev2@example.com").status_code == 409
    assert reg(c, "Zed Q", "creator@trustgate.demo").status_code == 409
    assert reg(c, "Zed Q", "not-an-email").status_code == 400
    assert reg(c, "Zed Q", "zed@example.com", "short1").status_code == 400
    assert reg(c, "Zed Q", "zed@example.com", "onlyletters").status_code == 400
    assert reg(c, "Z", "zed@example.com").status_code == 400

def test_demo_email_accounts_work():
    for role, pw in (("creator", "Creator@123"), ("reviewer", "Reviewer@123"), ("admin", "Admin@123")):
        r = TestClient(a.app).post("/api/login", json={"username": f"{role}@trustgate.demo", "password": pw, "role": role})
        assert r.status_code == 200 and r.json()["role"] == role
