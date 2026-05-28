from __future__ import annotations

from openagentpolicy.config import PiiDetectionConfig
from openagentpolicy.inventory.schema import Inventory
from openagentpolicy.pii import (
    RegexPiiDetector,
    create_pii_detector,
    redact_spans,
)
from openagentpolicy.privacy import REDACTED_VALUE, PrivacyRedactor
from openagentpolicy.runtime.events import PolicyEvent


def _detector() -> RegexPiiDetector:
    return RegexPiiDetector.from_entities(
        ["CREDIT_CARD", "EMAIL_ADDRESS", "IN_PAN", "IN_AADHAAR", "US_SSN"]
    )


def test_regex_detector_finds_common_pii() -> None:
    detector = _detector()
    assert detector.detect("mail john@example.com")
    assert detector.detect("pan ABCDE1234F")
    assert detector.detect("ssn 123-45-6789")
    assert detector.detect("card 4111111111111111")


def test_regex_detector_validates_checksums() -> None:
    detector = _detector()
    # Invalid Luhn card number is rejected.
    assert detector.detect("card 4111111111111112") == []
    # Invalid Aadhaar (bad Verhoeff) is rejected.
    assert detector.detect("aadhaar 1234 5678 9012") == []
    # Valid Aadhaar (good Verhoeff) is detected.
    assert detector.detect("aadhaar 2341 2341 2346")


def test_redact_spans_preserves_surrounding_text() -> None:
    detector = _detector()
    text = "Contact john@example.com for details."
    spans = detector.detect(text)
    redacted = redact_spans(text, spans)
    assert "john@example.com" not in redacted
    assert redacted.startswith("Contact ")
    assert redacted.endswith(" for details.")


def test_pii_detection_disabled_by_default() -> None:
    config = PiiDetectionConfig()
    assert config.enabled is False
    assert create_pii_detector(
        enabled=config.enabled,
        engine=config.engine,
        entities=config.entities,
        languages=config.languages,
    ) is None


def test_redactor_without_detector_leaves_free_text() -> None:
    redactor = PrivacyRedactor.from_config(Inventory(), ["password"])
    event = PolicyEvent(
        event_type="before_final_response",
        final_response="Reach me at john@example.com",
    )
    redacted = redactor.redact_event(event)
    assert redacted.final_response == "Reach me at john@example.com"


def test_redactor_scans_final_response_when_enabled() -> None:
    redactor = PrivacyRedactor.from_config(
        Inventory(),
        ["password"],
        pii_detector=_detector(),
        scan_fields=["final_response"],
    )
    event = PolicyEvent(
        event_type="before_final_response",
        final_response="Your PAN ABCDE1234F is on file.",
    )
    redacted = redactor.redact_event(event)
    assert "ABCDE1234F" not in (redacted.final_response or "")
    assert REDACTED_VALUE in (redacted.final_response or "")


def test_redactor_scans_tool_args_strings() -> None:
    redactor = PrivacyRedactor.from_config(
        Inventory(),
        ["password"],
        pii_detector=_detector(),
        scan_fields=["tool_args"],
    )
    event = PolicyEvent(
        event_type="before_tool_call",
        tool_id="send_email",
        tool_args={"note": "ssn 123-45-6789"},
    )
    redacted = redactor.redact_event(event)
    assert "123-45-6789" not in redacted.tool_args["note"]


def test_key_redaction_still_applies_without_detector() -> None:
    redactor = PrivacyRedactor.from_config(Inventory(), ["password"])
    out = redactor.redact_dict({"password": "hunter2", "name": "ok"})
    assert out["password"] == REDACTED_VALUE
    assert out["name"] == "ok"


def test_scan_fields_gating_skips_unlisted_field() -> None:
    redactor = PrivacyRedactor.from_config(
        Inventory(),
        ["password"],
        pii_detector=_detector(),
        scan_fields=["final_response"],
    )
    event = PolicyEvent(
        event_type="before_tool_call",
        tool_id="send_email",
        tool_args={"note": "ssn 123-45-6789"},
    )
    redacted = redactor.redact_event(event)
    # tool_args not in scan_fields, so PII value scanning is skipped there.
    assert redacted.tool_args["note"] == "ssn 123-45-6789"


def test_unknown_engine_raises() -> None:
    try:
        create_pii_detector(
            enabled=True, engine="bogus", entities=[], languages=["en"]
        )
    except ValueError as exc:
        assert "engine" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for unknown engine")
