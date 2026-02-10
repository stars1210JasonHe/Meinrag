from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings

from app.config import Settings, LLMProvider


def create_chat_model(settings: Settings) -> BaseChatModel:
    """Create the appropriate chat model based on configuration."""
    if settings.llm_provider == LLMProvider.OPENAI:
        return ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=0,
        )
    elif settings.llm_provider == LLMProvider.OPENROUTER:
        return ChatOpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            model=settings.openrouter_model,
            temperature=0,
            default_headers={
                "HTTP-Referer": settings.openrouter_site_url,
                "X-Title": settings.openrouter_site_name,
            },
        )
    else:
        raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")


def create_embeddings(settings: Settings) -> Embeddings:
    """Create embeddings model.

    Always uses OpenAI embeddings — even with OpenRouter for chat,
    because OpenRouter does not reliably support embedding endpoints,
    and mixing embedding models would break vector store compatibility.
    """
    return OpenAIEmbeddings(
        api_key=settings.openai_api_key,
        model=settings.openai_embedding_model,
    )
