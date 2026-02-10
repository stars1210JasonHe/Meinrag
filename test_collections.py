"""
Test script for Collections feature (Phase G + H).
Tests: manual collections, AI auto-suggest, filtering, combined filters.

Usage:
    uv run python test_collections.py
"""

import logging
import shutil
from pathlib import Path

from fpdf import FPDF

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("test_collections")

TEST_DIR = Path("data/test_collections")
PDF_LAW = TEST_DIR / "contract.pdf"
PDF_MEDICAL = TEST_DIR / "medical_report.pdf"
PDF_TECH = TEST_DIR / "technical_manual.pdf"


def create_test_pdfs():
    """Generate three test PDFs for different collections."""
    TEST_DIR.mkdir(parents=True, exist_ok=True)

    # PDF 1: Law/Legal
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Employment Contract Agreement", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, (
        "This Employment Agreement is entered into between the Employer and Employee. "
        "The parties agree to the following terms and conditions:\n\n"
        "1. Employment Term: The Employee shall be employed for an initial term of two years.\n"
        "2. Compensation: The Employee shall receive an annual salary of $75,000.\n"
        "3. Termination: Either party may terminate this agreement with 30 days written notice.\n"
        "4. Confidentiality: The Employee agrees to maintain confidentiality of proprietary information.\n"
        "5. Governing Law: This agreement shall be governed by the laws of the State of California."
    ))
    pdf.output(str(PDF_LAW))

    # PDF 2: Medical
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Patient Medical Report", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, (
        "Patient Name: John Doe\n"
        "Date of Visit: 2024-02-10\n\n"
        "Chief Complaint: Patient presents with persistent headaches for the past two weeks.\n\n"
        "Examination: Blood pressure 120/80, heart rate 72 bpm. Neurological exam normal.\n\n"
        "Diagnosis: Tension-type headache likely due to stress and poor posture.\n\n"
        "Treatment Plan:\n"
        "- Prescribe ibuprofen 400mg as needed for pain\n"
        "- Recommend stress management techniques and ergonomic workspace adjustments\n"
        "- Follow-up in 2 weeks if symptoms persist"
    ))
    pdf.output(str(PDF_MEDICAL))

    # PDF 3: Technical
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Server Configuration Manual", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, (
        "Chapter 1: Initial Setup\n\n"
        "This manual describes the configuration process for the XYZ-2000 application server.\n\n"
        "System Requirements:\n"
        "- CPU: 4-core processor (minimum 2.5 GHz)\n"
        "- RAM: 16 GB minimum, 32 GB recommended\n"
        "- Storage: 500 GB SSD\n"
        "- OS: Ubuntu 22.04 LTS or RHEL 8\n\n"
        "Installation Steps:\n"
        "1. Download the installation package from the official repository\n"
        "2. Extract to /opt/xyz2000/\n"
        "3. Run ./install.sh as root\n"
        "4. Configure database connection in config.yml\n"
        "5. Start the service: systemctl start xyz2000"
    ))
    pdf.output(str(PDF_TECH))

    print(f"  Generated: {PDF_LAW.name}, {PDF_MEDICAL.name}, {PDF_TECH.name}")


def test_config():
    """Test that collections config works."""
    print("\n" + "=" * 60)
    print("TEST 1: Config - Collections Support")
    print("=" * 60)

    from app.config import get_settings
    settings = get_settings()
    print(f"  Config loaded successfully")
    print(f"  Vector Store: {settings.vector_store.value}")
    print(f"  Top K: {settings.retrieval_top_k}")
    print("  [OK] Config works")
    return settings


def test_schemas():
    """Test that new schema fields work."""
    print("\n" + "=" * 60)
    print("TEST 2: Schemas - New Collection Fields")
    print("=" * 60)

    from app.models.schemas import QueryRequest, UploadResponse, DocumentInfo

    # Test QueryRequest with collection
    req = QueryRequest(question="Test?", collection="law")
    assert req.collection == "law"
    print(f"  QueryRequest with collection: {req.collection}")

    # Test UploadResponse with collection
    resp = UploadResponse(
        doc_id="abc",
        filename="test.pdf",
        chunk_count=5,
        collection="law",
        suggested_collection="legal",
        message="OK"
    )
    assert resp.collection == "law"
    assert resp.suggested_collection == "legal"
    print(f"  UploadResponse: collection={resp.collection}, suggested={resp.suggested_collection}")

    # Test DocumentInfo with collection
    doc_info = DocumentInfo(
        doc_id="abc",
        filename="test.pdf",
        file_type=".pdf",
        chunk_count=5,
        collection="law",
        uploaded_at="2024-02-10"
    )
    assert doc_info.collection == "law"
    print(f"  DocumentInfo: collection={doc_info.collection}")

    print("  [OK] Schemas work")


def test_document_registry():
    """Test DocumentRegistry with collections."""
    print("\n" + "=" * 60)
    print("TEST 3: DocumentRegistry - Collection Tracking")
    print("=" * 60)

    from app.models.document import DocumentRegistry

    test_file = TEST_DIR / "test_registry.json"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    if test_file.exists():
        test_file.unlink()

    registry = DocumentRegistry(test_file)

    # Add documents with collections
    registry.add("doc1", "file1.pdf", ".pdf", 10, collection="law")
    registry.add("doc2", "file2.pdf", ".pdf", 15, collection="medical")
    registry.add("doc3", "file3.pdf", ".pdf", 20, collection="law")
    registry.add("doc4", "file4.pdf", ".pdf", 5, collection=None)

    # Test list_all
    all_docs = registry.list_all()
    assert len(all_docs) == 4
    print(f"  Total documents: {len(all_docs)}")

    # Test list_by_collection
    law_docs = registry.list_by_collection("law")
    assert len(law_docs) == 2
    print(f"  Law collection: {len(law_docs)} documents")

    medical_docs = registry.list_by_collection("medical")
    assert len(medical_docs) == 1
    print(f"  Medical collection: {len(medical_docs)} documents")

    # Cleanup
    test_file.unlink()
    print("  [OK] DocumentRegistry works")


def test_vector_store_filtering(settings):
    """Test vector store collection filtering."""
    print("\n" + "=" * 60)
    print("TEST 4: Vector Store - Collection Filtering")
    print("=" * 60)

    from app.vectorstore.chroma_store import ChromaStoreManager
    from app.llm.provider import create_embeddings
    from app.services.document_processor import DocumentProcessor
    from langchain_core.documents import Document

    embeddings = create_embeddings(settings)
    store = ChromaStoreManager(persist_directory=TEST_DIR)
    store.initialize(embeddings)

    processor = DocumentProcessor(settings)

    # Process and add documents with collections
    chunks_law = processor.load_and_split(PDF_LAW)
    for chunk in chunks_law:
        chunk.metadata["collection"] = "law"
    store.add_documents(chunks_law, doc_id="doc_law")
    print(f"  Added {len(chunks_law)} law chunks")

    chunks_medical = processor.load_and_split(PDF_MEDICAL)
    for chunk in chunks_medical:
        chunk.metadata["collection"] = "medical"
    store.add_documents(chunks_medical, doc_id="doc_medical")
    print(f"  Added {len(chunks_medical)} medical chunks")

    # Test filtering by collection
    results_law = store.similarity_search_with_filter(
        "termination notice", k=3, collection="law"
    )
    print(f"  Query 'termination notice' in law: {len(results_law)} results")
    for doc in results_law:
        assert doc.metadata.get("collection") == "law"

    results_medical = store.similarity_search_with_filter(
        "patient headache", k=3, collection="medical"
    )
    print(f"  Query 'patient headache' in medical: {len(results_medical)} results")
    for doc in results_medical:
        assert doc.metadata.get("collection") == "medical"

    # Test combined filtering (collection + doc_ids)
    results_combined = store.similarity_search_with_filter(
        "employment", k=3, doc_ids=["doc_law"], collection="law"
    )
    print(f"  Combined filter (doc_ids + collection): {len(results_combined)} results")

    # Cleanup
    store.delete_document("doc_law")
    store.delete_document("doc_medical")
    print("  [OK] Vector store filtering works")


def test_ai_suggest(settings):
    """Test AI collection suggestion."""
    print("\n" + "=" * 60)
    print("TEST 5: AI Auto-Suggest Collection")
    print("=" * 60)

    from app.llm.provider import create_chat_model
    from app.services.document_processor import DocumentProcessor
    from app.services.collection_suggester import suggest_collection

    llm = create_chat_model(settings)
    processor = DocumentProcessor(settings)

    # Test legal document
    chunks_law = processor.load_and_split(PDF_LAW)
    suggestion_law = suggest_collection(chunks_law, llm)
    print(f"  Legal document suggestion: '{suggestion_law}'")
    assert len(suggestion_law) > 0
    assert len(suggestion_law) <= 50

    # Test medical document
    chunks_medical = processor.load_and_split(PDF_MEDICAL)
    suggestion_medical = suggest_collection(chunks_medical, llm)
    print(f"  Medical document suggestion: '{suggestion_medical}'")
    assert len(suggestion_medical) > 0

    # Test technical document
    chunks_tech = processor.load_and_split(PDF_TECH)
    suggestion_tech = suggest_collection(chunks_tech, llm)
    print(f"  Technical document suggestion: '{suggestion_tech}'")
    assert len(suggestion_tech) > 0

    print("  [OK] AI suggestions work")


def test_backwards_compatibility(settings):
    """Test that existing API calls still work without collections."""
    print("\n" + "=" * 60)
    print("TEST 6: Backwards Compatibility")
    print("=" * 60)

    from app.vectorstore.chroma_store import ChromaStoreManager
    from app.llm.provider import create_embeddings, create_chat_model
    from app.services.document_processor import DocumentProcessor
    from app.rag.chain import build_rag_chain

    embeddings = create_embeddings(settings)
    store = ChromaStoreManager(persist_directory=TEST_DIR)
    store.initialize(embeddings)
    llm = create_chat_model(settings)

    processor = DocumentProcessor(settings)
    chunks = processor.load_and_split(PDF_LAW)
    # Don't set collection - test null handling
    store.add_documents(chunks, doc_id="test_compat")
    print(f"  Added {len(chunks)} chunks without collection")

    # Test old-style build_rag_chain call (no collection param)
    chain, retriever = build_rag_chain(
        vector_store=store,
        llm=llm,
        top_k=3
    )
    print("  Built RAG chain without collection param")

    # Test query
    answer = chain.invoke("What is this document about?")
    assert len(answer) > 0
    print(f"  Query result: {answer[:100]}...")

    # Cleanup
    store.delete_document("test_compat")
    print("  [OK] Backwards compatibility preserved")


def cleanup():
    """Remove test artifacts."""
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)


def main():
    print("=" * 60)
    print("  MEINRAG - Collections Feature Test Suite (Phase G + H)")
    print("=" * 60)

    # Test 1: Config
    settings = test_config()

    # Test 2: Schemas
    test_schemas()

    # Test 3: DocumentRegistry
    test_document_registry()

    # Generate test PDFs
    print("\n" + "=" * 60)
    print("SETUP: Generating test PDFs")
    print("=" * 60)
    create_test_pdfs()

    # Check API key
    api_key = settings.openai_api_key
    if not api_key or api_key.startswith("sk-YOUR"):
        print("\n[DONE] Skipped vector store and AI tests (no API key).")
        print("Set OPENAI_API_KEY in .env and re-run for full test.")
        cleanup()
        return

    # Test 4: Vector store filtering
    test_vector_store_filtering(settings)

    # Test 5: AI suggestions
    test_ai_suggest(settings)

    # Test 6: Backwards compatibility
    test_backwards_compatibility(settings)

    # Cleanup
    cleanup()
    print("\n" + "=" * 60)
    print("  ALL COLLECTIONS TESTS PASSED! Cleaned up test artifacts.")
    print("=" * 60)


if __name__ == "__main__":
    main()
