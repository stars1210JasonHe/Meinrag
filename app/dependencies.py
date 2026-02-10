from fastapi import Request

from app.config import Settings
from app.models.document import DocumentRegistry
from app.rag.memory import SessionMemoryManager
from app.vectorstore.base import VectorStoreManager
from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_vector_store(request: Request) -> VectorStoreManager:
    return request.app.state.vector_store


def get_llm(request: Request) -> BaseChatModel:
    return request.app.state.llm


def get_embeddings(request: Request) -> Embeddings:
    return request.app.state.embeddings


def get_registry(request: Request) -> DocumentRegistry:
    return request.app.state.registry


def get_memory_manager(request: Request) -> SessionMemoryManager:
    return request.app.state.memory_manager
