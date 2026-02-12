"""B3: RAG Chain tests - Requires API key."""
import shutil

import pytest

from app.llm.provider import create_chat_model, create_embeddings
from app.rag.chain import build_rag_chain
from app.services.document_processor import DocumentProcessor
from app.vectorstore.chroma_store import ChromaStoreManager
from tests.conftest import online, TEST_DIR, PDF_AI_SAFETY, PDF_PATTERNS


@pytest.fixture(scope="module")
def rag_env():
    """Set up store + LLM with two indexed documents."""
    from app.config import Settings
    settings = Settings()

    store_dir = TEST_DIR / "b3_vectorstore"
    store_dir.mkdir(parents=True, exist_ok=True)

    embeddings = create_embeddings(settings)
    store = ChromaStoreManager(persist_directory=store_dir)
    store.initialize(embeddings)
    llm = create_chat_model(settings)

    processor = DocumentProcessor(settings)

    chunks_ai = processor.load_and_split(PDF_AI_SAFETY)
    for c in chunks_ai:
        c.metadata["collection"] = "research"
    store.add_documents(chunks_ai, doc_id="doc_ai")

    chunks_pat = processor.load_and_split(PDF_PATTERNS)
    for c in chunks_pat:
        c.metadata["collection"] = "computer-science"
    store.add_documents(chunks_pat, doc_id="doc_pat")

    yield {
        "store": store,
        "llm": llm,
        "settings": settings,
    }

    store.delete_document("doc_ai")
    store.delete_document("doc_pat")
    shutil.rmtree(store_dir, ignore_errors=True)


@online
class TestRAGChainBasic:
    """B3.1 - B3.2: Basic chain and filtering."""

    def test_basic_chain(self, rag_env):
        """B3.1: Basic chain returns a string answer."""
        chain, _ = build_rag_chain(
            rag_env["store"], rag_env["llm"], top_k=3, settings=rag_env["settings"]
        )
        answer = chain.invoke("What is this benchmark about?")
        assert isinstance(answer, str)
        assert len(answer) > 20

    def test_chain_with_doc_filter(self, rag_env):
        """B3.2: Chain with doc_ids filter answers from that doc."""
        chain, _ = build_rag_chain(
            rag_env["store"], rag_env["llm"], top_k=3,
            doc_ids=["doc_ai"], settings=rag_env["settings"]
        )
        answer = chain.invoke("What safety concerns are discussed?")
        assert isinstance(answer, str)
        assert len(answer) > 20

    def test_chain_with_doc_ids_filter(self, rag_env):
        """B3.3: Chain with doc_ids filter."""
        chain, _ = build_rag_chain(
            rag_env["store"], rag_env["llm"], top_k=3,
            doc_ids=["doc_patterns"], settings=rag_env["settings"]
        )
        answer = chain.invoke("How are patterns discovered from simulation traces?")
        assert isinstance(answer, str)
        assert len(answer) > 20


@online
class TestRAGChainChat:
    """B3.4: Chat history support."""

    def test_chain_with_chat_history(self, rag_env):
        """B3.4: Follow-up question references prior context."""
        from langchain_core.messages import HumanMessage, AIMessage

        # First question
        chain1, _ = build_rag_chain(
            rag_env["store"], rag_env["llm"], top_k=3, settings=rag_env["settings"]
        )
        answer1 = chain1.invoke("What is the main contribution of the AI safety paper?")

        # Follow-up with history
        history = [
            HumanMessage(content="What is the main contribution of the AI safety paper?"),
            AIMessage(content=answer1),
        ]
        chain2, _ = build_rag_chain(
            rag_env["store"], rag_env["llm"], top_k=3,
            chat_history=history, settings=rag_env["settings"]
        )
        answer2 = chain2.invoke("Can you explain more about that?")
        assert isinstance(answer2, str)
        assert len(answer2) > 20


@online
class TestRAGChainBackwardsCompat:
    """B3.5: Backwards compatibility."""

    def test_old_style_call(self, rag_env):
        """B3.5: Works with (vector_store, llm, top_k) only."""
        chain, retriever = build_rag_chain(
            vector_store=rag_env["store"],
            llm=rag_env["llm"],
            top_k=3,
        )
        answer = chain.invoke("What topics are covered in the documents?")
        assert isinstance(answer, str)
        assert len(answer) > 10
