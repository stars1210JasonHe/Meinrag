"""Per-document EntityRegistry.

Ensures cross-chunk pseudonym consistency: if "张三" appears in chunks 1,
5, and 12 of a document, all three are replaced with the same token
("[PERSON_1]") so the user can track the entity across retrieved chunks
and deanonymization is unambiguous.

Registries are per-DOCUMENT, never global — different documents may use
the same pseudonym for different entities, which is intentional for
cross-doc isolation. See article §7.4.

Typed placeholders (`[PERSON_1]`) are preferred over generic redaction
(`████`) or Faker-style fake names. They preserve entity-type signal for
the embedding model — article §8.3 strategy 1 — while removing the
identifying token.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EntityMapping:
    """A single original-text → pseudonym record.

    Persisted (with `original` Fernet-encrypted) into
    `anonymization_mappings`. Used at retrieval time to deanonymize.
    """
    original: str
    pseudonym: str
    entity_type: str


@dataclass
class EntityRegistry:
    """Per-document mapping. Build during pre-embedding pass, then persist
    its `new_mappings` to the encrypted mappings table.

    NOT thread-safe — one registry per document means one pipeline pass
    has exclusive access.
    """
    _mapping: dict[str, str] = field(default_factory=dict)
    _reverse: dict[str, str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)
    new_mappings: list[EntityMapping] = field(default_factory=list)

    def get_or_create_pseudonym(self, original: str, entity_type: str) -> str:
        """Return the existing pseudonym for `original`, or mint a new one.

        Pseudonyms follow `[ENTITY_TYPE_N]` where N is a per-type counter.
        Same original → same pseudonym across the document.

        Note: keyed by exact surface form. NER variants of the same
        underlying entity ("Smith" vs "Mr. Smith" vs "John Smith") get
        distinct pseudonyms. This is a known limitation of NER (not
        a code bug); v2 polish could add a coreference-resolution step.
        """
        if original in self._mapping:
            return self._mapping[original]
        n = self._counters.get(entity_type, 0) + 1
        self._counters[entity_type] = n
        pseudonym = f"[{entity_type}_{n}]"
        self._mapping[original] = pseudonym
        self._reverse[pseudonym] = original
        self.new_mappings.append(
            EntityMapping(
                original=original,
                pseudonym=pseudonym,
                entity_type=entity_type,
            )
        )
        return pseudonym

    def deanonymize(self, text: str) -> str:
        """Replace every pseudonym in `text` with its original. Used by
        the retrieval-time deanonymizer when a registry has been
        rehydrated from the encrypted mappings table.

        Order matters: longest pseudonyms first to avoid `[PERSON_1]`
        being a prefix-substring of `[PERSON_12]`. (Currently safe given
        the typed format, but defensive sort is cheap insurance.)
        """
        for pseudonym in sorted(self._reverse.keys(), key=len, reverse=True):
            text = text.replace(pseudonym, self._reverse[pseudonym])
        return text

    def __len__(self) -> int:
        return len(self._mapping)

    @classmethod
    def from_mappings(cls, mappings: list[EntityMapping]) -> "EntityRegistry":
        """Rehydrate a registry from previously-persisted mappings.

        Used at retrieval time: load + decrypt all rows for a doc_id,
        instantiate via from_mappings, then call deanonymize on chunk text.
        new_mappings stays empty — these are loaded, not minted.

        IMPORTANT: do NOT call get_or_create_pseudonym on a rehydrated
        registry. Counters restart at 0 and would mint colliding names
        like `[PERSON_1]` even if that pseudonym is already mapped to
        someone else. v1's pipeline does one registry per full document
        ingest pass, never partial-then-extend.
        """
        reg = cls()
        for m in mappings:
            reg._mapping[m.original] = m.pseudonym
            reg._reverse[m.pseudonym] = m.original
            # Counters intentionally NOT rebuilt — see docstring warning.
        return reg
