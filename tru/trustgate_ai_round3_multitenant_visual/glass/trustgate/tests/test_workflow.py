import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("TRUSTGATE_DB", os.path.join(tempfile.mkdtemp(), "workflow.db"))
import sqlite3
from fastapi.testclient import TestClient
import app as a

ACCOUNTS = {"creator": ("asha", "Creator@123"), "reviewer": ("ravi", "Reviewer@123"), "admin": ("meena", "Admin@123")}


def client(role):
    user, password = ACCOUNTS[role]
    result = TestClient(a.app)
    response = result.post("/api/login", json={"username": user, "password": password, "role": role})
    assert response.status_code == 200
    return result


def make_draft(creator, title="Workflow draft", text="SOLARA FLAT 50% OFF"):
    response = creator.post("/api/drafts", json={"title": title, "text": text})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_approval_is_transactional_audited_and_not_published():
    creator, reviewer = client("creator"), client("reviewer")
    draft_id = make_draft(creator)
    version = creator.get(f"/api/drafts/{draft_id}").json()["versions"][-1]
    url = f"/api/drafts/{draft_id}/decision"

    without_comment = reviewer.post(url, json={"decision": "approve", "expected_version": version["n"]})
    assert without_comment.status_code == 400
    decision = reviewer.post(url, json={"decision": "approve", "comment": "Offer needs correction before release.",
                                        "expected_version": version["n"]})
    assert decision.status_code == 200
    result = decision.json()
    assert result["status"] == "Ready to publish"  # legacy API status retained
    assert result["review_decision"] == "Approved by reviewer" and result["published"] is False
    assert result["reviewer"] == "Ravi" and result["reviewed_version"] == version["n"] and result["reviewed_at"]

    detail = reviewer.get(f"/api/drafts/{draft_id}").json()
    assert detail["status"] == "Ready to publish" and detail["review"]["published"] is False
    assert detail["review"]["reviewer"] == "Ravi" and detail["review"]["version"] == version["n"]
    assert detail["comments"][-1]["text"] == "Offer needs correction before release."
    audit = reviewer.get("/api/audit").json()
    event = next(row for row in audit if row["action"] == "draft approved by reviewer")
    assert event["actor"] == "Ravi" and event["role"] == "reviewer"
    assert f"version {version['n']}" in event["detail"] and event["at"] == result["reviewed_at"]

    duplicate_decision = reviewer.post(url, json={"decision": "return", "comment": "Second vote"})
    assert duplicate_decision.status_code == 409
    assert sum(row["action"] == "draft approved by reviewer" for row in reviewer.get("/api/audit").json()) == 1


def test_return_resubmit_preserves_history_and_duplicate_request_is_idempotent():
    creator, reviewer = client("creator"), client("reviewer")
    draft_id = make_draft(creator, text="Original copy")
    returned = reviewer.post(f"/api/drafts/{draft_id}/decision", json={"decision": "return", "comment": "Please revise the claim.", "expected_version": 1})
    assert returned.status_code == 200 and returned.json()["status"] == "Returned"
    assert returned.json()["review_decision"] == "Returned to creator" and returned.json()["published"] is False

    request_id = "9f7b3004-7653-4a80-9adc-3244fd34e8af"
    payload = {"text": "Revised copy", "expected_version": 1, "request_id": request_id}
    first = creator.post(f"/api/drafts/{draft_id}/resubmit", json=payload)
    assert first.status_code == 200 and first.json() == {"version": 2, "duplicate": False}
    second = creator.post(f"/api/drafts/{draft_id}/resubmit", json=payload)
    assert second.status_code == 200 and second.json() == {"version": 2, "duplicate": True}

    detail = creator.get(f"/api/drafts/{draft_id}").json()
    assert [version["n"] for version in detail["versions"]] == [1, 2]
    assert [version["content"] for version in detail["versions"]] == ["Original copy", "Revised copy"]
    assert detail["status"] == "Pending review" and detail["review"]["decision"] is None
    events = [row for row in reviewer.get("/api/audit").json() if f"draft {draft_id}" in row["detail"]]
    assert any(row["action"] == "draft returned by reviewer" for row in events)
    assert any(row["action"] == "version 2 checked" for row in events)


def test_duplicate_create_request_returns_the_original_draft():
    creator = client("creator")
    request_id = "436da93c-0d33-4cd7-8abc-b107bb1f4017"
    body = {"title": "Retry-safe create", "text": "One submission", "request_id": request_id}
    first = creator.post("/api/drafts", json=body)
    second = creator.post("/api/drafts", json=body)
    assert first.status_code == second.status_code == 200
    assert second.json() == {"id": first.json()["id"], "duplicate": True}
    detail = creator.get(f"/api/drafts/{first.json()['id']}").json()
    assert len(detail["versions"]) == 1


def test_pending_and_stale_draft_versions_cannot_be_resubmitted_or_decided():
    creator, reviewer = client("creator"), client("reviewer")
    draft_id = make_draft(creator, text="Original copy")
    url = f"/api/drafts/{draft_id}/resubmit"
    pending = creator.post(url, json={"text": "Too early", "expected_version": 1})
    assert pending.status_code == 409

    assert reviewer.post(f"/api/drafts/{draft_id}/decision", json={"decision": "return", "comment": "Revise."}).status_code == 200
    stale = creator.post(url, json={"text": "Stale edit", "expected_version": 0})
    assert stale.status_code == 409 and "changed" in stale.json()["detail"]
    resubmitted = creator.post(url, json={"text": "Version two", "expected_version": 1})
    assert resubmitted.status_code == 200 and resubmitted.json()["version"] == 2
    stale_decision = reviewer.post(f"/api/drafts/{draft_id}/decision", json={"decision": "approve", "comment": "Review", "expected_version": 1})
    assert stale_decision.status_code == 409
    current_decision = reviewer.post(f"/api/drafts/{draft_id}/decision", json={"decision": "approve", "comment": "Reviewed v2", "expected_version": 2})
    assert current_decision.status_code == 200 and current_decision.json()["reviewed_version"] == 2


def test_permissions_block_unauthorized_decisions_and_cross_creator_resubmits():
    creator = client("creator")
    draft_id = make_draft(creator)
    assert creator.post(f"/api/drafts/{draft_id}/decision", json={"decision": "return", "comment": "No"}).status_code == 403

    a.q("INSERT INTO users(username,name,role,salt,pwd_hash) VALUES('bea','Bea','creator',?,?)",
        ("11" * 16, a.hash_pw("Bea@12345", bytes.fromhex("11" * 16))))
    other = TestClient(a.app)
    assert other.post("/api/login", json={"username": "bea", "password": "Bea@12345", "role": "creator"}).status_code == 200
    assert other.post(f"/api/drafts/{draft_id}/resubmit", json={"text": "Not mine"}).status_code == 403
    assert other.get(f"/api/drafts/{draft_id}").status_code == 403


def test_failed_version_write_rolls_back_draft_and_audit(monkeypatch):
    creator = client("creator")
    before = len(a.q("SELECT id FROM drafts"))

    def fail_write(*args, **kwargs):
        raise sqlite3.OperationalError("simulated write failure")

    monkeypatch.setattr(a, "save_version", fail_write)
    response = creator.post("/api/drafts", json={"title": "Must roll back", "text": "Copy"})
    assert response.status_code == 503
    assert len(a.q("SELECT id FROM drafts")) == before
    assert not any("Must roll back" in row["detail"] for row in a.q("SELECT detail FROM audit"))


def test_failed_decision_audit_rolls_back_status_and_comment(monkeypatch):
    creator, reviewer = client("creator"), client("reviewer")
    draft_id = make_draft(creator)

    def fail_audit(*args, **kwargs):
        raise sqlite3.OperationalError("simulated audit failure")

    monkeypatch.setattr(a, "audit_insert", fail_audit)
    response = reviewer.post(f"/api/drafts/{draft_id}/decision", json={"decision": "return", "comment": "Please revise.", "expected_version": 1})
    assert response.status_code == 503
    draft = creator.get(f"/api/drafts/{draft_id}").json()
    assert draft["status"] == "Pending review" and draft["comments"] == []
    assert draft["review"]["decision"] is None


def test_legacy_workflow_tables_get_additive_metadata_migration(tmp_path, monkeypatch):
    database = tmp_path / "legacy-workflow.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE drafts(id INTEGER PRIMARY KEY, title TEXT, creator TEXT, status TEXT, created TEXT)")
    connection.execute("CREATE TABLE versions(id INTEGER PRIMARY KEY, draft_id INT, n INT, content TEXT, filename TEXT, issues TEXT, author TEXT, at TEXT)")
    connection.commit(); connection.close()
    monkeypatch.setattr(a, "DB", str(database))
    a.init()
    connection = sqlite3.connect(database)
    draft_columns = {row[1] for row in connection.execute("PRAGMA table_info(drafts)")}
    version_columns = {row[1] for row in connection.execute("PRAGMA table_info(versions)")}
    indexes = {row[1] for row in connection.execute("PRAGMA index_list(versions)")}
    connection.close()
    assert {"review_decision", "reviewer", "reviewed_at", "reviewed_version"} <= draft_columns
    assert {"image_checks", "request_id"} <= version_columns
    assert "idx_versions_request_id" in indexes
