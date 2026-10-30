import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import benchmark
import pytest


def record(sample_id, expected=(), expected_result=None):
    expected = list(expected)
    return {"id": sample_id, "title": sample_id, "text": f"Fictional draft {sample_id}.", "facts": [],
            "expected": expected, "expected_result": expected_result or ("finding" if expected else "no_finding"),
            "expected_classification": "Needs human review" if expected else benchmark.NO_FINDING_EXPECTED}


def test_score_separates_category_sensitive_claims_from_draft_detection():
    samples = [record("a", ["Offer mismatches"]), record("b"),
               record("c", ["Unsupported claims"]), record("d", ["Tone / naming"])]
    predictions = [[{"category": "Offer mismatches", "classification": "Needs human review"}],
                   [{"category": "Unsupported claims"}],
                   [],
                   [{"category": "Offer mismatches"}]]
    result = benchmark.score(predictions, samples)
    assert result["claim_level"]["true_positives"] == 1
    assert result["claim_level"]["false_positives"] == 2
    assert result["claim_level"]["false_negatives"] == 2
    assert result["claim_level"]["precision"] == 33.3
    assert result["claim_level"]["recall"] == 33.3
    assert result["claim_level"]["f1"] == 33.3
    assert result["draft_level"]["true_positives"] == 2
    assert result["draft_level"]["false_positives"] == 1
    assert result["draft_level"]["false_negatives"] == 1
    assert result["draft_level"]["f1"] == 66.7
    assert result["classification"] == {"accuracy": 100.0, "correct": 1, "errors": 0, "evaluated": 1}
    by_category = {item["category"]: item for item in result["by_category"]}
    assert by_category["Unsupported claims"]["false_positives"] == 1
    assert by_category["Unsupported claims"]["false_negatives"] == 1
    assert by_category["Tone / naming"]["false_negatives"] == 1


def test_score_handles_zero_denominators():
    samples = [record("clean-a"), record("clean-b")]
    result = benchmark.score([[], []], samples)
    assert result["claim_level"]["precision"] == 0
    assert result["claim_level"]["recall"] == 0
    assert result["claim_level"]["f1"] == 0
    assert result["draft_level"]["precision"] == 0
    assert result["draft_level"]["recall"] == 0
    assert result["draft_level"]["f1"] == 0
    assert result["draft_level"]["true_negatives"] == 2
    assert result["draft_level"]["accuracy"] == 100

def test_classification_error_is_separate_from_detection():
    sample = record("wrong-class", ["Offer mismatches"])
    result = benchmark.score([[{"category": "Offer mismatches", "classification": "Unsupported claim"}]], [sample])
    assert result["claim_level"]["true_positives"] == 1
    assert result["classification"] == {"accuracy": 0.0, "correct": 0, "errors": 1, "evaluated": 1}
    assert next(x for x in result["by_category"] if x["category"] == "Offer mismatches")["classification_errors"] == 1


def test_dataset_labels_and_version_are_validated_and_versioned():
    assert len(benchmark.validate_dataset()) == 140
    assert benchmark.DATASET_VERSION == "1.1.0"
    assert all(sample["expected_result"] == ("finding" if sample["expected"] else "no_finding")
               for sample in benchmark.SAMPLES)


@pytest.mark.parametrize("mutate, message", [
    (lambda samples: samples[0].update(text=""), "draft text"),
    (lambda samples: samples[1].update(id=samples[0]["id"]), "Duplicate"),
    (lambda samples: samples[0].update(expected=["invented category"]), "expected categories"),
    (lambda samples: samples[0].update(expected_result="no_finding"), "conflicts"),
    (lambda samples: samples[0].update(facts=["not a fact"]), "malformed approved fact"),
    (lambda samples: samples[0].update(expected=[], expected_result="no_finding",
                                       expected_classification="Verified against approved evidence"), "verified claim"),
])
def test_malformed_dataset_records_are_rejected(mutate, message):
    import copy
    samples = copy.deepcopy(benchmark.SAMPLES[:2])
    mutate(samples)
    with pytest.raises(ValueError, match=message):
        benchmark.validate_dataset(samples)


def test_malformed_prediction_lists_are_rejected():
    sample = record("single", ["Offer mismatches"])
    with pytest.raises(ValueError, match="count"):
        benchmark.score([], [sample])
    with pytest.raises(ValueError, match="must be a list"):
        benchmark.score([None], [sample])
    with pytest.raises(ValueError, match="malformed finding"):
        benchmark.score([[{}]], [sample])


def test_ai_requested_but_unconfigured_is_reported_without_claiming_results(monkeypatch):
    import ai
    monkeypatch.setattr(ai, "available", lambda: False)
    result = benchmark.evaluate(include_ai=True)
    assert result["configuration"]["ai"] == "unavailable"
    assert "ai_assisted" not in result
    assert result["evaluated_examples"] == len(benchmark.SAMPLES)
