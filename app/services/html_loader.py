"""HTML loader that strips iXBRL metadata + converts to Markdown.

Motivation
----------
SEC EDGAR filings (10-K, 10-Q, employment agreements) use Inline XBRL (iXBRL)
— XBRL tags embedded in the HTML. `UnstructuredHTMLLoader` requires a heavy
`unstructured` dep; `BSHTMLLoader` just dumps `get_text()` which includes
all XBRL metadata as a wall of URIs/identifiers at the start of the document.

This loader:
  1. Parses the HTML with BS4's `lxml` parser
  2. Decomposes iXBRL metadata blocks (ix:hidden, xbrli:context, xbrli:unit, …)
  3. Unwraps iXBRL display tags (ix:nonFraction, ix:nonNumeric, …) so the
     displayed values ("$100", "9/28/2024") remain as text
  4. Drops layout-only empty tables (SEC uses them as spacers)
  5. Converts the cleaned HTML to Markdown via `markdownify`
  6. Returns a single LangChain `Document` with the Markdown text

Benchmark on apple_10k_2024.htm (1.5 MB → 238 KB):
  BSHTMLLoader      : 24s, iXBRL noise in first chunks
  Native docling    : 10s, same iXBRL noise, bigger output
  This loader       : 1s, clean Markdown ← wins

Also used for plain `.htm` / `.html` — the iXBRL strip is a no-op for non-SEC
HTML so behavior stays correct.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


# Metadata-only iXBRL blocks — not user-visible content. Decompose entirely.
_IXBRL_METADATA_TAGS = {
    "ix:hidden", "ix:references", "ix:resources",
    "xbrli:context", "xbrli:unit", "xbrli:xbrl",
}

# HTML boilerplate with no prose value.
_HTML_DROP_TAGS = {"script", "style", "meta", "head"}

# Namespace prefixes for iXBRL DISPLAY wrappers — unwrap so their inner
# text (the actual numbers/dates) stays visible.
_IXBRL_DISPLAY_PREFIXES = ("ix:", "xbrli:", "xlink:", "link:", "xbrldi:")


def _clean_html(html: str) -> str:
    """Strip iXBRL metadata + empty layout tables. Returns cleaned HTML."""
    import warnings
    from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
    # SEC filings are technically iXBRL (XHTML). bs4's lxml HTML parser works
    # fine but warns; suppress — we know what we're doing.
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

    soup = BeautifulSoup(html, "lxml")

    # Pass 1: drop metadata + boilerplate outright
    for tag in list(soup.find_all()):
        name = tag.name or ""
        if name in _HTML_DROP_TAGS or name in _IXBRL_METADATA_TAGS:
            tag.decompose()
            continue
        # Unwrap iXBRL display wrappers (keep inner text)
        if any(name.startswith(p) for p in _IXBRL_DISPLAY_PREFIXES):
            tag.unwrap()

    # Pass 2: drop empty layout tables (SEC uses 9-col tables as spacers)
    for table in list(soup.find_all("table")):
        if len(table.get_text(strip=True)) < 10:
            table.decompose()

    return str(soup)


def html_to_markdown(html: str) -> str:
    """Convert HTML (possibly iXBRL) to clean Markdown."""
    from markdownify import markdownify as md

    cleaned = _clean_html(html)
    mdtext = md(cleaned, heading_style="ATX", strip=["a"])

    # Collapse empty-cell MD rows that survived
    mdtext = re.sub(r"^\|(\s*\|)+\s*$", "", mdtext, flags=re.MULTILINE)
    # Collapse separator-only rows
    mdtext = re.sub(r"^\|\s*---(\s*\|\s*---)*\s*\|?\s*$", "", mdtext, flags=re.MULTILINE)
    # Collapse 3+ blank lines
    mdtext = re.sub(r"\n{3,}", "\n\n", mdtext).strip()
    return mdtext


class MarkdownifyHTMLLoader(BaseLoader):
    """LangChain loader that produces Markdown-formatted Documents from HTML.

    Drop-in replacement for BSHTMLLoader for HTML and iXBRL (SEC) sources.
    Output is Markdown so:
      - SourceViewer renders it cleanly via ReactMarkdown
      - RecursiveCharacterTextSplitter can use MD-aware separators naturally
      - RAG retrieval benefits from preserved heading/list structure
    """

    def __init__(self, file_path: str | Path, encoding: str = "utf-8"):
        self.file_path = str(file_path)
        self.encoding = encoding

    def load(self) -> list[Document]:
        path = Path(self.file_path)
        html = path.read_text(encoding=self.encoding, errors="replace")
        md = html_to_markdown(html)
        meta = {"source": self.file_path}
        return [Document(page_content=md, metadata=meta)]
