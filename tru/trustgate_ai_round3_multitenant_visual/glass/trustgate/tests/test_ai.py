import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ["TRUSTGATE_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
import ai, rules

F = [dict(kind="discount", subject="all items", value="15", valid_from="2026-01-01", valid_to="2026-12-31", source="Promo Policy v2"),
     dict(kind="warranty", subject="Solara products", value="12", valid_from="", valid_to="", source="Warranty Record")]
T = "2026-06-01"

def fake(reply):
    return lambda system, user, max_tokens=1500: reply

def test_ai_catches_paraphrase_the_rules_miss(monkeypatch):
    text = "Our cheapest deal ever, and nobody beats our quality."
    assert rules.check(text, F, T) == []          # regex rules see nothing
    reply = json.dumps({"findings": [
        {"phrase": "cheapest deal ever", "kind": "offer", "reason": "No approved offer says this.", "approved": "none on record", "source": "Promo Policy v2", "suggestion": "15% off"},
        {"phrase": "nobody beats our quality", "kind": "claim", "reason": "Unsupported superiority claim.", "approved": "none on record", "source": "", "suggestion": ""}]})
    monkeypatch.setattr(ai, "_call", fake(reply))
    r = ai.find_missed_claims(text, F, [], T)
    assert [i["phrase"] for i in r] == ["cheapest deal ever", "nobody beats our quality"]
    assert all(i["status"] == "needs_review" and i["by"] == "AI" for i in r)
    assert text[r[0]["start"]:r[0]["end"]] == "cheapest deal ever"
    assert rules.apply_fixes(text, r) == text      # AI findings are never auto-applied

def test_hallucinated_phrase_is_discarded(monkeypatch):
    reply = json.dumps({"findings": [{"phrase": "this text is not in the copy", "kind": "claim", "reason": "x"}]})
    monkeypatch.setattr(ai, "_call", fake(reply))
    assert ai.find_missed_claims("Save 15% today", F, [], T) == []

def test_overlap_with_rule_finding_is_skipped(monkeypatch):
    text = "FLAT 50% OFF"; existing = rules.check(text, F, T)
    reply = json.dumps({"findings": [{"phrase": "50% OFF", "kind": "offer", "reason": "dup"}]})
    monkeypatch.setattr(ai, "_call", fake(reply))
    assert ai.find_missed_claims(text, F, existing, T) == []

def test_unknown_source_becomes_dash_and_fenced_json_parses(monkeypatch):
    reply = "```json\n" + json.dumps({"findings": [{"phrase": "cheapest", "kind": "claim", "reason": "r", "source": "Made Up Doc"}]}) + "\n```"
    monkeypatch.setattr(ai, "_call", fake(reply))
    r = ai.find_missed_claims("The cheapest phone", F, [], T)
    assert r[0]["source"] == "-"

def login(c, user, pw, role):
    r = c.post("/api/login", json={"username": user, "password": pw, "role": role}); assert r.status_code == 200, r.text; return c

def test_api_end_to_end_with_ai_and_fallback(monkeypatch):
    from fastapi.testclient import TestClient
    import app as a
    c = login(TestClient(a.app), "asha", "Creator@123", "creator"); h = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(ai, "available", lambda: True)
    calls = []
    def reply(system, user, max_tokens=1500):
        calls.append(1)
        if "rewrite marketing copy" in system: return "Get 15% off with a 12-month warranty."
        return json.dumps({"findings": [{"phrase": "Cheapest deal ever", "kind": "offer", "reason": "Approved is 15%.", "approved": "15%", "source": "Promo Policy v2", "suggestion": "15% off"}]})
    monkeypatch.setattr(ai, "_call", reply)
    r = c.post("/api/drafts", json={"title": "t", "text": "Cheapest deal ever this week"}, headers=h); assert r.status_code == 200
    assert len(calls) == 1                         # new draft is checked once, not twice
    d = c.get(f"/api/drafts/{r.json()['id']}").json()
    ai_issue = d["versions"][0]["issues"][0]
    assert ai_issue["by"] == "AI" and ai_issue["classification"] == "Needs human review"
    assert ai_issue["source"] == "-" and ai_issue["approved"] == "Not independently verified against approved evidence"
    assert "fact_id" not in ai_issue
    rw = c.post(f"/api/drafts/{r.json()['id']}/ai-rewrite", headers=h); assert rw.json()["text"].startswith("Get 15%")
    rv = login(TestClient(a.app), "ravi", "Reviewer@123", "reviewer")
    assert rv.post(f"/api/drafts/{r.json()['id']}/ai-rewrite").status_code == 403
    def boom(*a, **k): raise RuntimeError("network down")
    monkeypatch.setattr(ai, "_call", boom)         # AI failure must not block the rules
    r2 = c.post("/api/drafts", json={"title": "t2", "text": "SOLARA FLAT 50% OFF. LIFETIME WARRANTY"}, headers=h); assert r2.status_code == 200
    assert len(c.get(f"/api/drafts/{r2.json()['id']}").json()["versions"][0]["issues"]) == 2

def test_status_endpoint_without_key(monkeypatch):
    from fastapi.testclient import TestClient
    import app as a
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = login(TestClient(a.app), "asha", "Creator@123", "creator")
    assert c.get("/api/ai/status").json() == {"enabled": False, "model": ""}


def test_verified_claim_is_saved_with_evidence_and_does_not_block_approval(monkeypatch):
    from fastapi.testclient import TestClient
    import app as a

    monkeypatch.setattr(ai, "available", lambda: False)
    creator = login(TestClient(a.app), "asha", "Creator@123", "creator")
    result = creator.post("/api/drafts", json={"title": "Verified offer", "text": "Save 15% today"})
    assert result.status_code == 200
    draft = creator.get(f"/api/drafts/{result.json()['id']}").json()
    finding = draft["versions"][0]["issues"][0]
    assert finding["classification"] == "Verified against approved evidence"
    assert finding["status"] == "verified" and finding["fact_id"]
    assert finding["source_document"] == "Promo Policy v2" and finding["fact_version"] == 1
    assert finding["valid_from"] == "2026-01-01" and finding["valid_to"] == "2026-12-31"
    assert finding["evidence"][0]["source_quote"] == ""
    assert creator.get("/api/drafts").json()[0]["open_issues"] == 0

    reviewer = login(TestClient(a.app), "ravi", "Reviewer@123", "reviewer")
    decision = reviewer.post(f"/api/drafts/{result.json()['id']}/decision", json={"decision": "approve", "comment": ""})
    assert decision.status_code == 200 and decision.json()["status"] == "Ready to publish"


def test_long_text_is_read_in_pieces_and_offsets_stay_correct(monkeypatch):
    text = ("Filler line about nothing at all.\n" * 400) + "Nobody beats our quality."   # longer than one AI call
    calls = []
    def reply(system, user, max_tokens=1500):
        calls.append(1)
        return json.dumps({"findings": [{"phrase": "Nobody beats our quality", "kind": "claim", "reason": "r"}]}) if "Nobody beats" in user else json.dumps({"findings": []})
    monkeypatch.setattr(ai, "_call", reply)
    r = ai.find_missed_claims(text, F, [], T)
    assert len(calls) > 1 and len(r) == 1 and text[r[0]["start"]:r[0]["end"]] == "Nobody beats our quality"

def test_read_image_text_sends_an_image_and_handles_no_text(monkeypatch):
    from PIL import Image; import io
    b = io.BytesIO(); Image.new("RGBA", (800, 400), (255, 255, 255, 0)).save(b, "PNG")
    seen = {}
    def reply(system, user, max_tokens=1500):
        seen["user"] = user; return "SOLARA FLAT 50% OFF\nHalf price today"
    monkeypatch.setattr(ai, "_call", reply)
    assert ai.read_image_text(b.getvalue()).startswith("SOLARA FLAT 50% OFF")
    assert seen["user"][0]["type"] == "image" and seen["user"][0]["source"]["media_type"] in ("image/png", "image/jpeg")
    monkeypatch.setattr(ai, "_call", fake("NO_TEXT"))
    assert ai.read_image_text(b.getvalue()) == ""


def test_batched_benchmark_ai_validates_sample_id_and_quote(monkeypatch):
    import benchmark
    sample = benchmark.SAMPLES[20]
    reply = json.dumps({"findings": [
        {"sample_id": sample["id"], "phrase": "cheapest deal", "kind": "offer"},
        {"sample_id": sample["id"], "phrase": "cheapest deal", "kind": "invented-kind"},
        {"sample_id": sample["id"], "phrase": "invented quote", "kind": "offer"},
        {"sample_id": "unknown", "phrase": "cheapest deal", "kind": "offer"}]})
    monkeypatch.setattr(ai, "_call", fake(reply))
    predictions = [rules.check(sample["text"], sample["facts"], benchmark.TODAY)]
    found = ai.find_benchmark_claims([sample], predictions, benchmark.TODAY)
    assert len(found) == 1 and found[0][0]["phrase"] == "cheapest deal"
    assert found[0][0]["category"] == "Offer mismatches"


def test_benchmark_metrics_and_reviewer_feedback_flow(monkeypatch):
    import benchmark
    from fastapi.testclient import TestClient
    import app as a

    monkeypatch.setattr(ai, "available", lambda: False)
    creator = login(TestClient(a.app), "asha", "Creator@123", "creator")
    draft_id = creator.post("/api/drafts", json={"title": "Feedback test", "text": "SOLARA FLAT 50% OFF"}).json()["id"]
    version = creator.get(f"/api/drafts/{draft_id}").json()["versions"][0]
    assert creator.post(f"/api/drafts/{draft_id}/feedback", json={"version_id": version["id"], "finding_index": 0, "verdict": "false_alarm"}).status_code == 403

    reviewer = login(TestClient(a.app), "ravi", "Reviewer@123", "reviewer")
    mark = {"version_id": version["id"], "finding_index": 0, "verdict": "false_alarm"}
    assert reviewer.post(f"/api/drafts/{draft_id}/feedback", json=mark).status_code == 200
    marked = reviewer.get(f"/api/drafts/{draft_id}").json()["versions"][0]["issues"][0]["feedback"]
    assert marked["verdict"] == "false_alarm" and marked["reviewer"] == "Ravi"
    clarity = reviewer.get("/api/analytics").json()["guideline_clarity"]
    assert any(row["name"] == "Promo Policy v2" and row["false_alarms"] == 1 for row in clarity)
    mark["verdict"] = "correct"
    assert reviewer.post(f"/api/drafts/{draft_id}/feedback", json=mark).status_code == 200
    clarity = reviewer.get("/api/analytics").json()["guideline_clarity"]
    assert next(row for row in clarity if row["name"] == "Promo Policy v2")["votes"] == 1

    result = reviewer.post("/api/benchmark/run").json()
    assert result["samples"] == 140 and result["dataset_version"] == "1.1.0"
    assert result["rules"]["precision"] == 100.0 and result["rules"]["recall"] == 65.0
    assert result["rules"]["f1"] == 78.8 and result["rules_ai"] is None
    assert result["configuration"]["ai"] == "unavailable"
    latest = reviewer.get("/api/analytics").json()["benchmark"]
    assert latest["id"] == result["id"] and latest["rules"]["labelled_findings"] == 80

    monkeypatch.setattr(ai, "available", lambda: True)
    calls = []
    def no_ai_findings(system, user, max_tokens=1500):
        calls.append(1)
        return '{"findings": []}'
    monkeypatch.setattr(ai, "_call", no_ai_findings)
    compared = reviewer.post("/api/benchmark/run").json()
    assert len(calls) == 14 and compared["ai_enabled"] is True
    assert compared["rules_ai"] == compared["rules"]
