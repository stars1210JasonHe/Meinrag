"""Phase 2 verification: per-document EntityRegistry.

Covers:
- Same entity → same pseudonym (cross-chunk consistency)
- Different entities of same type get sequential counters
- Different entity types are counter-independent
- Pseudonyms use typed format [ENTITY_TYPE_N]
- deanonymize() reverses replacements
- deanonymize() handles overlapping prefix pseudonyms correctly
- from_mappings() rehydrates a read-only registry
- new_mappings tracks only newly minted entries (not loaded ones)
"""
from app.anonymization.registry import EntityMapping, EntityRegistry


class TestCrossChunkConsistency:
    def test_same_entity_returns_same_pseudonym(self):
        r = EntityRegistry()
        p1 = r.get_or_create_pseudonym("张三", "PERSON")
        p2 = r.get_or_create_pseudonym("张三", "PERSON")
        assert p1 == p2

    def test_different_entities_get_sequential_counters(self):
        r = EntityRegistry()
        p1 = r.get_or_create_pseudonym("张三", "PERSON")
        p2 = r.get_or_create_pseudonym("李四", "PERSON")
        p3 = r.get_or_create_pseudonym("王五", "PERSON")
        assert p1 == "[PERSON_1]"
        assert p2 == "[PERSON_2]"
        assert p3 == "[PERSON_3]"

    def test_different_entity_types_independent_counters(self):
        r = EntityRegistry()
        person = r.get_or_create_pseudonym("Alice", "PERSON")
        email = r.get_or_create_pseudonym("alice@example.com", "EMAIL_ADDRESS")
        phone = r.get_or_create_pseudonym("555-1234", "PHONE_NUMBER")
        assert person == "[PERSON_1]"
        assert email == "[EMAIL_ADDRESS_1]"
        assert phone == "[PHONE_NUMBER_1]"


class TestPseudonymFormat:
    def test_typed_placeholder_format(self):
        r = EntityRegistry()
        p = r.get_or_create_pseudonym("张三", "PERSON")
        assert p.startswith("[PERSON_")
        assert p.endswith("]")

    def test_us_ssn_pseudonym_carries_type_signal(self):
        """Article §8.3 strategy 1: typed placeholders preserve more
        embedding signal than generic redaction."""
        r = EntityRegistry()
        p = r.get_or_create_pseudonym("555-12-3456", "US_SSN")
        assert "US_SSN" in p


class TestDeanonymize:
    def test_single_pseudonym_round_trip(self):
        r = EntityRegistry()
        p = r.get_or_create_pseudonym("张三", "PERSON")
        text = f"Plaintiff {p} filed a complaint."
        assert r.deanonymize(text) == "Plaintiff 张三 filed a complaint."

    def test_multiple_pseudonyms_round_trip(self):
        r = EntityRegistry()
        p1 = r.get_or_create_pseudonym("Alice", "PERSON")
        p2 = r.get_or_create_pseudonym("alice@example.com", "EMAIL_ADDRESS")
        text = f"{p1} can be reached at {p2}."
        assert r.deanonymize(text) == "Alice can be reached at alice@example.com."

    def test_prefix_overlap_resolves_correctly(self):
        """Defensive: [PERSON_1] is a substring of [PERSON_10]. Without
        longest-first ordering, deanonymizing [PERSON_10] would corrupt
        it to '张三0' (the leading [PERSON_1] would match first).
        """
        r = EntityRegistry()
        # Mint 10+ persons to force the [PERSON_1] vs [PERSON_10] case
        names = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K"]
        for n in names:
            r.get_or_create_pseudonym(n, "PERSON")
        text = "[PERSON_10] and [PERSON_1] talked."
        assert r.deanonymize(text) == "J and A talked."

    def test_unknown_pseudonym_left_unchanged(self):
        """deanonymize doesn't invent originals — unknown tokens pass
        through. This matters when the panel renders chunks from docs
        with disjoint registries."""
        r = EntityRegistry()
        r.get_or_create_pseudonym("Alice", "PERSON")
        text = "Hello [UNKNOWN_42], how are you?"
        assert r.deanonymize(text) == "Hello [UNKNOWN_42], how are you?"


class TestNewMappingsTracking:
    def test_new_mappings_recorded_in_order(self):
        r = EntityRegistry()
        r.get_or_create_pseudonym("Alice", "PERSON")
        r.get_or_create_pseudonym("bob@example.com", "EMAIL_ADDRESS")
        assert len(r.new_mappings) == 2
        assert r.new_mappings[0].original == "Alice"
        assert r.new_mappings[0].entity_type == "PERSON"
        assert r.new_mappings[1].entity_type == "EMAIL_ADDRESS"

    def test_repeated_entity_does_not_duplicate(self):
        r = EntityRegistry()
        r.get_or_create_pseudonym("Alice", "PERSON")
        r.get_or_create_pseudonym("Alice", "PERSON")
        r.get_or_create_pseudonym("Alice", "PERSON")
        assert len(r.new_mappings) == 1

    def test_len_tracks_unique_entities(self):
        r = EntityRegistry()
        r.get_or_create_pseudonym("A", "PERSON")
        r.get_or_create_pseudonym("B", "PERSON")
        r.get_or_create_pseudonym("A", "PERSON")  # repeat
        assert len(r) == 2


class TestFromMappings:
    def test_rehydrate_from_persisted_mappings(self):
        mappings = [
            EntityMapping(original="张三", pseudonym="[PERSON_1]", entity_type="PERSON"),
            EntityMapping(original="李四", pseudonym="[PERSON_2]", entity_type="PERSON"),
        ]
        r = EntityRegistry.from_mappings(mappings)
        text = "[PERSON_1] sued [PERSON_2]."
        assert r.deanonymize(text) == "张三 sued 李四."

    def test_rehydrated_registry_has_no_new_mappings(self):
        """Rehydrated registries are READ-ONLY for retrieval. We must
        not write back loaded mappings as 'new' rows on the next save."""
        mappings = [
            EntityMapping(original="x", pseudonym="[PERSON_1]", entity_type="PERSON"),
        ]
        r = EntityRegistry.from_mappings(mappings)
        assert r.new_mappings == []

    def test_rehydrated_registry_empty_when_no_mappings(self):
        r = EntityRegistry.from_mappings([])
        assert len(r) == 0
        assert r.deanonymize("[PERSON_1]") == "[PERSON_1]"
