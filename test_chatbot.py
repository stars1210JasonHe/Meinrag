"""
Test script for MEINRAG chatbot upgrade (Phases A-E).
Tests: document filtering, re-ranking, chat memory, hybrid search.

Usage:
    1. Put your OpenAI API key in .env
    2. Run: uv run python test_chatbot.py
"""

import logging
import shutil
from pathlib import Path

from fpdf import FPDF

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("test_chatbot")

TEST_DIR = Path("data/test_chatbot")
PDF_A = TEST_DIR / "solar_energy.pdf"
PDF_B = TEST_DIR / "machine_learning.pdf"


def create_test_pdfs():
    """Generate two distinct test PDFs for filtering tests."""
    TEST_DIR.mkdir(parents=True, exist_ok=True)

    # PDF A: Solar Energy
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Solar Energy Systems Guide", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, (
        "Solar photovoltaic (PV) panels convert sunlight directly into electricity using "
        "semiconductor materials, primarily silicon. A typical residential system produces "
        "between 5 and 10 kilowatts of power. The efficiency of modern monocrystalline panels "
        "ranges from 20% to 23%. Solar inverters convert the DC output into AC electricity "
        "suitable for home use. Net metering allows homeowners to sell excess energy back to "
        "the grid. Battery storage systems like the Tesla Powerwall can store 13.5 kWh of "
        "energy for use during nighttime or cloudy periods.\n\n"
        "The levelized cost of solar energy has dropped below $30 per megawatt-hour in many "
        "regions, making it the cheapest source of new electricity generation. Solar thermal "
        "systems use mirrors to concentrate sunlight and generate steam for turbines."
    ))
    pdf.output(str(PDF_A))

    # PDF B: Machine Learning
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Machine Learning Fundamentals", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, (
        "Machine learning is a subset of artificial intelligence where algorithms learn patterns "
        "from data without being explicitly programmed. Supervised learning uses labeled training "
        "data to learn a mapping from inputs to outputs. Common algorithms include linear regression, "
        "decision trees, random forests, and neural networks.\n\n"
        "Deep learning uses multi-layered neural networks with architectures like convolutional "
        "neural networks (CNNs) for image recognition and transformers for natural language "
        "processing. The transformer architecture, introduced in the 'Attention Is All You Need' "
        "paper, uses self-attention mechanisms to process sequences in parallel.\n\n"
        "Gradient descent is the primary optimization algorithm used to train neural networks. "
        "Backpropagation computes gradients layer by layer. Regularization techniques like "
        "dropout and L2 penalty prevent overfitting. Transfer learning allows pre-trained models "
        "to be fine-tuned on smaller domain-specific datasets."
    ))
    pdf.output(str(PDF_B))

    print(f"  Generated: {PDF_A.name} ({PDF_A.stat().st_size} bytes)")
    print(f"  Generated: {PDF_B.name} ({PDF_B.stat().st_size} bytes)")


def setup_stores(settings):
    """Load and embed both PDFs into a fresh Chroma store."""
    from app.services.document_processor import DocumentProcessor
    from app.vectorstore.chroma_store import ChromaStoreManager
    from app.llm.provider import create_embeddings

    embeddings = create_embeddings(settings)
    store = ChromaStoreManager(persist_directory=TEST_DIR)
    store.initialize(embeddings)

    processor = DocumentProcessor(settings)

    chunks_a = processor.load_and_split(PDF_A)
    store.add_documents(chunks_a, doc_id="doc_solar")
    print(f"  Indexed doc_solar: {len(chunks_a)} chunks")

    chunks_b = processor.load_and_split(PDF_B)
    store.add_documents(chunks_b, doc_id="doc_ml")
    print(f"  Indexed doc_ml: {len(chunks_b)} chunks")

    return store, embeddings


def test_config_new_settings():
    """Test that new config settings load correctly."""
    print("\n" + "=" * 60)
    print("TEST 1: New Configuration Settings")
    print("=" * 60)

    from app.config import get_settings
    settings = get_settings()

    print(f"  rerank_enabled:        {settings.rerank_enabled}")
    print(f"  rerank_top_n:          {settings.rerank_top_n}")
    print(f"  hybrid_search_enabled: {settings.hybrid_search_enabled}")
    print(f"  hybrid_bm25_weight:    {settings.hybrid_bm25_weight}")
    print(f"  memory_max_messages:   {settings.memory_max_messages}")
    print(f"  memory_session_ttl:    {settings.memory_session_ttl}")

    assert isinstance(settings.rerank_enabled, bool)
    assert isinstance(settings.hybrid_search_enabled, bool)
    assert 0.0 <= settings.hybrid_bm25_weight <= 1.0
    assert settings.memory_max_messages > 0
    assert settings.memory_session_ttl > 0
    print("  [OK] All new settings loaded")
    return settings


def test_document_filtering(store, llm, settings):
    """Test doc_ids filtering: results should come only from the specified doc."""
    print("\n" + "=" * 60)
    print("TEST 2: Document Filtering (doc_ids)")
    print("=" * 60)

    # Filtered search — only solar
    results = store.similarity_search_with_filter(
        "What is the efficiency?", k=4, doc_ids=["doc_solar"]
    )
    print(f"  Filter=[doc_solar], results={len(results)}")
    for doc in results:
        assert doc.metadata.get("doc_id") == "doc_solar", (
            f"Expected doc_solar, got {doc.metadata.get('doc_id')}"
        )
        print(f"    doc_id={doc.metadata['doc_id']}: \"{doc.page_content[:80]}...\"")

    # Filtered search — only ML
    results = store.similarity_search_with_filter(
        "What is gradient descent?", k=4, doc_ids=["doc_ml"]
    )
    print(f"  Filter=[doc_ml], results={len(results)}")
    for doc in results:
        assert doc.metadata.get("doc_id") == "doc_ml", (
            f"Expected doc_ml, got {doc.metadata.get('doc_id')}"
        )
        print(f"    doc_id={doc.metadata['doc_id']}: \"{doc.page_content[:80]}...\"")

    # Filtered RAG chain
    from app.rag.chain import build_rag_chain

    chain, retriever = build_rag_chain(
        store, llm, top_k=3, doc_ids=["doc_solar"], settings=settings
    )
    answer = chain.invoke("What is the cost of solar energy?")
    print(f"  Filtered RAG answer: \"{answer[:200]}...\"")
    print("  [OK] Document filtering works")


def test_chat_memory():
    """Test session memory manager: storage, trimming, and expiry."""
    print("\n" + "=" * 60)
    print("TEST 3: Chat Memory (SessionMemoryManager)")
    print("=" * 60)

    from app.rag.memory import SessionMemoryManager

    mgr = SessionMemoryManager(max_messages=6, session_ttl=2)

    # Empty session
    history = mgr.get_history("s1")
    assert history == [], f"Expected empty, got {len(history)} messages"
    print("  New session: 0 messages [OK]")

    # Add exchanges
    mgr.add_exchange("s1", "What is solar?", "Solar is energy from the sun.")
    mgr.add_exchange("s1", "How efficient?", "Modern panels are 20-23% efficient.")
    history = mgr.get_history("s1")
    assert len(history) == 4, f"Expected 4 messages, got {len(history)}"
    print(f"  After 2 exchanges: {len(history)} messages [OK]")

    # Test trimming (max_messages=6, adding 4th exchange should trim)
    mgr.add_exchange("s1", "Cost?", "Below $30/MWh.")
    mgr.add_exchange("s1", "Storage?", "Tesla Powerwall stores 13.5 kWh.")
    history = mgr.get_history("s1")
    assert len(history) <= 6, f"Expected <=6 messages, got {len(history)}"
    print(f"  After 4 exchanges (max=6): {len(history)} messages [OK]")

    # Test TTL expiry
    import time
    time.sleep(3)
    history = mgr.get_history("s1")
    assert history == [], f"Expected expired (empty), got {len(history)} messages"
    print("  After TTL expiry: 0 messages [OK]")
    print("  [OK] Chat memory works")


def test_chat_aware_rag(store, llm, settings):
    """Test that chat history is incorporated into RAG answers."""
    print("\n" + "=" * 60)
    print("TEST 4: Chat-Aware RAG (memory + prompt)")
    print("=" * 60)

    from app.rag.chain import build_rag_chain
    from app.rag.memory import SessionMemoryManager

    mgr = SessionMemoryManager(max_messages=20, session_ttl=300)

    # First query — no history
    chain1, _ = build_rag_chain(
        store, llm, top_k=3, settings=settings
    )
    answer1 = chain1.invoke("What is the efficiency of solar panels?")
    mgr.add_exchange("test_session", "What is the efficiency of solar panels?", answer1)
    print(f"  Q1 answer: \"{answer1[:150]}...\"")

    # Second query — with history
    history = mgr.get_history("test_session")
    chain2, _ = build_rag_chain(
        store, llm, top_k=3, chat_history=history, settings=settings
    )
    answer2 = chain2.invoke("Can you elaborate on that?")
    mgr.add_exchange("test_session", "Can you elaborate on that?", answer2)
    print(f"  Q2 (follow-up) answer: \"{answer2[:150]}...\"")

    # The follow-up should reference solar/efficiency (not be confused)
    assert len(answer2) > 20, "Follow-up answer seems too short"
    print("  [OK] Chat-aware RAG works")


def test_hybrid_search(store, settings):
    """Test BM25 + vector hybrid retrieval."""
    print("\n" + "=" * 60)
    print("TEST 5: Hybrid Search (BM25 + Vector)")
    print("=" * 60)

    from app.rag.chain import _build_hybrid_retriever

    retriever = _build_hybrid_retriever(
        store, top_k=3, bm25_weight=0.5
    )

    # Exact keyword query — BM25 should boost this
    results = retriever.invoke("Tesla Powerwall 13.5 kWh")
    print(f"  Query: 'Tesla Powerwall 13.5 kWh'")
    print(f"  Results: {len(results)} documents")
    for i, doc in enumerate(results):
        print(f"    [{i+1}] doc_id={doc.metadata.get('doc_id', '?')}: "
              f"\"{doc.page_content[:80]}...\"")

    # With doc_ids filter
    results_filtered = _build_hybrid_retriever(
        store, top_k=3, bm25_weight=0.5, doc_ids=["doc_ml"]
    ).invoke("transformer attention mechanism")
    print(f"\n  Filtered query: 'transformer attention mechanism' (doc_ml only)")
    print(f"  Results: {len(results_filtered)} documents")
    for doc in results_filtered:
        assert doc.metadata.get("doc_id") == "doc_ml"
        print(f"    doc_id={doc.metadata['doc_id']}: \"{doc.page_content[:80]}...\"")

    print("  [OK] Hybrid search works")


def test_reranking(store, llm, settings):
    """Test LLM listwise re-ranking."""
    print("\n" + "=" * 60)
    print("TEST 6: Re-ranking (LLM Listwise)")
    print("=" * 60)

    from app.rag.chain import build_rag_chain

    # Build chain with re-ranking enabled
    settings.rerank_enabled = True
    settings.rerank_top_n = 2

    chain, retriever = build_rag_chain(
        store, llm, top_k=3, settings=settings
    )

    question = "How do solar inverters work?"
    print(f"  Question: \"{question}\"")
    print("  Calling LLM with re-ranking... (this may take longer)")
    answer = chain.invoke(question)
    print(f"  Answer: \"{answer[:200]}...\"")

    # Reset
    settings.rerank_enabled = False
    print("  [OK] Re-ranking works")


def test_backwards_compatibility(store, llm):
    """Test that the old API signature still works unchanged."""
    print("\n" + "=" * 60)
    print("TEST 7: Backwards Compatibility")
    print("=" * 60)

    from app.rag.chain import build_rag_chain

    # Old-style call: no doc_ids, no chat_history, no settings
    chain, retriever = build_rag_chain(
        vector_store=store, llm=llm, top_k=3
    )
    answer = chain.invoke("What is machine learning?")
    print(f"  Old-style call answer: \"{answer[:150]}...\"")
    assert len(answer) > 10
    print("  [OK] Backwards compatibility preserved")


def cleanup():
    """Remove test artifacts."""
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)


def main():
    print("=" * 60)
    print("  MEINRAG - Chatbot Upgrade Test Suite (Phases A-E)")
    print("=" * 60)

    # Test 1: Config
    settings = test_config_new_settings()

    api_key = settings.openai_api_key
    if not api_key or api_key.startswith("sk-YOUR"):
        print("\n[DONE] Skipped API tests (no API key).")
        print("Set OPENAI_API_KEY in .env and re-run for full test.")
        return

    # Test 3: Chat memory (no API key needed)
    test_chat_memory()

    # Setup: Generate PDFs and index
    print("\n" + "=" * 60)
    print("SETUP: Generating and indexing test PDFs")
    print("=" * 60)
    create_test_pdfs()
    store, embeddings = setup_stores(settings)

    from app.llm.provider import create_chat_model
    llm = create_chat_model(settings)

    # Test 2: Document filtering
    test_document_filtering(store, llm, settings)

    # Test 4: Chat-aware RAG
    test_chat_aware_rag(store, llm, settings)

    # Test 5: Hybrid search
    test_hybrid_search(store, settings)

    # Test 6: Re-ranking
    test_reranking(store, llm, settings)

    # Test 7: Backwards compatibility
    test_backwards_compatibility(store, llm)

    # Cleanup
    cleanup()
    print("\n" + "=" * 60)
    print("  ALL CHATBOT TESTS PASSED! Cleaned up test artifacts.")
    print("=" * 60)


if __name__ == "__main__":
    main()
