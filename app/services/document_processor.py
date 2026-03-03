import base64
import json
import logging
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
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

from app.config import Settings, ParseMode

logger = logging.getLogger(__name__)

LOADER_MAP: dict[str, type | None] = {
    ".pdf": PyPDFLoader,
    ".txt": TextLoader,
    ".md": UnstructuredMarkdownLoader,
    ".html": UnstructuredHTMLLoader,
    ".htm": UnstructuredHTMLLoader,
    ".docx": Docx2txtLoader,
    ".doc": None,  # Handled via LibreOffice conversion
    ".xlsx": UnstructuredExcelLoader,
    ".xls": UnstructuredExcelLoader,
    ".pptx": UnstructuredPowerPointLoader,
    ".ppt": UnstructuredPowerPointLoader,
}

SUPPORTED_EXTENSIONS = set(LOADER_MAP.keys())


def _check_libreoffice_available() -> bool:
    """Check if LibreOffice (soffice) is available on PATH."""
    return shutil.which("soffice") is not None


class DocumentProcessor:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def load_and_split(self, file_path: Path, doc_id: str | None = None) -> list[Document]:
        """Load a file and split it into chunks."""
        suffix = file_path.suffix.lower()

        # Strip doc_id prefix from filename for clean display in citations
        # Files are saved as "{doc_id}_{original_name}" on disk
        clean_name = file_path.name
        if doc_id and clean_name.startswith(f"{doc_id}_"):
            clean_name = clean_name[len(doc_id) + 1:]
        self._clean_name = clean_name

        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {suffix}. "
                f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        parse_mode = self._settings.parse_mode

        # === VISION MODE (any file type) ===
        if parse_mode == ParseMode.VISION:
            try:
                return self._load_vision(file_path, doc_id)
            except Exception as e:
                logger.warning(f"Vision mode failed, falling back to enhanced/default: {e}")
                parse_mode = ParseMode.ENHANCED  # fall through

        # === ENHANCED MODE (PDF only) ===
        if parse_mode == ParseMode.ENHANCED and suffix == ".pdf":
            try:
                return self._load_pdf_enhanced(file_path, doc_id)
            except Exception as e:
                logger.warning(f"Enhanced PDF processing failed, falling back to default: {e}")
                # fall through to default

        # === DEFAULT MODE ===
        # .doc files need LibreOffice even in default mode
        if suffix == ".doc":
            return self._load_doc_default(file_path)

        loader_cls = LOADER_MAP.get(suffix)
        if loader_cls is None:
            raise ValueError(f"No loader available for {suffix}")

        logger.info(f"Loading {file_path.name} with {loader_cls.__name__}")
        loader = loader_cls(str(file_path))
        documents = loader.load()

        logger.info(f"Loaded {len(documents)} page(s), splitting into chunks")
        chunks = self._splitter.split_documents(documents)
        logger.info(f"Split into {len(chunks)} chunk(s)")

        for i, chunk in enumerate(chunks):
            chunk.metadata["source_file"] = self._clean_name
            chunk.metadata["chunk_index"] = i
            chunk.metadata["chunk_type"] = "text"

        return chunks

    # ========================================
    # VISION MODE
    # ========================================

    def _load_vision(self, file_path: Path, doc_id: str | None = None) -> list[Document]:
        """Vision mode: render every page as image, send to vision LLM, get markdown.

        Works for any supported file type:
        - PDF: opens directly with PyMuPDF
        - All others: converts to PDF via LibreOffice first
        """
        import fitz  # PyMuPDF

        suffix = file_path.suffix.lower()
        converted_tmp_dir: Path | None = None

        # Step 1: Get a PDF to work with
        if suffix == ".pdf":
            pdf_path = file_path
        else:
            if not _check_libreoffice_available():
                raise RuntimeError(
                    f"LibreOffice (soffice) is required for vision mode with {suffix} files "
                    f"but was not found on PATH. Install LibreOffice or use PARSE_MODE=default."
                )
            logger.info(f"Converting {file_path.name} to PDF via LibreOffice")
            converted_pdf_path = self._convert_to_pdf(file_path)
            converted_tmp_dir = converted_pdf_path.parent
            pdf_path = converted_pdf_path

        try:
            pdf_doc = fitz.open(str(pdf_path))
            total_pages = len(pdf_doc)
            dpi = self._settings.vision_page_dpi
            logger.info(f"Vision mode: processing {file_path.name} ({total_pages} pages at {dpi} DPI)")

            # Create vision LLM once for all pages
            vision_llm = self._create_vision_llm()

            # Step 2: Render all pages to base64 (CPU-bound, done in main thread)
            rendered_pages: list[tuple[int, str, str]] = []  # (page_num, b64, fallback_text)
            for page_num in range(total_pages):
                page = pdf_doc[page_num]
                page_b64 = self._render_page_to_base64(page, dpi=dpi)
                fallback_text = page.get_text("text").strip()
                rendered_pages.append((page_num, page_b64, fallback_text))

            pdf_doc.close()

            # Step 3: Send to vision LLM concurrently (IO-bound)
            max_workers = min(5, total_pages)
            all_page_markdowns: list[tuple[int, str]] = []

            def _describe_page(args: tuple[int, str, str]) -> tuple[int, str]:
                page_num, page_b64, fallback_text = args
                try:
                    markdown = self._vision_describe_page(page_b64, page_num, total_pages, vision_llm)
                    logger.debug(f"Vision: page {page_num + 1}/{total_pages} -> {len(markdown)} chars")
                    return (page_num, markdown)
                except Exception as e:
                    logger.warning(
                        f"Vision failed for page {page_num + 1}/{total_pages}: {e}. "
                        f"Falling back to text extraction."
                    )
                    return (page_num, fallback_text)

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(_describe_page, rp): rp[0] for rp in rendered_pages}
                for future in as_completed(futures):
                    page_num, markdown = future.result()
                    if markdown.strip():
                        all_page_markdowns.append((page_num, markdown))

            # Sort by page number to maintain order
            all_page_markdowns.sort(key=lambda x: x[0])

            # Step 4: Segment and chunk each page's markdown
            images_dir = None
            if doc_id:
                images_dir = self._settings.upload_dir / doc_id / "images"
                images_dir.mkdir(parents=True, exist_ok=True)

            # Build page render lookup for fallback image saving
            page_renders: dict[int, str] = {}
            for page_num, page_b64, _ in rendered_pages:
                page_renders[page_num] = page_b64

            all_chunks: list[Document] = []
            text_count = table_count = image_count = 0

            # Pre-extract bounding boxes for all pages from the PDF
            page_bboxes: dict[int, dict] = {}
            if suffix == ".pdf":
                for page_num, _ in all_page_markdowns:
                    try:
                        page_bboxes[page_num] = self._extract_page_bboxes(
                            str(pdf_path), page_num
                        )
                    except Exception as e:
                        logger.debug(f"BBox extraction failed for page {page_num}: {e}")

            for page_num, page_markdown in all_page_markdowns:
                segments = self._separate_content_segments(page_markdown)
                bboxes = page_bboxes.get(page_num, {"tables": [], "images": []})
                page_table_idx = 0
                page_img_idx = 0

                for content, chunk_type in segments:
                    content = content.strip()
                    if not content:
                        continue

                    base_meta = {
                        "source_file": self._clean_name,
                        "page": page_num,
                        "parse_mode": "vision",
                    }

                    if chunk_type == "text":
                        text_docs = self._splitter.split_documents([
                            Document(page_content=content, metadata=base_meta.copy())
                        ])
                        for d in text_docs:
                            d.metadata["chunk_type"] = "text"
                            all_chunks.append(d)
                            text_count += 1

                    elif chunk_type == "table":
                        bbox = None
                        if page_table_idx < len(bboxes["tables"]):
                            bbox = json.dumps(bboxes["tables"][page_table_idx])
                        page_table_idx += 1
                        table_parts = self._split_large_table(content, self._settings.chunk_size * 3)
                        for part in table_parts:
                            meta = {**base_meta, "chunk_type": "table"}
                            if bbox:
                                meta["bbox"] = bbox
                            d = Document(page_content=part, metadata=meta)
                            all_chunks.append(d)
                            table_count += 1

                    elif chunk_type == "image":
                        description = self._extract_image_description(content)
                        meta = {**base_meta, "chunk_type": "image"}
                        bbox = None
                        if page_img_idx < len(bboxes["images"]):
                            bbox = json.dumps(bboxes["images"][page_img_idx])
                        if bbox:
                            meta["bbox"] = bbox
                        if images_dir and doc_id:
                            image_path = self._save_image_from_content(
                                content, images_dir, doc_id, page_num, page_img_idx
                            )
                            # Fallback: save the rendered page image
                            if not image_path and page_num in page_renders:
                                image_path = self._save_page_render(
                                    page_renders[page_num], images_dir, doc_id,
                                    page_num, page_img_idx,
                                )
                            if image_path:
                                meta["image_path"] = image_path
                        page_img_idx += 1
                        d = Document(page_content=description, metadata=meta)
                        all_chunks.append(d)
                        image_count += 1

            # Step 5: Set chunk indices
            for i, chunk in enumerate(all_chunks):
                chunk.metadata["chunk_index"] = i

            logger.info(
                f"Vision mode: {len(all_chunks)} chunks "
                f"({text_count} text, {table_count} table, {image_count} image) "
                f"from {total_pages} pages"
            )
            return all_chunks

        finally:
            if converted_tmp_dir and converted_tmp_dir.exists():
                shutil.rmtree(converted_tmp_dir, ignore_errors=True)

    def _convert_to_pdf(self, file_path: Path) -> Path:
        """Convert any document to PDF using LibreOffice headless mode.

        Returns the path to the generated PDF. Caller is responsible for cleanup
        of the parent temp directory.
        """
        if not _check_libreoffice_available():
            raise RuntimeError("LibreOffice (soffice) not found on PATH.")

        # Validate file_path resolves within upload directory
        resolved = file_path.resolve()
        upload_root = self._settings.upload_dir.resolve()
        if not str(resolved).startswith(str(upload_root)):
            raise ValueError(f"File path outside upload directory: {file_path}")

        tmp_dir = Path(tempfile.mkdtemp(prefix="meinrag_lo_"))
        try:
            result = subprocess.run(
                [
                    "soffice", "--headless", "--norestore",
                    "--convert-to", "pdf",
                    "--outdir", str(tmp_dir),
                    str(file_path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                raise RuntimeError(f"LibreOffice conversion failed: {result.stderr.strip()}")

            expected_pdf = tmp_dir / (file_path.stem + ".pdf")
            if not expected_pdf.exists():
                pdfs = list(tmp_dir.glob("*.pdf"))
                if not pdfs:
                    raise RuntimeError(f"LibreOffice produced no PDF for {file_path.name}")
                expected_pdf = pdfs[0]

            logger.info(f"Converted {file_path.name} to PDF ({expected_pdf.stat().st_size // 1024} KB)")
            return expected_pdf

        except subprocess.TimeoutExpired:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise RuntimeError(f"LibreOffice conversion timed out for {file_path.name}")
        except Exception:
            if not any(tmp_dir.glob("*.pdf")):
                shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    @staticmethod
    def _render_page_to_base64(page, dpi: int = 150) -> str:
        """Render a PyMuPDF page to a base64-encoded PNG string."""
        pixmap = page.get_pixmap(dpi=dpi)
        png_bytes = pixmap.tobytes("png")
        return base64.b64encode(png_bytes).decode("ascii")

    def _create_vision_llm(self):
        """Create a single vision LLM instance for reuse across pages."""
        from langchain_openai import ChatOpenAI

        if not self._settings.openai_api_key:
            raise RuntimeError("OpenAI API key required for vision mode")

        return ChatOpenAI(
            model=self._settings.vision_model,
            max_tokens=self._settings.vision_max_tokens,
            api_key=self._settings.openai_api_key,
        )

    def _vision_describe_page(self, page_b64: str, page_num: int, total_pages: int, vision_llm=None) -> str:
        """Send a rendered page image to a vision LLM and get structured markdown back."""
        from langchain_core.messages import HumanMessage

        if vision_llm is None:
            vision_llm = self._create_vision_llm()

        prompt_text = (
            f"Convert this document page (page {page_num + 1} of {total_pages}) to well-structured markdown.\n"
            "Rules:\n"
            "- Preserve all text content accurately\n"
            "- Format tables using markdown table syntax (| header | ... | with |---| separator)\n"
            "- Describe any images, charts, diagrams, or figures using ![description](image) syntax\n"
            "- Preserve headings, lists, bold, italic formatting\n"
            "- For mathematical equations, use LaTeX notation: $inline$ or $$block$$\n"
            "- Do NOT add commentary — output ONLY the page content as markdown"
        )

        message = HumanMessage(content=[
            {"type": "text", "text": prompt_text},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{page_b64}"}},
        ])

        response = vision_llm.invoke([message])
        return response.content

    # ========================================
    # DOC DEFAULT MODE (LibreOffice + PyPDF)
    # ========================================

    def _load_doc_default(self, file_path: Path) -> list[Document]:
        """Load .doc files by converting to PDF via LibreOffice, then using PyPDFLoader."""
        if not _check_libreoffice_available():
            raise ValueError(
                "LibreOffice (soffice) is required to process .doc files but was not found. "
                "Install LibreOffice and ensure 'soffice' is on PATH."
            )

        pdf_path = self._convert_to_pdf(file_path)
        try:
            loader = PyPDFLoader(str(pdf_path))
            documents = loader.load()

            chunks = self._splitter.split_documents(documents)
            for i, chunk in enumerate(chunks):
                chunk.metadata["source_file"] = self._clean_name  # original name
                chunk.metadata["chunk_index"] = i
                chunk.metadata["chunk_type"] = "text"

            logger.info(f"Loaded .doc via LibreOffice: {len(chunks)} chunks")
            return chunks
        finally:
            if pdf_path.exists():
                shutil.rmtree(pdf_path.parent, ignore_errors=True)

    # ========================================
    # ENHANCED MODE (PDF only, PyMuPDF)
    # ========================================

    def _load_pdf_enhanced(self, file_path: Path, doc_id: str | None = None) -> list[Document]:
        """Load PDF with PyMuPDF for table and image extraction."""
        from langchain_community.document_loaders import PyMuPDFLoader

        logger.info(f"Loading {file_path.name} with PyMuPDFLoader (enhanced mode)")

        loader_kwargs = {
            "mode": "page",
            "extract_tables": "markdown",
        }

        # Add image extraction if OpenAI API key is available
        if self._settings.openai_api_key:
            try:
                from langchain_community.document_loaders.parsers import LLMImageBlobParser
                from langchain_openai import ChatOpenAI

                image_llm = ChatOpenAI(
                    model=self._settings.image_description_model,
                    max_tokens=self._settings.image_description_max_tokens,
                    api_key=self._settings.openai_api_key,
                )
                image_parser = LLMImageBlobParser(model=image_llm)
                loader_kwargs["images_inner_format"] = "markdown-img"
                loader_kwargs["extract_images"] = True
                logger.info("Image extraction enabled with LLM descriptions")
            except Exception as e:
                logger.warning(f"Could not set up image extraction: {e}")

        loader = PyMuPDFLoader(str(file_path), **loader_kwargs)
        pages = loader.load()
        logger.info(f"Loaded {len(pages)} page(s) with PyMuPDF")

        # Create image storage directory if needed
        images_dir = None
        if doc_id:
            images_dir = self._settings.upload_dir / doc_id / "images"
            images_dir.mkdir(parents=True, exist_ok=True)

        all_chunks: list[Document] = []
        text_count = table_count = image_count = 0

        # Pre-extract bounding boxes for all pages
        page_bboxes: dict[int, dict] = {}
        for pg in pages:
            pn = pg.metadata.get("page", 0)
            if pn not in page_bboxes:
                try:
                    page_bboxes[pn] = self._extract_page_bboxes(str(file_path), pn)
                except Exception as e:
                    logger.debug(f"BBox extraction failed for page {pn}: {e}")

        for page in pages:
            page_num = page.metadata.get("page", 0)
            segments = self._separate_content_segments(page.page_content)
            bboxes = page_bboxes.get(page_num, {"tables": [], "images": []})
            page_table_idx = 0
            page_img_idx = 0

            for content, chunk_type in segments:
                content = content.strip()
                if not content:
                    continue

                if chunk_type == "text":
                    text_docs = self._splitter.split_documents([
                        Document(page_content=content, metadata=page.metadata.copy())
                    ])
                    for doc in text_docs:
                        doc.metadata["chunk_type"] = "text"
                        all_chunks.append(doc)
                        text_count += 1

                elif chunk_type == "table":
                    bbox = None
                    if page_table_idx < len(bboxes["tables"]):
                        bbox = json.dumps(bboxes["tables"][page_table_idx])
                    page_table_idx += 1
                    table_parts = self._split_large_table(content, self._settings.chunk_size * 3)
                    for part in table_parts:
                        meta = {**page.metadata, "chunk_type": "table"}
                        if bbox:
                            meta["bbox"] = bbox
                        doc = Document(page_content=part, metadata=meta)
                        all_chunks.append(doc)
                        table_count += 1

                elif chunk_type == "image":
                    image_path = None
                    meta = {**page.metadata, "chunk_type": "image"}
                    bbox = None
                    if page_img_idx < len(bboxes["images"]):
                        bbox = json.dumps(bboxes["images"][page_img_idx])
                    if bbox:
                        meta["bbox"] = bbox
                    if images_dir and doc_id:
                        image_path = self._save_image_from_content(
                            content, images_dir, doc_id, page_num, page_img_idx
                        )
                    page_img_idx += 1
                    if image_path:
                        meta["image_path"] = image_path

                    description = self._extract_image_description(content)
                    doc = Document(page_content=description, metadata=meta)
                    all_chunks.append(doc)
                    image_count += 1

        for i, chunk in enumerate(all_chunks):
            chunk.metadata["source_file"] = self._clean_name
            chunk.metadata["chunk_index"] = i

        logger.info(
            f"Enhanced PDF: {len(all_chunks)} chunks "
            f"({text_count} text, {table_count} table, {image_count} image)"
        )
        return all_chunks

    # ========================================
    # SHARED HELPERS
    # ========================================

    @staticmethod
    def _extract_page_bboxes(pdf_path: str, page_num: int) -> dict:
        """Extract bounding boxes for tables and images on a page using PyMuPDF."""
        import fitz

        doc = fitz.open(pdf_path)
        try:
            page = doc[page_num]

            table_bboxes = []
            try:
                tables = page.find_tables()
                table_bboxes = [list(t.bbox) for t in tables.tables]
            except Exception:
                pass

            image_bboxes = []
            for img in page.get_images(full=True):
                try:
                    bbox = list(page.get_image_bbox(img))
                    # Skip tiny images (icons, bullets, etc.)
                    if bbox[2] - bbox[0] > 20 and bbox[3] - bbox[1] > 20:
                        image_bboxes.append(bbox)
                except Exception:
                    pass

            return {"tables": table_bboxes, "images": image_bboxes}
        finally:
            doc.close()

    @staticmethod
    def _separate_content_segments(page_content: str) -> list[tuple[str, str]]:
        """Split page content into typed segments: text, table, or image.

        Detection rules:
        - Lines starting with `![` -> "image" segment
        - Lines starting with `|` where a `|---|` separator row exists -> "table" segment
        - Everything else -> "text" segment
        """
        segments: list[tuple[str, str]] = []
        current_lines: list[str] = []
        current_type = "text"

        lines = page_content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Image detection: ![...](...)
            if stripped.startswith("!["):
                if current_lines:
                    segments.append(("\n".join(current_lines), current_type))
                    current_lines = []
                segments.append((line, "image"))
                current_type = "text"
                i += 1
                continue

            # Table detection: line starts with |
            if stripped.startswith("|"):
                is_table = False
                lookahead_lines = [line]
                j = i + 1
                while j < len(lines) and lines[j].strip().startswith("|"):
                    lookahead_lines.append(lines[j])
                    if re.match(r"^\|[\s\-:|]+\|", lines[j].strip()):
                        is_table = True
                    j += 1

                if is_table:
                    if current_lines:
                        segments.append(("\n".join(current_lines), current_type))
                        current_lines = []
                    segments.append(("\n".join(lookahead_lines), "table"))
                    current_type = "text"
                    i = j
                    continue

            # Default: text
            if current_type != "text" and current_lines:
                segments.append(("\n".join(current_lines), current_type))
                current_lines = []
                current_type = "text"

            current_lines.append(line)
            i += 1

        if current_lines:
            segments.append(("\n".join(current_lines), current_type))

        return segments

    @staticmethod
    def _split_large_table(table_content: str, max_size: int) -> list[str]:
        """Split a large table into parts, preserving the header row in each."""
        if len(table_content) <= max_size:
            return [table_content]

        lines = table_content.split("\n")
        if len(lines) < 3:
            return [table_content]

        header_lines = lines[:2]
        header = "\n".join(header_lines)
        data_lines = lines[2:]

        parts: list[str] = []
        current_part_lines: list[str] = list(header_lines)
        current_size = len(header)

        for data_line in data_lines:
            line_size = len(data_line) + 1
            if current_size + line_size > max_size and len(current_part_lines) > 2:
                parts.append("\n".join(current_part_lines))
                current_part_lines = list(header_lines)
                current_size = len(header)
            current_part_lines.append(data_line)
            current_size += line_size

        if len(current_part_lines) > 2:
            parts.append("\n".join(current_part_lines))

        return parts if parts else [table_content]

    @staticmethod
    def _save_image_from_content(
        content: str, images_dir: Path, doc_id: str, page_num: int, img_idx: int
    ) -> str | None:
        """Extract base64 image from markdown and save to disk. Returns relative path."""
        match = re.search(r"!\[.*?\]\(data:image/(\w+);base64,([A-Za-z0-9+/=]+)\)", content)
        if not match:
            return None

        ext = match.group(1)
        if ext == "jpeg":
            ext = "jpg"
        b64_data = match.group(2)

        try:
            image_bytes = base64.b64decode(b64_data)
            filename = f"page{page_num}_img{img_idx}.{ext}"
            (images_dir / filename).write_bytes(image_bytes)
            return f"{doc_id}/{filename}"
        except Exception as e:
            logger.warning(f"Failed to save image: {e}")
            return None

    @staticmethod
    def _save_page_render(
        page_b64: str, images_dir: Path, doc_id: str, page_num: int, img_idx: int
    ) -> str | None:
        """Save a rendered page screenshot as the image for a vision-mode image chunk."""
        try:
            image_bytes = base64.b64decode(page_b64)
            filename = f"page{page_num}_img{img_idx}.png"
            (images_dir / filename).write_bytes(image_bytes)
            return f"{doc_id}/{filename}"
        except Exception as e:
            logger.warning(f"Failed to save page render as image: {e}")
            return None

    @staticmethod
    def _extract_image_description(content: str) -> str:
        """Extract alt text / description from image markdown, or return content as-is."""
        match = re.match(r"!\[(.*?)\]\(.*\)", content, re.DOTALL)
        if match and match.group(1).strip():
            return match.group(1).strip()
        cleaned = re.sub(r"!\[.*?\]\(.*?\)", "", content).strip()
        return cleaned if cleaned else content
