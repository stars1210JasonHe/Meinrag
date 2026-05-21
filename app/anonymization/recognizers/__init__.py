"""Custom Presidio recognizers for entity types not covered by built-ins.

Presidio ships with PERSON, EMAIL_ADDRESS, PHONE_NUMBER, US_SSN,
CREDIT_CARD, IP_ADDRESS, etc. We add Chinese-specific structured PII
that the built-ins miss: ID numbers, mobile phones, bank cards, passports.

Registered via `register_chinese_recognizers(analyzer)` — called once at
engine construction time.
"""
from app.anonymization.recognizers.chinese import register_chinese_recognizers

__all__ = ["register_chinese_recognizers"]
