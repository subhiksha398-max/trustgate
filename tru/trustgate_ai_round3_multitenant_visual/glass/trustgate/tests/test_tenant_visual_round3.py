import base64, io, json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("TRUSTGATE_DB", os.path.join(tempfile.mkdtemp(), "round3-default.db"))
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import app as a


def b64_png(image):
    buf = io.BytesIO(); image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def login_on(host, role="admin"):
    creds = {"creator": ("asha", "Creator@123"), "reviewer": ("ravi", "Reviewer@123"), "admin": ("meena", "Admin@123")}[role]
    client = TestClient(a.app, base_url=f"http://{host}")
    response = client.post("/api/login", json={"username": creds[0], "password": creds[1], "role": role})
    assert response.status_code == 200, response.text
    return client


def test_multi_tenant_host_mapping_isolates_database_and_assets(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUSTGATE_MULTI_TENANT", "1")
    monkeypatch.setenv("TRUSTGATE_ORG_HOSTS", json.dumps({"acme.test": "acme", "northwind.test": "northwind"}))
    monkeypatch.setenv("TRUSTGATE_TENANT_DB_DIR", str(tmp_path / "dbs"))
    monkeypatch.setenv("TRUSTGATE_ASSET_DIR", str(tmp_path / "assets"))
    # Ensure this test uses freshly initialized tenant databases.
    a.INITIALIZED_TENANT_DBS.clear()
    acme = login_on("acme.test")
    northwind = login_on("northwind.test")
    assert acme.get("/api/me").json()["organization"] == "acme"
    assert northwind.get("/api/me").json()["organization"] == "northwind"
    created = acme.post("/api/facts", json={"kind": "claim", "subject": "ACME secret phrase", "value": "private"})
    assert created.status_code == 200
    acme_facts = acme.get("/api/facts").json()
    northwind_facts = northwind.get("/api/facts").json()
    assert any(f["subject"] == "ACME secret phrase" for f in acme_facts)
    assert not any(f["subject"] == "ACME secret phrase" for f in northwind_facts)
    visual = Image.new("RGB", (100, 60), "white")
    ImageDraw.Draw(visual).rectangle((10, 10, 80, 50), fill="#0B5FFF")
    uploaded = acme.post("/api/visual-assets", json={"name": "Acme-only logo", "filename": "logo.png", "file_b64": b64_png(visual), "asset_type": "logo"})
    assert uploaded.status_code == 200, uploaded.text
    assert any(x["name"] == "Acme-only logo" for x in acme.get("/api/visual-assets").json())
    assert not any(x["name"] == "Acme-only logo" for x in northwind.get("/api/visual-assets").json())
    assert (tmp_path / "assets" / "acme").is_dir()
    assert (tmp_path / "assets" / "northwind").is_dir()
    assert (tmp_path / "dbs" / "acme.sqlite3").exists()
    assert (tmp_path / "dbs" / "northwind.sqlite3").exists()
    assert acme.get("/api/me", headers={"host": "unmapped.test"}).status_code == 421


def test_visual_asset_type_is_saved_and_returned(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUSTGATE_ASSET_DIR", str(tmp_path / "assets"))
    admin = login_on("testserver")
    logo = Image.new("RGB", (100, 60), "white")
    draw = ImageDraw.Draw(logo)
    draw.rectangle((8, 8, 43, 52), fill="#0B5FFF")
    draw.ellipse((50, 12, 90, 48), fill="#FFB703")
    response = admin.post("/api/visual-assets", json={"name": "Solara logo", "filename": "logo.png", "file_b64": b64_png(logo), "asset_type": "logo"})
    assert response.status_code == 200, response.text
    rows = admin.get("/api/visual-assets").json()
    assert any(x["name"] == "Solara logo" and x["asset_type"] == "logo" for x in rows)


def test_embedded_logo_matcher_detects_reference_inside_poster(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUSTGATE_ASSET_DIR", str(tmp_path / "assets"))
    admin = login_on("testserver")
    logo = Image.new("RGB", (100, 60), "white")
    draw = ImageDraw.Draw(logo)
    draw.rectangle((8, 8, 43, 52), fill="#0B5FFF")
    draw.ellipse((50, 12, 90, 48), fill="#FFB703")
    draw.line((8, 30, 90, 30), fill="#172033", width=4)
    upload = admin.post("/api/visual-assets", json={"name": "Template logo", "filename": "logo.png", "file_b64": b64_png(logo), "asset_type": "logo"})
    assert upload.status_code == 200, upload.text
    poster = Image.new("RGB", (600, 360), "#e7edf5")
    poster.paste(logo.resize((70, 42)), (245, 120))
    creator = login_on("testserver", "creator")
    draft = creator.post("/api/drafts", json={"title": "Poster with embedded logo", "filename": "poster.png", "file_b64": b64_png(poster)})
    assert draft.status_code == 200, draft.text
    details = creator.get(f"/api/drafts/{draft.json()['id']}").json()
    checks = details["versions"][0]["image_checks"]
    logo_check = next(c for c in checks if c["name"] == "Embedded approved logo")
    assert logo_check["status"] in {"passed", "review"}
    assert "score" in logo_check["detail"] or "similarity" in logo_check["detail"]
