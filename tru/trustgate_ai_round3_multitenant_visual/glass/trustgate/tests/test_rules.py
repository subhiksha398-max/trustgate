import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import rules

F = [dict(kind="discount", subject="all items", value="15", valid_from="2026-01-01", valid_to="2026-12-31", source="Promo Policy v2"),
     dict(kind="warranty", subject="x", value="12", valid_from="", valid_to="", source="Warranty Record"),
     dict(kind="term", subject="Solara Pro Max", value="SolaraMax", valid_from="", valid_to="", source="Naming Guide")]
T = "2026-06-01"

def test_wrong_discount_and_warranty():
    s = "SOLARA FLAT 50% OFF. LIFETIME WARRANTY"
    r = rules.check(s, F, T)
    assert [i["type"] for i in r] == ["Discount mismatch", "Warranty unsupported"]
    assert rules.apply_fixes(s, r) == "SOLARA FLAT 15% OFF. 1-year warranty"

def test_correct_discount_passes():
    assert rules.check("Save 15% today with a 1-year warranty", F, T) == []

def test_expired_offer():
    assert rules.check("Save 15% now", F, "2027-02-01")[0]["type"] == "Offer not valid today"

def test_terminology_and_unsupported_claim():
    r = rules.check("The Solara Pro Max is guaranteed to last!!", F, T)
    assert {i["type"] for i in r} == {"Naming drift", "Unsupported claim", "Tone keyword"}
    assert [i for i in r if i["type"] == "Unsupported claim"][0]["status"] == "needs_review"

def test_image_size_check():
    from PIL import Image; import io
    b = io.BytesIO(); Image.new("RGB", (100, 100), "white").save(b, "PNG")
    assert rules.check_image(b.getvalue(), F)[0]["type"] == "Image too small"

def make_image(color, size=(800, 400), fmt="PNG"):
    from PIL import Image
    import io
    output = io.BytesIO(); Image.new("RGB", size, color).save(output, fmt)
    return output.getvalue()

def test_valid_image_reports_bounded_decode_and_brand_colour_pass():
    facts = [dict(kind="color", subject="primary", value="#0B5FFF", id=41, version=2, source="Brand Kit")]
    findings, checks, info = rules.inspect_image(make_image("#0B5FFF"), facts)
    assert findings == []
    assert info == {"format": "PNG", "width": 800, "height": 400, "pixels": 320000}
    assert next(item for item in checks if item["name"] == "Brand colours")["status"] == "passed"
    assert next(item for item in checks if item["name"] == "Logo presence")["status"] == "unavailable"

def test_image_rejects_malformed_and_non_image_data():
    import pytest
    with pytest.raises(rules.ImageValidationError):
        rules.inspect_image(b"not an image", F)

def test_image_rejects_oversized_bytes_and_decoded_pixel_count(monkeypatch):
    import pytest
    data = make_image("white")
    monkeypatch.setattr(rules, "MAX_IMAGE_BYTES", len(data) - 1)
    with pytest.raises(rules.ImageTooLargeError):
        rules.inspect_image(data, F)
    monkeypatch.setattr(rules, "MAX_IMAGE_BYTES", 10 * 1024 * 1024)
    large = make_image("white", size=(4000, 4000))
    with pytest.raises(rules.ImageTooLargeError):
        rules.inspect_image(large, F)

def test_image_reports_undersized_dimensions_without_claiming_compliance():
    findings, checks, _ = rules.inspect_image(make_image("#0B5FFF", size=(400, 200)), F)
    assert findings[0]["type"] == "Image too small"
    assert findings[0]["classification"] == rules.MISMATCH
    dimension = next(item for item in checks if item["name"] == "Dimensions")
    assert dimension["status"] == "review" and "600 x 315" in dimension["detail"]

def test_sampled_colour_mismatch_is_review_only_with_palette_evidence():
    fact = dict(kind="color", subject="primary", value="#0B5FFF", id=42, version=3,
                source="Brand Kit", source_quote="Primary brand blue #0B5FFF")
    findings, checks, _ = rules.inspect_image(make_image("#111111"), [fact])
    mismatch = next(item for item in findings if item["type"] == "Colour differs from sampled brand palette")
    assert mismatch["classification"] == rules.HUMAN_REVIEW and mismatch["status"] == "needs_review"
    assert mismatch["evidence"][0]["fact_id"] == 42
    assert next(item for item in checks if item["name"] == "Brand colours")["status"] == "review"

def test_missing_or_invalid_brand_palette_is_reported_as_unavailable():
    _, checks, _ = rules.inspect_image(make_image("#0B5FFF"), [])
    assert next(item for item in checks if item["name"] == "Brand colours")["status"] == "unavailable"
    invalid = [dict(kind="color", subject="primary", value="blue")]
    findings, checks, _ = rules.inspect_image(make_image("#0B5FFF"), invalid)
    assert any(item["type"] == "Brand palette unavailable" for item in findings)
    assert next(item for item in checks if item["name"] == "Brand colours")["status"] == "review"


import pytest

@pytest.mark.parametrize("text, phrase", [
    ("Grab it at half price today", "half price"), ("Half-price weekend", "Half-price"), ("Get half off everything", "Get half off"),
    ("Fifty percent off all items", "Fifty percent off"), ("Save twenty-five per cent now", "Save twenty-five per cent"),
    ("A third off this week", "A third off"), ("Flat 50 percent discount", "Flat 50 percent discount")])
def test_discount_phrasings_are_caught_without_ai(text, phrase):
    r = rules.check(text, F, T)
    assert [i["type"] for i in r] == ["Discount mismatch"] and r[0]["phrase"] == phrase and "15" in r[0]["suggestion"]

def test_correct_discount_in_words_passes():
    assert rules.check("Save fifteen percent today", F, T) == []

@pytest.mark.parametrize("text, phrase", [
    ("Warranty for life", "Warranty for life"), ("A lifetime warranty", "lifetime warranty"), ("a lifelong guarantee", "lifelong guarantee"),
    ("Warranty that lasts forever", "Warranty that lasts forever"), ("The warranty never expires", "warranty never expires"),
    ("Includes a two-year warranty", "two-year warranty"), ("Warranty of 5 years", "Warranty of 5 years"), ("a 24 month guarantee", "24 month guarantee")])
def test_warranty_phrasings_are_caught_without_ai(text, phrase):
    r = rules.check(text, F, T)
    assert [i["type"] for i in r] == ["Warranty unsupported"] and r[0]["phrase"] == phrase and r[0]["status"] == "issue"

def test_matching_warranty_in_words_passes():
    assert rules.check("Backed by a twelve month warranty", F, T) == []

def test_loose_nouns_are_review_only_never_auto_fixed():
    s = "Enjoy protection for life"; r = rules.check(s, F, T)
    assert r[0]["status"] == "needs_review" and rules.apply_fixes(s, r) == s

def test_multi_buy_offer_needs_review():
    r = rules.check("Buy one get one free!", F, T)
    assert r[0]["type"] == "No approved offer" and r[0]["status"] == "needs_review"

def test_no_false_alarm_on_ordinary_percent_or_warranty_words():
    assert rules.check("Made with 100% recycled paper. Read the warranty terms.", F, T) == []

def test_verified_discount_has_exact_fact_snapshot():
    fact = {**F[0], "id": 11, "version": 3, "source_quote": "15% off all items in 2026", "source_document_id": 8}
    found = rules.check("Save 15% today", [fact], T, include_verified=True)
    assert len(found) == 1
    issue = found[0]
    assert issue["classification"] == rules.VERIFIED and issue["status"] == "verified"
    assert issue["fact_id"] == 11 and issue["fact_version"] == 3
    assert issue["source_document_id"] == 8 and issue["source_quote"] == fact["source_quote"]
    assert issue["valid_from"] == "2026-01-01" and issue["valid_to"] == "2026-12-31"

def test_discount_mismatch_has_evidence_and_explicit_classification():
    fact = {**F[0], "id": 12, "version": 2, "source_quote": "Approved promotion is 15 percent"}
    issue = rules.check("Flat 50% off", [fact], T)[0]
    assert issue["classification"] == rules.MISMATCH
    assert issue["fact_id"] == 12 and issue["fact_version"] == 2
    assert issue["evidence"][0]["value"] == "15" and issue["source_quote"] == fact["source_quote"]

def test_unapproved_discount_is_unsupported_not_proven_false():
    issue = rules.check("Save 15% today", [], T)[0]
    assert issue["classification"] == rules.UNSUPPORTED
    assert issue["status"] == "needs_review" and "fact_id" not in issue
    assert "does not prove" in issue["reason"] and issue["source"] == "-"

def test_expired_discount_cites_expired_fact_dates():
    fact = {**F[0], "id": 13, "valid_from": "2025-01-01", "valid_to": "2025-12-31", "source_quote": "15% off in 2025"}
    issue = rules.check("Save 15% today", [fact], T)[0]
    assert issue["type"] == "Offer not valid today"
    assert issue["classification"] == rules.MISMATCH and issue["fact_id"] == 13
    assert issue["valid_to"] == "2025-12-31" and issue["source_quote"] == fact["source_quote"]

@pytest.mark.parametrize("text", ["Grab it at half price", "Get fifty percent off today"])
def test_paraphrased_discount_mismatch_is_evidence_backed(text):
    fact = {**F[0], "id": 14, "source_quote": "15% off all items"}
    issue = rules.check(text, [fact], T)[0]
    assert issue["classification"] == rules.MISMATCH and issue["fact_id"] == 14

def test_paraphrased_warranty_mismatch_uses_human_review_conservatively():
    fact = {**F[1], "id": 15, "version": 4, "source_quote": "12-month limited warranty"}
    issue = rules.check("Enjoy protection for life", [fact], T)[0]
    assert issue["classification"] == rules.HUMAN_REVIEW and issue["status"] == "needs_review"
    assert issue["fact_id"] == 15 and issue["fact_version"] == 4

def test_price_mismatch_and_unrecorded_price_are_distinguished():
    fact = dict(kind="price", subject="SolaraPhone", value="24999", source="Price List", id=16,
                version=2, source_quote="SolaraPhone price Rs 24,999")
    mismatch = rules.check("SolaraPhone price Rs 25,000", [fact], T)[0]
    assert mismatch["classification"] == rules.MISMATCH and mismatch["fact_id"] == 16
    unsupported = rules.check("Widget price Rs 25,000", [fact], T)[0]
    assert unsupported["classification"] == rules.UNSUPPORTED and "does not prove" in unsupported["reason"]

def test_conflicting_current_discounts_require_human_review():
    facts = [{**F[0], "id": 21, "source_quote": "15 percent offer"},
             {**F[0], "id": 22, "value": "20", "source": "Updated offer", "source_quote": "20 percent offer"}]
    issue = rules.check("Save 50% today", facts, T)[0]
    assert issue["classification"] == rules.HUMAN_REVIEW and issue["status"] == "needs_review"
    assert issue["type"] == "Conflicting approved facts"
    assert {e["fact_id"] for e in issue["evidence"]} == {21, 22}
    assert issue["suggestion"] is None

def test_conflicting_current_prices_require_human_review():
    facts = [dict(kind="price", subject="SolaraPhone", value="24999", source="Price List", id=31),
             dict(kind="price", subject="SolaraPhone", value="23999", source="Promo Price", id=32)]
    issue = rules.check("SolaraPhone price Rs 25,000", facts, T)[0]
    assert issue["classification"] == rules.HUMAN_REVIEW
    assert {e["fact_id"] for e in issue["evidence"]} == {31, 32}

def test_pdf_text_is_read():
    assert rules._pdf_text(_make_pdf("Flat 50% off")) .startswith("Flat 50% off")

def _make_pdf(line):
    """Smallest valid one-page PDF containing a line of text."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    stream = f"BT /F1 18 Tf 20 100 Td ({line}) Tj ET"
    objs[3] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
    out = b"%PDF-1.4\n"; offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out); out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs: out += f"{o:010d} 00000 n \n".encode()
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF".encode()


def test_html_accessibility_flags_missing_alt_text_for_human_review():
    html = '<main><img src="hero.jpg"><p>Welcome</p></main>'
    issues = rules.check(html, [], T)
    issue = next(item for item in issues if item["type"] == "Image missing alternative text")
    assert issue["phrase"] == '<img src="hero.jpg">'
    assert issue["classification"] == rules.HUMAN_REVIEW
    assert issue["status"] == "needs_review"
    assert issue["suggestion"] is None


def test_html_accessibility_checks_inline_wcag_contrast_conservatively():
    html = '<p style="color:#aaaaaa;background-color:#ffffff">Low contrast</p>'
    issues = rules.check(html, [], T)
    issue = next(item for item in issues if item["type"] == "Possible low text contrast")
    assert issue["classification"] == rules.HUMAN_REVIEW
    assert "4.5:1" in issue["approved"]


def test_html_accessibility_does_not_flag_good_inline_contrast():
    html = '<p style="color:#000000;background-color:#ffffff">Readable</p>'
    assert not any(item["type"] == "Possible low text contrast" for item in rules.check(html, [], T))


def test_skipped_heading_level_is_a_review_prompt():
    html = '<main><h1>Title</h1><h3>Section</h3></main>'
    issue = next(item for item in rules.check(html, [], T) if item["type"] == "Heading level skipped")
    assert issue["classification"] == rules.HUMAN_REVIEW
    assert issue["status"] == "needs_review"


def test_promotional_superlative_is_review_only_not_claimed_false():
    issue = next(item for item in rules.check("Our revolutionary product is here", [], T)
                 if item["type"] == "Promotional superlative")
    assert issue["status"] == "needs_review"
    assert issue["classification"] == rules.HUMAN_REVIEW
    assert issue["suggestion"] is None
