import base64, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("TRUSTGATE_DB", os.path.join(tempfile.mkdtemp(), "policy.db"))
from fastapi.testclient import TestClient
import app as a


def client(role):
    account = {"creator": ("asha", "Creator@123"), "admin": ("meena", "Admin@123"), "reviewer": ("ravi", "Reviewer@123")}[role]
    c = TestClient(a.app)
    response = c.post("/api/login", json={"username": account[0], "password": account[1], "role": role})
    assert response.status_code == 200
    return c


def upload(c, filename, text, include_ai=False):
    encoded = base64.b64encode(text.encode()).decode()
    return c.post("/api/policies/import", json={"filename": filename, "file_b64": encoded, "include_ai": include_ai})


def upload_bytes(c, filename, data):
    encoded = base64.b64encode(data).decode()
    return c.post("/api/policies/import", json={"filename": filename, "file_b64": encoded})


def test_policy_import_keeps_candidates_pending_and_is_admin_only():
    creator = client("creator")
    assert upload(creator, "promo.txt", "20% off on phones").status_code == 403

    admin = client("admin")
    existing = admin.get("/api/facts").json()
    result = upload(admin, "promo.txt", "Promo: 20% off on phones valid from 2026-01-01 to 2026-02-01\nWarranty: 2 year warranty\nDo not use 'miracle'.")
    assert result.status_code == 200, result.text
    assert result.json()["proposals"] == 3
    pending = admin.get("/api/policy-proposals").json()
    assert len(pending) == 3 and all(item["status"] == "pending" for item in pending)
    source_text = "Promo: 20% off on phones valid from 2026-01-01 to 2026-02-01\nWarranty: 2 year warranty\nDo not use 'miracle'."
    assert all(item["source_quote"] in source_text and item["filename"] == "promo.txt" for item in pending)
    active = admin.get("/api/facts").json()
    assert len(active) == len(existing)
    assert not any(item["subject"] == "phones" for item in active)


def test_policy_duplicate_update_reject_and_fact_history():
    admin = client("admin")
    result = upload(admin, "price.txt", "SolaraPhone price: Rs 24,999.")
    assert result.status_code == 200 and result.json()["proposals"] == 1
    proposal = admin.get("/api/policy-proposals").json()[0]
    fact_id = next(item["id"] for item in admin.get("/api/facts").json() if item["subject"] == "SolaraPhone")
    assert proposal["matched_fact_id"] == fact_id

    unauthorized = client("reviewer")
    assert unauthorized.post(f"/api/policy-proposals/{proposal['id']}/decision", json={"decision": "update"}).status_code == 403
    decision = admin.post(f"/api/policy-proposals/{proposal['id']}/decision", json={"decision": "update"})
    assert decision.status_code == 200 and decision.json()["fact_id"] == fact_id
    updated = next(item for item in admin.get("/api/facts").json() if item["id"] == fact_id)
    assert updated["value"] == "24999" and updated["version"] == 2
    assert updated["source_quote"] == "SolaraPhone price: Rs 24,999."
    history = admin.get(f"/api/facts/{fact_id}/history").json()
    assert [row["version"] for row in history] == [1, 2]
    assert history[0]["value"] == "24999" and history[1]["source_quote"] == updated["source_quote"]
    assert any(row["action"] == "policy proposal approved" for row in admin.get("/api/audit").json())

    upload(admin, "claims.txt", "Do not use 'miracle'.")
    reject_id = admin.get("/api/policy-proposals").json()[0]["id"]
    assert admin.post(f"/api/policy-proposals/{reject_id}/decision", json={"decision": "reject"}).json()["status"] == "rejected"
    assert any(item["id"] == reject_id and item["status"] == "rejected" for item in admin.get("/api/policy-proposals?status=all").json())


def test_policy_upload_rejects_bad_extension_and_ai_request_without_ai(monkeypatch):
    import ai
    admin = client("admin")
    assert upload(admin, "policy.doc", "20% off").status_code == 400
    monkeypatch.setattr(ai, "available", lambda: False)
    assert upload(admin, "policy.txt", "20% off", include_ai=True).status_code == 400


def test_optional_ai_adds_only_valid_verbatim_candidates(monkeypatch):
    import ai
    admin = client("admin")
    monkeypatch.setattr(ai, "available", lambda: True)
    monkeypatch.setattr(ai, "extract_policy_facts", lambda text: [
        {"kind": "discount", "subject": "phones", "value": "50", "quote": "half price"},
        {"kind": "discount", "subject": "phones", "value": "40", "quote": "fabricated quote"},
        {"kind": "discount", "subject": "phones", "value": "20", "valid_from": "2026-99-99", "quote": "half price"},
        {"kind": "unknown", "subject": "phones", "value": "1", "quote": "half price"}])
    result = upload(admin, "offer.txt", "The phones are half price.", include_ai=True)
    assert result.status_code == 200 and result.json()["ai"] == "completed"
    proposal = [item for item in admin.get("/api/policy-proposals").json() if item["policy_id"] == result.json()["id"]]
    assert len(proposal) == 1 and proposal[0]["kind"] == "discount" and proposal[0]["source_quote"] == "half price"
    assert not any(f["subject"] == "phones" for f in admin.get("/api/facts").json())


def test_ai_extraction_failure_keeps_deterministic_proposals_pending(monkeypatch):
    import ai
    admin = client("admin")
    monkeypatch.setattr(ai, "available", lambda: True)
    def fail(_): raise RuntimeError("temporary failure")
    monkeypatch.setattr(ai, "extract_policy_facts", fail)
    result = upload(admin, "offer.txt", "Save 20% off today.", include_ai=True)
    assert result.status_code == 200 and result.json()["ai"] == "failed"
    proposals = [item for item in admin.get("/api/policy-proposals").json() if item["policy_id"] == result.json()["id"]]
    assert len(proposals) == 1
    assert not any(f["value"] == "20" for f in admin.get("/api/facts").json())


def test_pdf_and_docx_policy_import_use_shared_text_reader():
    import io
    from docx import Document
    import test_rules
    admin = client("admin")
    pdf = upload_bytes(admin, "policy.pdf", test_rules._make_pdf("Save 25% off today"))
    assert pdf.status_code == 200 and pdf.json()["proposals"] == 1
    doc = Document(); doc.add_paragraph("Warranty: 3 year warranty")
    data = io.BytesIO(); doc.save(data)
    word = upload_bytes(admin, "warranty.docx", data.getvalue())
    assert word.status_code == 200 and word.json()["proposals"] == 1
    policy_ids = {pdf.json()["id"], word.json()["id"]}
    proposals = [item for item in admin.get("/api/policy-proposals").json() if item["policy_id"] in policy_ids]
    assert {item["filename"] for item in proposals} == {"policy.pdf", "warranty.docx"}


def test_old_findings_keep_the_fact_version_and_quote_after_fact_edit():
    admin = client("admin")
    current_price = next(item for item in admin.get("/api/facts").json() if item["subject"] == "SolaraPhone")
    result = upload(admin, "price.txt", "SolaraPhone price: Rs 24,999.")
    proposal = admin.get("/api/policy-proposals").json()[0]
    price_id = proposal["matched_fact_id"]
    assert price_id is not None
    assert admin.post(f"/api/policy-proposals/{proposal['id']}/decision", json={"decision": "update"}).status_code == 200
    first_version = current_price["version"] + 1

    creator = client("creator")
    created = creator.post("/api/drafts", json={"title": "Evidence snapshot", "text": "SolaraPhone price Rs 25,000."})
    assert created.status_code == 200
    draft = creator.get(f"/api/drafts/{created.json()['id']}").json()
    issue = draft["versions"][0]["issues"][0]
    assert issue["fact_id"] == price_id and issue["fact_version"] == first_version
    first_quote = "SolaraPhone price: Rs 24,999."
    assert issue["source_quote"] == first_quote

    update = upload(admin, "price-v2.txt", "SolaraPhone price: Rs 23,999.")
    second_proposal = next(item for item in admin.get("/api/policy-proposals").json() if item["policy_id"] == update.json()["id"])
    assert admin.post(f"/api/policy-proposals/{second_proposal['id']}/decision", json={"decision": "update"}).status_code == 200
    old_issue = creator.get(f"/api/drafts/{created.json()['id']}").json()["versions"][0]["issues"][0]
    updated = next(item for item in admin.get("/api/facts").json() if item["id"] == price_id)
    assert updated["version"] == first_version + 1 and updated["source_quote"] == "SolaraPhone price: Rs 23,999."
    assert old_issue["fact_version"] == first_version and old_issue["source_quote"] == first_quote


def test_direct_fact_edit_and_delete_are_versioned_and_audited():
    admin = client("admin")
    fact = next(item for item in admin.get("/api/facts").json() if item["subject"] == "SolaraPhone")
    payload = {key: fact[key] for key in ("kind", "subject", "value", "valid_from", "valid_to", "source")}
    payload["source_quote"] = "Unverified replacement evidence."
    reviewer = client("reviewer")
    assert reviewer.put(f"/api/facts/{fact['id']}", json=payload).status_code == 403
    updated = admin.put(f"/api/facts/{fact['id']}", json=payload)
    assert updated.status_code == 200 and updated.json()["version"] == fact["version"] + 1
    current = next(item for item in admin.get("/api/facts").json() if item["id"] == fact["id"])
    assert current["source_quote"] == fact["source_quote"]
    assert admin.get(f"/api/facts/{fact['id']}/history").json()[-1]["action"] == "updated"
    assert admin.delete(f"/api/facts/{fact['id']}").status_code == 200
    history = admin.get(f"/api/facts/{fact['id']}/history")
    assert history.status_code == 200 and history.json()[-1]["action"] == "deleted"
    audit = admin.get("/api/audit").json()
    assert any(item["action"] == "fact edited" for item in audit)
    assert any(item["action"] == "fact removed" for item in audit)


def test_manual_policy_fact_change_clears_active_citation_but_keeps_history():
    admin = client("admin")
    admin.post("/api/facts", json={"kind": "price", "subject": "TestPhone", "value": "10000", "source": "Test price list"})
    imported = upload(admin, "price.txt", "TestPhone price: Rs 9,999.").json()
    proposal = next(item for item in admin.get("/api/policy-proposals").json() if item["policy_id"] == imported["id"])
    fact_id = proposal["matched_fact_id"]
    assert admin.post(f"/api/policy-proposals/{proposal['id']}/decision", json={"decision": "update"}).status_code == 200
    fact = next(item for item in admin.get("/api/facts").json() if item["id"] == fact_id)
    payload = {key: fact[key] for key in ("kind", "subject", "value", "valid_from", "valid_to", "source")}
    payload["value"] = "23999"
    result = admin.put(f"/api/facts/{fact_id}", json=payload)
    assert result.status_code == 200
    current = next(item for item in admin.get("/api/facts").json() if item["id"] == fact_id)
    assert current["source"] == "Manual update" and current["source_quote"] == "" and current["source_document_id"] is None
    history = admin.get(f"/api/facts/{fact_id}/history").json()
    assert history[-2]["source_quote"] == "TestPhone price: Rs 9,999."
    assert history[-1]["source_quote"] == "" and "policy evidence cleared" in admin.get("/api/audit").json()[0]["detail"]


def test_existing_database_gets_a_legacy_fact_history_baseline(tmp_path, monkeypatch):
    import sqlite3
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE facts(id INTEGER PRIMARY KEY, kind TEXT, subject TEXT, value TEXT, valid_from TEXT, valid_to TEXT, source TEXT)")
    connection.execute("INSERT INTO facts VALUES(41,'discount','all items','15','2026-01-01','2026-12-31','Old policy')")
    connection.commit(); connection.close()
    monkeypatch.setattr(a, "DB", str(database))
    a.init()
    fact = a.one("SELECT * FROM facts WHERE id=41")
    history = a.q("SELECT * FROM fact_history WHERE fact_id=41")
    assert fact["version"] == 1 and fact["source_quote"] == ""
    assert len(history) == 1 and history[0]["action"] == "legacy baseline" and history[0]["value"] == "15"