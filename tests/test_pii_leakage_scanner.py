"""Sanity check for the PII leakage scanner."""
import pytest

from scripts.scan_vector_store_for_pii import scan_text


def test_scanner_flags_email():
    findings = scan_text("Contact alice@example.com for details.")
    assert any(f["entity_type"] == "EMAIL_ADDRESS" for f in findings)


def test_scanner_flags_ssn():
    findings = scan_text("SSN 123-45-6789 on file.")
    assert any(f["entity_type"] == "US_SSN" for f in findings)


def test_scanner_flags_chinese_id():
    findings = scan_text("身份证号 110101199003078954")
    assert any(f["entity_type"] == "CHINESE_ID_NUMBER" for f in findings)


def test_scanner_passes_pseudonymized_text():
    findings = scan_text(
        "[PERSON_1] filed against [PERSON_2] re: [DATE_1]. "
        "Contact [EMAIL_ADDRESS_1] or [PHONE_NUMBER_1]."
    )
    assert findings == []


def test_scanner_ignores_typed_placeholders():
    findings = scan_text("Plaintext mention of [PERSON_5] is fine.")
    assert findings == []
