import base64, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("TRUSTGATE_DB", os.path.join(tempfile.mkdtemp(), "u.db"))
from fastapi.testclient import TestClient
import app as a

def creator():
    c = TestClient(a.app)
    assert c.post("/api/login", json={"username": "asha", "password": "Creator@123", "role": "creator"}).status_code == 200
    return c

def b64(t): return base64.b64encode(t.encode()).decode()

def test_resubmit_accepts_a_new_file_version():
    c = creator()
    did = c.post("/api/drafts", json={"title": "Banner", "text": "SOLARA FLAT 50% OFF. LIFETIME WARRANTY"}).json()["id"]
    reviewer = TestClient(a.app)
    assert reviewer.post("/api/login", json={"username": "ravi", "password": "Reviewer@123", "role": "reviewer"}).status_code == 200
    assert reviewer.post(f"/api/drafts/{did}/decision", json={"decision": "return", "comment": "Please revise.", "expected_version": 1}).status_code == 200
    r = c.post(f"/api/drafts/{did}/resubmit", json={"filename": "v2.txt", "file_b64": b64("Solara Tech: 15% off with a 12-month warranty.")})
    assert r.status_code == 200
    v = c.get(f"/api/drafts/{did}").json()["versions"]
    assert len(v) == 2 and v[1]["filename"] == "v2.txt" and "12-month" in v[1]["content"]

def test_resubmit_rejects_unsupported_file_type():
    c = creator()
    did = c.post("/api/drafts", json={"title": "Banner", "text": "Hello"}).json()["id"]
    reviewer = TestClient(a.app)
    assert reviewer.post("/api/login", json={"username": "ravi", "password": "Reviewer@123", "role": "reviewer"}).status_code == 200
    assert reviewer.post(f"/api/drafts/{did}/decision", json={"decision": "return", "comment": "Please revise.", "expected_version": 1}).status_code == 200
    r = c.post(f"/api/drafts/{did}/resubmit", json={"filename": "v2.xlsx", "file_b64": b64("x")})
    assert r.status_code == 400

def test_renamed_pdf_as_docx_gets_a_clear_message():
    c = creator()
    r = c.post("/api/drafts", json={"title": "x", "filename": "fake.docx", "file_b64": b64("%PDF-1.4 not a zip")})
    assert r.status_code == 400 and "real Word .docx" in r.json()["detail"]

def test_old_doc_files_get_a_save_as_docx_hint():
    c = creator()
    r = c.post("/api/drafts", json={"title": "x", "filename": "old.doc", "file_b64": b64("x")})
    assert r.status_code == 400 and ".docx" in r.json()["detail"]


def pdf_b64(line):
    import test_rules; import base64
    return base64.b64encode(test_rules._make_pdf(line)).decode()

def test_pdf_upload_is_read_and_checked():
    c = creator()
    r = c.post("/api/drafts", json={"title": "Brief", "filename": "brief.pdf", "file_b64": pdf_b64("SOLARA FLAT 50% OFF. LIFETIME WARRANTY")})
    assert r.status_code == 200
    v = c.get(f"/api/drafts/{r.json()['id']}").json()["versions"][0]
    assert v["filename"] == "brief.pdf" and [i["type"] for i in v["issues"]] == ["Discount mismatch", "Warranty unsupported"]

def test_broken_or_textless_pdf_gets_a_clear_message():
    c = creator()
    r = c.post("/api/drafts", json={"title": "x", "filename": "bad.pdf", "file_b64": b64("not a pdf")})
    assert r.status_code == 400 and "PDF" in r.json()["detail"]
    from pypdf import PdfWriter; import io, base64
    w = PdfWriter(); w.add_blank_page(200, 200); b = io.BytesIO(); w.write(b)
    r = c.post("/api/drafts", json={"title": "x", "filename": "scan.pdf", "file_b64": base64.b64encode(b.getvalue()).decode()})
    assert r.status_code == 400 and "no selectable text" in r.json()["detail"]

def png_b64():
    import io, base64; from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (800, 400), "#0B5FFF").save(b, "PNG"); return base64.b64encode(b.getvalue()).decode()

def image_b64(color="#0B5FFF", size=(800, 400)):
    import io, base64; from PIL import Image
    b = io.BytesIO(); Image.new("RGB", size, color).save(b, "PNG"); return base64.b64encode(b.getvalue()).decode()

def test_image_upload_persists_actual_local_check_statuses(monkeypatch):
    import ai
    monkeypatch.setattr(ai, "available", lambda: False)
    c = creator()
    r = c.post("/api/drafts", json={"title": "Valid poster", "filename": "poster.png", "file_b64": png_b64()})
    assert r.status_code == 200
    version = c.get(f"/api/drafts/{r.json()['id']}").json()["versions"][0]
    checks = {item["name"]: item for item in version["image_checks"]}
    assert checks["File format"]["status"] == "passed" and checks["Dimensions"]["status"] == "passed"
    assert checks["Brand colours"]["status"] == "passed"
    assert checks["Visible text extraction"]["status"] == "unavailable"
    assert checks["Logo presence"]["status"] == "unavailable"
    assert checks["Text readability"]["status"] == "not_performed"
    assert any(issue["type"] == "Image text not read" and issue["classification"] == "Needs human review"
               for issue in version["issues"])

def test_image_upload_rejects_malformed_contents_despite_png_extension():
    import base64
    c = creator()
    payload = base64.b64encode(b"not a PNG or JPEG").decode()
    response = c.post("/api/drafts", json={"title": "Invalid image", "filename": "fake.png", "file_b64": payload})
    assert response.status_code == 400 and "contents" in response.json()["detail"]

def test_image_bytes_cannot_be_uploaded_as_plain_text():
    c = creator()
    response = c.post("/api/drafts", json={"title": "Renamed image", "filename": "poster.txt", "file_b64": png_b64()})
    assert response.status_code == 400 and "image data" in response.json()["detail"]

def test_image_upload_rejects_oversized_file(monkeypatch):
    import base64
    monkeypatch.setattr(a, "MAX_UPLOAD", 10)
    c = creator()
    payload = base64.b64encode(b"01234567890").decode()
    response = c.post("/api/drafts", json={"title": "Large image", "filename": "large.png", "file_b64": payload})
    assert response.status_code == 400 and "larger than 10 MB" in response.json()["detail"]

def test_image_upload_rejects_excessive_decoded_dimensions():
    c = creator()
    response = c.post("/api/drafts", json={"title": "Huge image", "filename": "huge.png", "file_b64": image_b64(size=(4000, 4000))})
    assert response.status_code == 400 and "dimensions" in response.json()["detail"]

def test_existing_versions_table_gets_image_check_metadata_migration(tmp_path, monkeypatch):
    import sqlite3
    database = tmp_path / "legacy-image.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE versions(id INTEGER PRIMARY KEY, draft_id INT, n INT, content TEXT, filename TEXT, issues TEXT, author TEXT, at TEXT)")
    connection.commit(); connection.close()
    monkeypatch.setattr(a, "DB", str(database))
    a.init()
    columns = {row["name"] for row in a.q("PRAGMA table_info(versions)")}
    assert "image_checks" in columns

def test_image_upload_records_dimensions_and_colour_mismatch(monkeypatch):
    import ai
    monkeypatch.setattr(ai, "available", lambda: False)
    c = creator()
    small = c.post("/api/drafts", json={"title": "Small image", "filename": "small.png", "file_b64": image_b64(size=(400, 200))})
    assert small.status_code == 200
    small_version = c.get(f"/api/drafts/{small.json()['id']}").json()["versions"][0]
    assert any(f["type"] == "Image too small" for f in small_version["issues"])
    assert next(x for x in small_version["image_checks"] if x["name"] == "Dimensions")["status"] == "review"

    off_palette = c.post("/api/drafts", json={"title": "Off palette", "filename": "dark.png", "file_b64": image_b64("#111111")})
    assert off_palette.status_code == 200
    palette_version = c.get(f"/api/drafts/{off_palette.json()['id']}").json()["versions"][0]
    color_issue = next(f for f in palette_version["issues"] if f["type"] == "Colour differs from sampled brand palette")
    assert color_issue["classification"] == "Needs human review"
    assert next(x for x in palette_version["image_checks"] if x["name"] == "Brand colours")["status"] == "review"

def test_image_text_is_checked_when_ai_reads_it(monkeypatch):
    import ai
    c = creator()
    monkeypatch.setattr(ai, "available", lambda: True)
    def reply(system, user, max_tokens=1500):
        if isinstance(user, list): return "SOLARA POSTER\nHalf price. Warranty for life."
        return '{"findings": []}'
    monkeypatch.setattr(ai, "_call", reply)
    r = c.post("/api/drafts", json={"title": "Poster", "filename": "poster.png", "file_b64": png_b64()}); assert r.status_code == 200
    v = c.get(f"/api/drafts/{r.json()['id']}").json()["versions"][0]
    assert v["content"].startswith("[Image: poster.png]\nSOLARA POSTER")
    hits = [i for i in v["issues"] if i["type"] in ("Discount mismatch", "Warranty unsupported")]
    assert len(hits) == 2 and all(v["content"][i["start"]:i["end"]] == i["phrase"] for i in hits)   # highlights line up after the header
    assert all(i["status"] == "needs_review" and i["classification"] == "Needs human review" and i["by"] == "Vision" for i in hits)
    assert next(item for item in v["image_checks"] if item["name"] == "Visible text extraction")["status"] == "completed"
    assert not any(i["type"] == "Image text not read" for i in v["issues"])

def test_image_without_ai_is_flagged_for_a_human_instead_of_passing_silently(monkeypatch):
    import ai
    c = creator(); monkeypatch.setattr(ai, "available", lambda: False)
    r = c.post("/api/drafts", json={"title": "Poster", "filename": "poster.png", "file_b64": png_b64()}); assert r.status_code == 200
    v = c.get(f"/api/drafts/{r.json()['id']}").json()["versions"][0]
    f = [i for i in v["issues"] if i["type"] == "Image text not read"]
    assert len(f) == 1 and f[0]["status"] == "needs_review" and v["content"] == "[Image: poster.png]"
    assert next(item for item in v["image_checks"] if item["name"] == "Visible text extraction")["status"] == "unavailable"

def test_image_vision_failure_does_not_block_the_check(monkeypatch):
    import ai
    c = creator(); monkeypatch.setattr(ai, "available", lambda: True)
    def boom(*a, **k): raise RuntimeError("down")
    monkeypatch.setattr(ai, "_call", boom)
    r = c.post("/api/drafts", json={"title": "Poster", "filename": "poster.jpg", "file_b64": png_b64()}); assert r.status_code == 200
    version = c.get(f"/api/drafts/{r.json()['id']}").json()["versions"][0]
    assert next(item for item in version["image_checks"] if item["name"] == "Visible text extraction")["status"] == "failed"

def test_image_vision_no_text_still_requires_human_review(monkeypatch):
    import ai
    c = creator(); monkeypatch.setattr(ai, "available", lambda: True)
    monkeypatch.setattr(ai, "read_image_text", lambda _: "")
    r = c.post("/api/drafts", json={"title": "No OCR text", "filename": "poster.png", "file_b64": png_b64()})
    assert r.status_code == 200
    version = c.get(f"/api/drafts/{r.json()['id']}").json()["versions"][0]
    result = next(item for item in version["image_checks"] if item["name"] == "Visible text extraction")
    assert result["status"] == "no_text_returned"
    assert any(issue["type"] == "Image text not read" and issue["classification"] == "Needs human review"
               for issue in version["issues"])
