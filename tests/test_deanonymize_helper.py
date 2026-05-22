import pytest
from langchain_core.documents import Document

from app.services.deanonymize import deanonymize_chunks


def test_deanonymize_replaces_pseudonyms_per_doc():
    chunks = [
        Document(
            page_content="On [DATE_1], [PERSON_1] called [PERSON_2].",
            metadata={"doc_id": "docA"},
        ),
        Document(
            page_content="[PERSON_1] is the plaintiff.",
            metadata={"doc_id": "docB"},
        ),
    ]
    mappings = {
        "docA": {"[DATE_1]": "2026-04-15", "[PERSON_1]": "Alice", "[PERSON_2]": "Bob"},
        "docB": {"[PERSON_1]": "Carol"},  # Same pseudonym, different doc → different name
    }
    out = deanonymize_chunks(chunks, mappings)

    assert out[0].page_content == "On 2026-04-15, Alice called Bob."
    assert out[1].page_content == "Carol is the plaintiff."
    # Metadata preserved
    assert out[0].metadata == {"doc_id": "docA"}


def test_deanonymize_no_mappings_passthrough():
    chunks = [Document(page_content="Hello world", metadata={"doc_id": "docA"})]
    out = deanonymize_chunks(chunks, {})
    assert out[0].page_content == "Hello world"


def test_deanonymize_longest_first_avoids_prefix_collision():
    """[PERSON_1] should not partially replace inside [PERSON_12]."""
    chunks = [Document(
        page_content="[PERSON_12] knows [PERSON_1].",
        metadata={"doc_id": "docA"},
    )]
    mappings = {"docA": {"[PERSON_1]": "Alice", "[PERSON_12]": "Bob"}}
    out = deanonymize_chunks(chunks, mappings)
    assert out[0].page_content == "Bob knows Alice."


def test_deanonymize_chunk_without_doc_id_passthrough():
    """Chunks whose metadata lacks doc_id (legacy / non-anonymized) pass through."""
    chunks = [Document(page_content="[PERSON_1] said hi", metadata={})]
    out = deanonymize_chunks(chunks, {"docA": {"[PERSON_1]": "Alice"}})
    assert out[0].page_content == "[PERSON_1] said hi"


def test_deanonymize_doc_id_not_in_mappings_passthrough():
    """Chunk's doc_id has no mapping entries → chunk passes through unchanged."""
    chunks = [Document(page_content="[PERSON_1] said hi", metadata={"doc_id": "docC"})]
    out = deanonymize_chunks(chunks, {"docA": {"[PERSON_1]": "Alice"}})
    assert out[0].page_content == "[PERSON_1] said hi"


def test_deanonymize_empty_mapping_dict_passthrough():
    """doc_id IS in mappings_by_doc but the inner dict is empty.

    Documents the contract: `get_by_docs` pre-populates every requested
    doc_id with `{}` even when no mapping rows exist. The legitimate
    case this covers is a doc that was anonymized but contained no PII
    (e.g., a public arXiv paper). Passthrough is correct.
    """
    chunks = [Document(page_content="[PERSON_1] said hi", metadata={"doc_id": "docA"})]
    out = deanonymize_chunks(chunks, {"docA": {}})
    assert out[0].page_content == "[PERSON_1] said hi"
