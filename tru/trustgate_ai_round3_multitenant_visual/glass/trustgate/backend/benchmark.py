"""Frozen fictional drafts and independent labels for reproducible checker evaluation."""
import argparse
import json

TODAY = "2026-06-01"
DATASET_VERSION = "1.1.0"
OFFER = [dict(kind="discount", subject="all items", value="15", valid_from="2026-01-01",
              valid_to="2026-12-31", source="Promo Policy v2")]
WARRANTY = [dict(kind="warranty", subject="Solara products", value="12", valid_from="",
                 valid_to="", source="Product Warranty Record")]
EXPIRED_OFFER = [dict(kind="discount", subject="all items", value="15", valid_from="2025-01-01",
                      valid_to="2025-12-31", source="Archived Promo Policy")]
SUPPORTED_CLAIM = [dict(kind="claim", subject="clinically proven", value="clinically proven",
                        valid_from="", valid_to="", source="Clinical Study")]
PHONE_PRICE = [dict(kind="price", subject="SolaraPhone", value="24999", valid_from="", valid_to="",
                    source="Price List 2026")]
TERMS = [dict(kind="banned", subject="miracle", value="", valid_from="", valid_to="", source="Claims Policy"),
         dict(kind="term", subject="Solara Pro Max", value="SolaraMax", valid_from="", valid_to="", source="Naming Guide"),
         dict(kind="tone", subject="cheap", value="affordable", valid_from="", valid_to="", source="Tone Guide")]

GROUPS = [
    ("Wrong offer figures", OFFER, "Offer mismatches", [
        "Solara: flat 50% off today.", "Save 40 percent on every Solara item.",
        "Take 30% off the full range.", "Get 25 percent off your order.",
        "Flat 60% discount on Solara products.", "Enjoy 35% off this weekend.",
        "All Solara items are now 20% off.", "Save 45 percent with this offer.",
        "Get 55% off selected products.", "A 10 percent discount on Solara today."]),
    ("Warranty mismatches", WARRANTY, "Unsupported claims", [
        "Solara products include a 5-year warranty.", "Backed by a 24-month warranty.",
        "Enjoy a lifetime warranty on every Solara product.", "Includes a 2 year guarantee.",
        "Our warranty lasts for life.", "Covered by a 6-month warranty.",
        "Every device comes with a 3-year warranty.", "Protection that never expires.",
        "A ten-year guarantee is included.", "Your Solara purchase has a 36 month warranty."]),
    ("Unapproved offer paraphrases", OFFER, "Offer mismatches", [
        "This is the cheapest deal Solara has ever offered.", "Nobody beats this price on Solara products.",
        "Get the lowest price of the year on every item.", "A once-in-a-lifetime bargain across the range.",
        "Pay just a fraction of the usual price today.", "The best deal in the market is here.",
        "Our prices are unbeatable this weekend.", "Shop now for an incredible bargain.",
        "This is the biggest saving you will find anywhere.", "Everything is practically free today."]),
    ("Unsupported performance claims", [], "Unsupported claims", [
        "Solara is clinically proven to improve your life.", "The world's best device is here.",
        "Guaranteed results from the first day.", "Our product is number one for every customer.",
        "100% effective for all users.", "The only device you will ever need.",
        "Proven to work better than every competitor.", "Everyone agrees this is the best choice.",
        "A miracle product for your home.", "Nothing else comes close to our performance."]),
    ("Expired offer dates", EXPIRED_OFFER, "Offer mismatches", [
        "Save 15% on all Solara items.", "Get 15 percent off today.",
        "Enjoy a 15% discount this weekend.", "All products are 15% off now.",
        "Take fifteen percent off your order.", "Flat 15 percent off the whole range.",
        "Shop Solara and save 15% today.", "A 15% saving on every item.",
        "Get a fifteen percent discount now.", "Save 15 percent on Solara products."]),
    ("Correct offer wording", OFFER, None, [
        "Solara: flat 15% off today.", "Save 15 percent on every Solara item.",
        "Take 15% off the full range.", "Get fifteen percent off your order.",
        "Flat 15% discount on Solara products.", "Enjoy 15% off this weekend.",
        "All Solara items are now 15% off.", "Save fifteen percent with this offer.",
        "Get 15% off selected products.", "A 15 percent discount on Solara today."]),
    ("Correct warranty wording", WARRANTY, None, [
        "Solara products include a 1-year warranty.", "Backed by a 12-month warranty.",
        "Enjoy a twelve month warranty on every product.", "Includes a 1 year guarantee.",
        "Our warranty lasts for one year.", "Covered by a 12-month warranty.",
        "Every device comes with a one-year warranty.", "A 12 month guarantee is included.",
        "Your purchase has a 1-year warranty.", "Solara products are backed for 12 months."]),
    ("Supported claim wording", SUPPORTED_CLAIM, None, [
        "A clinical study found positive results.", "Research supports this product's performance.",
        "Read the published study for details.", "Our team tested this product in a study.",
        "See the clinical study on our website.", "Results are described in the attached report.",
        "This product was evaluated by researchers.", "Study findings are available on request.",
        "Learn more about the evidence behind this product.", "Independent research examined the product."]),
    ("Harmless percentages and terms", [], None, [
        "Made with 100% recycled paper.", "Read the warranty terms before purchase.",
        "The page is 50% complete.", "A 100 percent cotton cover is included.",
        "Warranty information is available online.", "The design uses 15% recycled material.",
        "Find the percentage in the product specifications.", "This report explains the warranty process.",
        "The 50% mark is shown on the chart.", "See the terms and conditions for details."]),
    ("Valid offer dates", OFFER, None, [
        "Save 15% today.", "Get 15 percent off this week.",
        "Enjoy a 15% discount before year end.", "All products are 15% off now.",
        "Take fifteen percent off your order.", "Flat 15 percent off the whole range.",
        "Shop Solara and save 15% today.", "A 15% saving on every item.",
        "Get a fifteen percent discount now.", "Save 15 percent on Solara products."]),
    ("Incorrect prices", PHONE_PRICE, "Offer mismatches", [
        "SolaraPhone price: Rs 25,000.", "SolaraPhone costs $250.00.",
        "The price of SolaraPhone is Rs 24,500.", "Buy SolaraPhone for ₹26,000.",
        "SolaraPhone now costs Rs 23,999.", "Get SolaraPhone at $240.",
        "SolaraPhone is priced at ₹25,500.", "Pay just Rs 25,100 for SolaraPhone.",
        "SolaraPhone price Rs 22,999 today.", "SolaraPhone costs Rs 30,000."]),
    ("Correct prices", PHONE_PRICE, None, [
        "SolaraPhone price: Rs 24,999.", "SolaraPhone costs ₹24,999.",
        "The price of SolaraPhone is Rs 24,999.", "Buy SolaraPhone for $24,999.",
        "SolaraPhone now costs Rs 24,999.", "Get SolaraPhone at ₹24,999.",
        "SolaraPhone is priced at Rs 24,999.", "Pay just Rs 24,999 for SolaraPhone.",
        "SolaraPhone price ₹24,999 today.", "SolaraPhone costs Rs 24,999."]),
    ("Terminology violations", TERMS, "Tone / naming", [
        "This is a miracle solution.", "Meet the Solara Pro Max.", "Choose the cheap plan.",
        "Our miracle formula is here.", "The Solara Pro Max is ready.", "A cheap way to get started.",
        "Discover this miracle product.", "Introducing Solara Pro Max today.", "Get a cheap upgrade.",
        "The miracle device for your home."]),
    ("Ambiguous claims for review", [], "Unsupported claims", [
        "A favorite among everyone who tries it.", "Customers say it changes everything.",
        "The choice that makes every day better.", "A remarkable difference for your routine.",
        "The product people cannot stop talking about.", "An experience unlike anything else.",
        "Designed to make life feel effortless.", "A new standard for everyday comfort.",
        "The upgrade you have been waiting for.", "A product that speaks for itself."]),
]

EXPECTED_CLASSIFICATION = {
    "Wrong offer figures": "Mismatch with approved information",
    "Warranty mismatches": "Mismatch with approved information",
    "Unapproved offer paraphrases": "Needs human review",
    "Unsupported performance claims": "Unsupported claim",
    "Expired offer dates": "Mismatch with approved information",
    "Correct offer wording": "Verified against approved evidence",
    "Correct warranty wording": "Verified against approved evidence",
    "Supported claim wording": "Verified against approved evidence",
    "Harmless percentages and terms": "Verified against approved evidence",
    "Valid offer dates": "Verified against approved evidence",
    "Incorrect prices": "Mismatch with approved information",
    "Correct prices": "Verified against approved evidence",
    "Terminology violations": "Mismatch with approved information",
    "Ambiguous claims for review": "Needs human review",
}
NO_FINDING_EXPECTED = "No finding expected"

SAMPLES = [
    {"id": f"TG-{group_index:02d}-{sample_index:02d}", "title": title,
     "text": text, "facts": facts, "expected": [expected] if expected else [],
     "expected_result": "finding" if expected else "no_finding",
    "expected_classification": EXPECTED_CLASSIFICATION[title] if expected else NO_FINDING_EXPECTED}
    for group_index, (title, facts, expected, examples) in enumerate(GROUPS, 1)
    for sample_index, text in enumerate(examples, 1)
]


ISSUE_CATEGORIES = {group[2] for group in GROUPS if group[2]}


def validate_dataset(samples=SAMPLES):
    """Reject malformed or ambiguous fixtures before running any checker."""
    if not isinstance(samples, list) or not samples:
        raise ValueError("Benchmark dataset must be a non-empty list.")
    seen = set()
    for index, sample in enumerate(samples):
        where = f"record {index}"
        if not isinstance(sample, dict):
            raise ValueError(f"{where} must be an object.")
        sample_id = sample.get("id")
        if not isinstance(sample_id, str) or not sample_id.strip():
            raise ValueError(f"{where} has no valid id.")
        if sample_id in seen:
            raise ValueError(f"Duplicate benchmark id: {sample_id}.")
        seen.add(sample_id)
        if not isinstance(sample.get("title"), str) or not sample["title"].strip():
            raise ValueError(f"{sample_id} has no title.")
        if not isinstance(sample.get("text"), str) or not sample["text"].strip():
            raise ValueError(f"{sample_id} has no draft text.")
        if not isinstance(sample.get("facts"), list):
            raise ValueError(f"{sample_id} facts must be a list.")
        for fact in sample["facts"]:
            if not isinstance(fact, dict) or not isinstance(fact.get("kind"), str) or not isinstance(fact.get("subject"), str):
                raise ValueError(f"{sample_id} contains a malformed approved fact.")
        expected = sample.get("expected")
        if not isinstance(expected, list) or any(not isinstance(category, str) or category not in ISSUE_CATEGORIES for category in expected):
            raise ValueError(f"{sample_id} has malformed expected categories.")
        if len(expected) != len(set(expected)):
            raise ValueError(f"{sample_id} repeats an expected category; add distinct claim labels instead.")
        if sample.get("expected_result") not in ("finding", "no_finding"):
            raise ValueError(f"{sample_id} has an invalid expected result.")
        if (sample["expected_result"] == "finding") != bool(expected):
            raise ValueError(f"{sample_id} expected result conflicts with its labels.")
        if sample.get("expected_classification") not in (
                "Mismatch with approved information", "Unsupported claim", "Verified against approved evidence",
                "Needs human review", NO_FINDING_EXPECTED):
            raise ValueError(f"{sample_id} has an invalid expected classification.")
        if not expected and sample["expected_classification"] != NO_FINDING_EXPECTED:
            raise ValueError(f"{sample_id} has no findings but is labelled as a verified claim.")
        if expected and sample["expected_classification"] == NO_FINDING_EXPECTED:
            raise ValueError(f"{sample_id} has expected findings but is labelled as a no-finding case.")
    return samples


def _rates(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision * 100, 1), "recall": round(recall * 100, 1),
            "f1": round(f1 * 100, 1), "true_positives": tp, "false_positives": fp, "false_negatives": fn}


def score(predictions, samples=SAMPLES):
    """Calculate claim/finding-event and draft-level binary metrics, plus category errors."""
    validate_dataset(samples)
    if not isinstance(predictions, list) or len(predictions) != len(samples):
        raise ValueError("Prediction count must match the benchmark record count.")
    claim_tp = claim_fp = claim_fn = 0
    draft_tp = draft_fp = draft_fn = draft_tn = 0
    class_correct = class_errors = 0
    category_counts = {}
    for sample, found in zip(samples, predictions):
        if not isinstance(found, list):
            raise ValueError(f"Predictions for {sample['id']} must be a list.")
        for item in found:
            if not isinstance(item, dict) or not isinstance(item.get("category"), str) or not item["category"].strip():
                raise ValueError(f"Predictions for {sample['id']} contain a malformed finding.")
        remaining = list(sample["expected"])
        for item in found:
            category = item["category"]
            counts = category_counts.setdefault(category, {"true_positives": 0, "false_positives": 0,
                                                           "false_negatives": 0, "classification_errors": 0})
            if category in remaining:
                remaining.remove(category)
                claim_tp += 1; counts["true_positives"] += 1
                if item.get("classification") == sample["expected_classification"]:
                    class_correct += 1
                else:
                    class_errors += 1
                    counts["classification_errors"] += 1
            else:
                claim_fp += 1; counts["false_positives"] += 1
        claim_fn += len(remaining)
        for category in remaining:
            category_counts.setdefault(category, {"true_positives": 0, "false_positives": 0, "false_negatives": 0})["false_negatives"] += 1

        expected_draft = sample["expected_result"] == "finding"
        predicted_draft = bool(found)
        if expected_draft and predicted_draft:
            draft_tp += 1
        elif predicted_draft:
            draft_fp += 1
        elif expected_draft:
            draft_fn += 1
        else:
            draft_tn += 1

    claim = _rates(claim_tp, claim_fp, claim_fn)
    draft = _rates(draft_tp, draft_fp, draft_fn)
    draft["true_negatives"] = draft_tn
    draft["accuracy"] = round((draft_tp + draft_tn) / len(samples) * 100, 1) if samples else 0.0
    classification_evaluated = class_correct + class_errors
    classification = {"accuracy": round(class_correct / classification_evaluated * 100, 1) if classification_evaluated else 0.0,
                      "correct": class_correct, "errors": class_errors, "evaluated": classification_evaluated}
    by_category = []
    for category in sorted(set(ISSUE_CATEGORIES) | set(category_counts)):
        counts = category_counts.get(category, {"true_positives": 0, "false_positives": 0, "false_negatives": 0,
                                                 "classification_errors": 0})
        by_category.append({"category": category, **counts,
                            **_rates(counts["true_positives"], counts["false_positives"], counts["false_negatives"])})
    return {**claim, "claim_level": claim, "draft_level": draft, "by_category": by_category,
            "classification": classification,
            "labelled_findings": sum(len(sample["expected"]) for sample in samples),
            "evaluated_examples": len(samples), "dataset_version": DATASET_VERSION}


def evaluate(include_ai=False):
    """Run rules always; AI-assisted evaluation is explicit and uses only fictional fixture data."""
    import ai
    import rules

    validate_dataset()
    rule_predictions = [rules.check(sample["text"], sample["facts"], TODAY) for sample in SAMPLES]
    result = {"dataset_version": DATASET_VERSION, "evaluated_examples": len(SAMPLES), "today": TODAY,
              "configuration": {"rules": "deterministic", "ai": "not_requested"},
              "deterministic": score(rule_predictions)}
    if include_ai:
        if not ai.available():
            result["configuration"]["ai"] = "unavailable"
        else:
            ai_predictions = ai.find_benchmark_claims(SAMPLES, rule_predictions, TODAY)
            combined = [rule_predictions[index] + ai_predictions[index] for index in range(len(SAMPLES))]
            result["configuration"]["ai"] = "claude_vision_language_model"
            result["ai_assisted"] = score(combined)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate TrustGate's frozen fictional benchmark dataset.")
    parser.add_argument("--with-ai", action="store_true", help="Also call configured Claude on fictional benchmark drafts; may incur API cost.")
    args = parser.parse_args(argv)
    result = evaluate(include_ai=args.with_ai)
    if args.with_ai and result["configuration"]["ai"] == "unavailable":
        result["ai_assisted"] = {"status": "unavailable", "reason": "Claude is not configured; no AI-assisted predictions were evaluated."}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())