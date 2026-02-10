from app.config import Settings, VectorStoreType
from app.vectorstore.base import VectorStoreManager
from app.vectorstore.chroma_store import ChromaStoreManager
from app.vectorstore.faiss_store import FAISSStoreManager


def create_vector_store_manager(settings: Settings) -> VectorStoreManager:
    if settings.vector_store == VectorStoreType.CHROMA:
        return ChromaStoreManager(persist_directory=settings.vectorstore_dir)
    elif settings.vector_store == VectorStoreType.FAISS:
        return FAISSStoreManager(persist_directory=settings.vectorstore_dir)
    else:
        raise ValueError(f"Unknown vector store type: {settings.vector_store}")
