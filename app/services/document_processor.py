import logging
from pathlib import Path

from langchain_core.documents import Document
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    UnstructuredMarkdownLoader,
    UnstructuredHTMLLoader,
    Docx2txtLoader,
)
from langchain_community.document_loaders import UnstructuredExcelLoader
from langchain_community.document_loaders import UnstructuredPowerPointLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import Settings

logger = logging.getLogger(__name__)

LOADER_MAP: dict[str, type] = {
    ".pdf": PyPDFLoader,
    ".txt": TextLoader,
    ".md": UnstructuredMarkdownLoader,
    ".html": UnstructuredHTMLLoader,
    ".htm": UnstructuredHTMLLoader,
    ".docx": Docx2txtLoader,
    ".xlsx": UnstructuredExcelLoader,
    ".xls": UnstructuredExcelLoader,
    ".pptx": UnstructuredPowerPointLoader,
    ".ppt": UnstructuredPowerPointLoader,
}

SUPPORTED_EXTENSIONS = set(LOADER_MAP.keys())


class DocumentProcessor:
    def __init__(self, settings: Settings):
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def load_and_split(self, file_path: Path) -> list[Document]:
        """Load a file and split it into chunks."""
        suffix = file_path.suffix.lower()
        loader_cls = LOADER_MAP.get(suffix)
        if loader_cls is None:
            raise ValueError(
                f"Unsupported file type: {suffix}. "
                f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        logger.info(f"Loading {file_path.name} with {loader_cls.__name__}")
        loader = loader_cls(str(file_path))
        documents = loader.load()

        logger.info(f"Loaded {len(documents)} page(s), splitting into chunks")
        chunks = self._splitter.split_documents(documents)
        logger.info(f"Split into {len(chunks)} chunk(s)")

        for i, chunk in enumerate(chunks):
            chunk.metadata["source_file"] = file_path.name
            chunk.metadata["chunk_index"] = i

        return chunks
