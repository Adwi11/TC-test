from app.models import Candidate
from app.workflow.agent import should_auto_request, AUTO_REQUEST_THRESHOLD


def _c(email, fc):
    """Build a candidate stub with the given email and field_confidence_json."""
    return Candidate(name="X", email=email, phone="9999999999", field_confidence_json=fc)


def test_auto_request_true_when_all_fields_above_threshold():
    """All scored fields >= 0.75 with a valid email should pass the gate."""
    fc = {k: {"score": 0.9, "source": "llm"} for k in ("name", "email", "phone", "company", "designation", "skills")}
    ok, _ = should_auto_request(_c("asha@example.com", fc))
    assert ok is True


def test_auto_request_blocked_by_low_field():
    """A single field below the threshold should block the gate."""
    fc = {k: {"score": 0.9, "source": "llm"} for k in ("name", "email", "phone", "company", "designation", "skills")}
    fc["skills"] = {"score": 0.4, "source": "llm"}
    ok, reason = should_auto_request(_c("asha@example.com", fc))
    assert ok is False
    assert "skills" in reason


def test_auto_request_blocked_when_email_invalid():
    """Auto-request must not fire on an invalid email regardless of confidence."""
    fc = {k: {"score": 1.0, "source": "llm"} for k in ("name", "email", "phone")}
    ok, _ = should_auto_request(_c("not-an-email", fc))
    assert ok is False


def test_threshold_is_75_percent():
    """The threshold is documented as 0.75."""
    assert AUTO_REQUEST_THRESHOLD == 0.75
