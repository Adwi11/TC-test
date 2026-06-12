from app.services.confidence import score_fields, _normalize_phone


def test_email_high_confidence_when_regex_passes():
    """A valid email plus high LLM self-confidence should land in the high tier with source=regex."""
    out = score_fields({
        "name": "Asha Rao", "email": "asha@example.com", "phone": "9876543210",
        "company": "Acme", "designation": "Engineer", "skills": ["py", "ts", "go"],
        "confidence": {"name": 0.9, "email": 0.9, "phone": 0.9, "company": 0.9, "designation": 0.9, "skills": 0.9},
    }, route="text")
    assert out["field_confidence"]["email"]["score"] >= 0.9
    assert out["field_confidence"]["email"]["source"] == "regex"
    assert out["field_confidence"]["email"]["validated"] is True


def test_email_regex_runs_on_vision_route_too():
    """Email regex validation applies regardless of which extraction lane ran."""
    out = score_fields({
        "name": None, "email": "good@example.com", "phone": None, "company": None,
        "designation": None, "skills": [],
        "confidence": {"email": 0.8},
    }, route="vision")
    assert out["field_confidence"]["email"]["source"] == "regex"
    assert out["field_confidence"]["email"]["validated"] is True


def test_email_low_when_malformed():
    """Malformed emails should produce a low score and fall back to the route source."""
    out = score_fields({
        "name": "X", "email": "not-an-email", "phone": None, "company": None,
        "designation": None, "skills": [],
        "confidence": {"name": 0.5, "email": 0.5, "phone": 0.0, "company": 0.0, "designation": 0.0, "skills": 0.0},
    }, route="text")
    assert out["field_confidence"]["email"]["validated"] is False
    assert out["field_confidence"]["email"]["source"] == "llm"
    assert out["field_confidence"]["email"]["score"] < 0.5


def test_non_email_fields_pass_through_llm_score():
    """Non-email fields should mirror llm self-confidence with no rule-based boost."""
    out = score_fields({
        "name": "Asha", "email": None, "phone": "9876543210",
        "company": "Acme", "designation": "Engineer", "skills": ["py", "ts", "go"],
        "confidence": {"name": 0.42, "phone": 0.7, "company": 0.6, "designation": 0.6, "skills": 0.6},
    }, route="text")
    fc = out["field_confidence"]
    assert fc["name"]["score"] == 0.42
    assert fc["name"]["source"] == "llm"
    assert fc["name"]["validated"] is None
    assert fc["phone"]["score"] == 0.7
    assert fc["skills"]["score"] == 0.6


def test_phone_normalisation_strips_country_code():
    """+91 prefix should be stripped to a 10-digit local number."""
    assert _normalize_phone("+91 98765 43210") == "9876543210"
    assert _normalize_phone("09876543210") == "9876543210"
    assert _normalize_phone("9876543210") == "9876543210"


def test_route_source_propagates_for_non_email():
    """When the route is vision, non-email fields record that route as their source."""
    out = score_fields({
        "name": "A", "email": "a@b.io", "phone": "9876543210", "company": "C",
        "designation": "D", "skills": ["x", "y", "z"],
        "confidence": {"name": 0.7, "email": 0.7, "phone": 0.7, "company": 0.7, "designation": 0.7, "skills": 0.7},
    }, route="vision")
    assert out["field_confidence"]["name"]["source"] == "vision"
    assert out["field_confidence"]["skills"]["source"] == "vision"
    assert out["field_confidence"]["email"]["source"] == "regex"
