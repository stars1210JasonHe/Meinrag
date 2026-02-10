"""
End-to-end test script for MEINRAG phases 1-3.
Tests: config loading, document processing, vector store (chroma + faiss),
       LLM provider creation, and RAG chain with a generated test PDF.

Usage:
    1. Put your OpenAI API key in .env
    2. Run: uv run python test.py
"""

import logging
import shutil
from pathlib import Path

from fpdf import FPDF

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("test")

TEST_PDF_PATH = Path("data/test_sample.pdf")


def create_test_pdf():
    """Generate a multi-page test PDF with real content for RAG testing."""
    TEST_PDF_PATH.parent.mkdir(parents=True, exist_ok=True)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Page 1
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "MEINRAG Technical Architecture Document", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, (
        "MEINRAG is a Retrieval-Augmented Generation (RAG) system designed for "
        "document question-answering. The system uses a FastAPI backend with LangChain "
        "to orchestrate the RAG pipeline. Users upload documents in various formats "
        "(PDF, DOCX, TXT, Markdown, HTML, Excel, PowerPoint) which are then processed, "
        "chunked, and stored as vector embeddings.\n\n"
        "The core architecture consists of three layers:\n"
        "1. Document Ingestion Layer - handles file upload, format detection, text extraction, "
        "and chunking using RecursiveCharacterTextSplitter.\n"
        "2. Vector Storage Layer - stores embeddings with a switchable backend supporting "
        "both ChromaDB (default) and FAISS.\n"
        "3. Query Layer - retrieves relevant chunks via similarity search, constructs a "
        "context-augmented prompt, and generates answers using an LLM.\n\n"
        "The system supports two LLM providers: OpenAI (direct) and OpenRouter (proxy). "
        "Embeddings are always generated using OpenAI's text-embedding-3-small model to "
        "ensure consistency across the vector store, regardless of which chat model is used."
    ))

    # Page 2
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Vector Store Comparison", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, (
        "ChromaDB is the default vector store. It provides automatic persistence to disk, "
        "built-in metadata filtering, and requires no additional infrastructure. Data is stored "
        "in a local SQLite database with parquet files. ChromaDB is ideal for datasets up to "
        "500,000 documents and provides sub-100ms query times.\n\n"
        "FAISS (Facebook AI Similarity Search) is the alternative backend optimized for raw "
        "search speed. It uses optimized index structures and can leverage GPU acceleration. "
        "FAISS excels with datasets exceeding 500,000 documents but requires manual persistence "
        "(save_local/load_local calls) and lacks native metadata filtering.\n\n"
        "The system uses an abstract VectorStoreManager interface that both implementations "
        "conform to. Switching between stores requires only changing the VECTOR_STORE environment "
        "variable from 'chroma' to 'faiss' (or vice versa). The factory pattern in "
        "vectorstore/factory.py handles instantiation."
    ))

    # Page 3
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "API Endpoints", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, (
        "The REST API provides five endpoints:\n\n"
        "POST /documents/upload - Accepts a file upload via multipart form data. The file is "
        "saved to disk, processed through the document loader pipeline, split into chunks, "
        "embedded, and stored in the vector store. Returns a document ID and chunk count.\n\n"
        "GET /documents - Lists all uploaded documents with metadata including filename, "
        "file type, chunk count, and upload timestamp.\n\n"
        "DELETE /documents/{doc_id} - Removes a document from the vector store and metadata "
        "registry. Also deletes the original uploaded file from disk.\n\n"
        "POST /query - Accepts a question and optional top_k parameter. Retrieves the most "
        "relevant chunks from the vector store, constructs a context-augmented prompt, sends "
        "it to the LLM, and returns the answer along with source chunks.\n\n"
        "GET /health - Returns system status including the active LLM provider, vector store "
        "type, and total document count."
    ))

    pdf.output(str(TEST_PDF_PATH))
    print(f"  Generated test PDF: {TEST_PDF_PATH} ({TEST_PDF_PATH.stat().st_size} bytes)")


def test_config():
    """Phase 1: Test configuration loading."""
    print("\n" + "=" * 60)
    print("TEST 1: Configuration Loading")
    print("=" * 60)

    from app.config import get_settings

    settings = get_settings()
    print(f"  LLM Provider:     {settings.llm_provider.value}")
    print(f"  OpenAI Model:     {settings.openai_model}")
    print(f"  Embedding Model:  {settings.openai_embedding_model}")
    print(f"  Vector Store:     {settings.vector_store.value}")
    print(f"  Chunk Size:       {settings.chunk_size}")
    print(f"  Chunk Overlap:    {settings.chunk_overlap}")
    print(f"  Top K:            {settings.retrieval_top_k}")

    api_key = settings.openai_api_key
    if not api_key or api_key.startswith("sk-YOUR"):
        print("\n  [WARNING] OpenAI API key not set! Edit .env to add your key.")
        print("  Tests requiring API calls will be skipped.")
        return settings, False

    print("  [OK] API key detected")
    return settings, True


def test_document_processor(settings):
    """Test PDF loading and chunking."""
    print("\n" + "=" * 60)
    print("TEST 2: Document Processing (PDF)")
    print("=" * 60)

    from app.services.document_processor import DocumentProcessor

    processor = DocumentProcessor(settings)
    chunks = processor.load_and_split(TEST_PDF_PATH)

    print(f"  Loaded -> {len(chunks)} chunks")
    print(f"  First chunk preview ({len(chunks[0].page_content)} chars):")
    print(f"    \"{chunks[0].page_content[:150]}...\"")
    print(f"  Metadata: {chunks[0].metadata}")
    print("  [OK] Document processing works")
    return chunks


def test_vector_store_chroma(settings, chunks):
    """Phase 2: Test ChromaDB vector store."""
    print("\n" + "=" * 60)
    print("TEST 3: Vector Store - ChromaDB")
    print("=" * 60)

    from app.vectorstore.chroma_store import ChromaStoreManager
    from app.llm.provider import create_embeddings

    embeddings = create_embeddings(settings)
    store = ChromaStoreManager(persist_directory=Path("data/vectorstore"))
    store.initialize(embeddings)

    # Add documents
    doc_id = "test_pdf_001"
    ids = store.add_documents(chunks, doc_id=doc_id)
    print(f"  Added {len(ids)} chunks with doc_id={doc_id}")

    # Search
    query = "What vector stores does MEINRAG support?"
    results = store.similarity_search(query, k=2)
    print(f"  Query: \"{query}\"")
    print(f"  Results: {len(results)} chunks returned")
    for i, doc in enumerate(results):
        print(f"    [{i+1}] ({doc.metadata.get('source_file', '?')}) "
              f"\"{doc.page_content[:100]}...\"")

    # Delete
    store.delete_document(doc_id)
    results_after = store.similarity_search(query, k=2)
    print(f"  After delete: {len(results_after)} chunks (should be 0)")
    print("  [OK] ChromaDB works")

    return embeddings


def test_vector_store_faiss(settings, chunks, embeddings):
    """Phase 2: Test FAISS vector store."""
    print("\n" + "=" * 60)
    print("TEST 4: Vector Store - FAISS")
    print("=" * 60)

    from app.vectorstore.faiss_store import FAISSStoreManager

    store = FAISSStoreManager(persist_directory=Path("data/vectorstore"))
    store.initialize(embeddings)

    # Add documents
    doc_id = "test_pdf_002"
    ids = store.add_documents(chunks, doc_id=doc_id)
    print(f"  Added {len(ids)} chunks with doc_id={doc_id}")

    # Search
    query = "What API endpoints are available?"
    results = store.similarity_search(query, k=2)
    print(f"  Query: \"{query}\"")
    print(f"  Results: {len(results)} chunks returned")
    for i, doc in enumerate(results):
        print(f"    [{i+1}] ({doc.metadata.get('source_file', '?')}) "
              f"\"{doc.page_content[:100]}...\"")

    # Test persistence
    store.persist()
    faiss_index = Path("data/vectorstore/faiss/index.faiss")
    print(f"  Persisted to disk: {faiss_index.exists()}")

    # Delete
    store.delete_document(doc_id)
    results_after = store.similarity_search(query, k=2)
    print(f"  After delete: {len(results_after)} chunks (should be 0)")
    print("  [OK] FAISS works")


def test_rag_chain(settings, chunks):
    """Phase 3: Test full RAG chain (end-to-end with LLM)."""
    print("\n" + "=" * 60)
    print("TEST 5: RAG Chain (end-to-end)")
    print("=" * 60)

    from app.llm.provider import create_chat_model, create_embeddings
    from app.vectorstore.chroma_store import ChromaStoreManager
    from app.rag.chain import build_rag_chain

    # Setup
    embeddings = create_embeddings(settings)
    store = ChromaStoreManager(persist_directory=Path("data/vectorstore"))
    store.initialize(embeddings)
    store.add_documents(chunks, doc_id="test_rag")

    llm = create_chat_model(settings)
    chain, retriever = build_rag_chain(store, llm, top_k=3)

    # Query
    question = "What are the three core architecture layers of MEINRAG?"
    print(f"  Question: \"{question}\"")
    print("  Calling LLM... (this may take a few seconds)")

    answer = chain.invoke(question)
    print(f"\n  Answer:\n  {answer[:500]}{'...' if len(answer) > 500 else ''}")

    # Cleanup
    store.delete_document("test_rag")
    print("\n  [OK] RAG chain works end-to-end!")


def test_factory(settings):
    """Test the vector store factory switching."""
    print("\n" + "=" * 60)
    print("TEST 6: Vector Store Factory (switchable)")
    print("=" * 60)

    from app.vectorstore.factory import create_vector_store_manager
    from app.config import VectorStoreType

    settings.vector_store = VectorStoreType.CHROMA
    store = create_vector_store_manager(settings)
    print(f"  VECTOR_STORE=chroma -> {type(store).__name__}")

    settings.vector_store = VectorStoreType.FAISS
    store = create_vector_store_manager(settings)
    print(f"  VECTOR_STORE=faiss  -> {type(store).__name__}")

    # Reset to default
    settings.vector_store = VectorStoreType.CHROMA
    print("  [OK] Factory switching works")


def cleanup():
    """Remove test artifacts."""
    for path in [
        Path("data/vectorstore/chroma"),
        Path("data/vectorstore/faiss"),
    ]:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    TEST_PDF_PATH.unlink(missing_ok=True)


def main():
    print("=" * 60)
    print("  MEINRAG - Phase 1/2/3 Test Suite")
    print("=" * 60)

    # Test 1: Config
    settings, has_api_key = test_config()

    # Test 6: Factory (no API key needed)
    test_factory(settings)

    # Generate test PDF
    print("\n" + "=" * 60)
    print("SETUP: Generating test PDF")
    print("=" * 60)
    create_test_pdf()

    # Test 2: Document processing
    chunks = test_document_processor(settings)

    if not has_api_key:
        print("\n[DONE] Skipped vector store and RAG tests (no API key).")
        print("Set OPENAI_API_KEY in .env and re-run for full test.")
        return

    # Test 3: ChromaDB (requires API key for embeddings)
    embeddings = test_vector_store_chroma(settings, chunks)

    # Test 4: FAISS
    test_vector_store_faiss(settings, chunks, embeddings)

    # Test 5: RAG chain (requires API key for LLM call)
    test_rag_chain(settings, chunks)

    # Cleanup test data
    cleanup()
    print("\n" + "=" * 60)
    print("  ALL TESTS PASSED! Cleaned up test artifacts.")
    print("=" * 60)


if __name__ == "__main__":
    main()
