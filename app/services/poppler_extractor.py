"""Poppler-based figure extraction for PDF documents.

Extracts images from PDFs using pdftohtml -xml and matches them to
figure captions found in the PDF text. No API calls required.
"""

import logging
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Bundled poppler location (relative to project root)
_BUNDLED_POPPLER = Path(__file__).parent.parent.parent / "docs" / "poppler" / "Library" / "bin"

# Default config
DEFAULT_CONFIG = {
    "caption_patterns": [r"^(?:Fig(?:ure)?\.?|图)\s*[:：\.]?\s*.*"],
    "proximity": 80,
    "line_tolerance": 2.0,
    "chunk_gap": 40.0,
    "ignore_case": True,
    "min_image_area": 2500,  # skip icons/bullets < 50x50
}

# Compiled caption regex (module-level, built on first use)
_caption_regexes: list[re.Pattern] | None = None


def _get_caption_regexes() -> list[re.Pattern]:
    global _caption_regexes
    if _caption_regexes is None:
        _caption_regexes = [
            re.compile(p, re.IGNORECASE)
            for p in DEFAULT_CONFIG["caption_patterns"]
        ]
    return _caption_regexes


@dataclass
class ExtractedFigure:
    """A figure extracted from a PDF via poppler."""

    page_num: int  # 0-indexed
    image_path: str  # "{doc_id}/page0_img0.png"
    caption: str  # matched caption or "Figure on page N"
    bbox: list[float] = field(default_factory=list)  # [x0, y0, x1, y1]


def _find_poppler_bin() -> Path | None:
    """Find poppler binaries: bundled path first, then system PATH."""
    if _BUNDLED_POPPLER.exists() and (_BUNDLED_POPPLER / "pdftohtml.exe").exists():
        return _BUNDLED_POPPLER
    if _BUNDLED_POPPLER.exists() and (_BUNDLED_POPPLER / "pdftohtml").exists():
        return _BUNDLED_POPPLER
    # Check system PATH
    if shutil.which("pdftohtml") is not None:
        return None  # system PATH, no extra env needed
    return None


def has_poppler() -> bool:
    """Check if poppler (pdftohtml) is available."""
    if _BUNDLED_POPPLER.exists():
        pdftohtml = _BUNDLED_POPPLER / "pdftohtml.exe"
        if pdftohtml.exists():
            return True
        pdftohtml = _BUNDLED_POPPLER / "pdftohtml"
        if pdftohtml.exists():
            return True
    return shutil.which("pdftohtml") is not None


def _run_poppler(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a poppler command with bundled path in env if available."""
    import os

    env = None
    poppler_bin = _find_poppler_bin()
    if poppler_bin is not None:
        env = os.environ.copy()
        # Keep PATH for DLL dependencies
        env["PATH"] = str(poppler_bin) + os.pathsep + env.get("PATH", "")
        # Resolve full executable path so subprocess finds it on Windows
        exe_name = cmd[0] + (".exe" if os.name == "nt" else "")
        full_exe = poppler_bin / exe_name
        if full_exe.exists():
            cmd = [str(full_exe)] + cmd[1:]

    proc = subprocess.run(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=120, env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Poppler command failed: {' '.join(cmd)}\n"
            f"stderr: {proc.stderr[:500]}"
        )
    return proc


def _convert_to_png(src: Path, dest: Path) -> None:
    """Convert an image file to PNG format."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".png":
        shutil.copy2(src, dest)
        return
    try:
        from PIL import Image
        img = Image.open(src)
        img.save(dest, "PNG")
    except Exception:
        # Last resort: copy as-is
        shutil.copy2(src, dest)


def _parse_page_text(page_elem: ET.Element) -> list[dict]:
    """Parse text segments from a page XML element."""
    segments = []
    for tx in page_elem.findall("text"):
        raw_text = "".join(tx.itertext()).strip()
        if not raw_text:
            continue
        segments.append({
            "top": float(tx.get("top", 0.0)),
            "left": float(tx.get("left", 0.0)),
            "width": float(tx.get("width", 0.0)),
            "height": float(tx.get("height", 0.0)),
            "text": raw_text,
        })
    return segments


def _group_into_lines(segments: list[dict], line_tol: float) -> list[dict]:
    """Group text segments into lines by vertical proximity."""
    lines = []
    for seg in sorted(segments, key=lambda s: s["top"]):
        placed = False
        for line in lines:
            if abs(seg["top"] - line["top"]) <= line_tol:
                line["segments"].append(seg)
                line["top"] = min(line["top"], seg["top"])
                line["bottom"] = max(line["bottom"], seg["top"] + seg["height"])
                placed = True
                break
        if not placed:
            lines.append({
                "top": seg["top"],
                "bottom": seg["top"] + seg["height"],
                "segments": [seg],
            })
    return lines


_SECTION_HEADING_RE = re.compile(r"^\d+\.\s+[A-Z]")


def _extract_captions(lines: list[dict], chunk_gap: float) -> list[dict]:
    """Extract figure captions from grouped text lines.

    After finding a caption line, collects up to 3 continuation lines
    where the vertical gap from the previous line bottom to the next
    line top is <= 20px.  Stops early if the next line matches a caption
    pattern, a section heading pattern, or is empty.
    """
    caption_regexes = _get_caption_regexes()
    max_continuation = 3
    continuation_gap = 20.0  # max px gap between consecutive caption lines

    # Sort lines by vertical position so continuation lookup works
    sorted_lines = sorted(lines, key=lambda ln: ln["top"])

    caps = []
    consumed: set[int] = set()  # indices of lines consumed as continuations

    for line_idx, line in enumerate(sorted_lines):
        if line_idx in consumed:
            continue
        segs = sorted(line["segments"], key=lambda s: s["left"])
        if not segs:
            continue
        # Split into chunks by horizontal gap
        chunks = []
        current = [segs[0]]
        for seg in segs[1:]:
            prev = current[-1]
            gap = seg["left"] - (prev["left"] + prev["width"])
            if gap > chunk_gap:
                chunks.append(current)
                current = [seg]
            else:
                current.append(seg)
        if current:
            chunks.append(current)

        for chunk in chunks:
            parts = [s["text"] for s in chunk if s["text"]]
            if not parts:
                continue
            chunk_text = " ".join(parts)
            if any(regex.match(chunk_text) for regex in caption_regexes):
                left = min(s["left"] for s in chunk)
                right = max(s["left"] + s["width"] for s in chunk)
                top = min(s["top"] for s in chunk)
                bottom = max(s["top"] + s["height"] for s in chunk)

                # --- Collect continuation lines ---
                prev_bottom = bottom
                cont_count = 0
                for next_idx in range(line_idx + 1, len(sorted_lines)):
                    if cont_count >= max_continuation:
                        break
                    next_line = sorted_lines[next_idx]
                    gap_to_next = next_line["top"] - prev_bottom
                    if gap_to_next > continuation_gap:
                        break

                    next_segs = sorted(
                        next_line["segments"], key=lambda s: s["left"]
                    )
                    next_text = " ".join(
                        s["text"] for s in next_segs if s["text"]
                    ).strip()

                    if not next_text:
                        break
                    if any(r.match(next_text) for r in caption_regexes):
                        break
                    if _SECTION_HEADING_RE.match(next_text):
                        break

                    chunk_text += " " + next_text
                    bottom = next_line["bottom"]
                    prev_bottom = bottom
                    consumed.add(next_idx)
                    cont_count += 1

                caps.append({
                    "rect": (left, top, right, bottom),
                    "text": chunk_text,
                })
    return caps


def _match_caption(
    img_rect: tuple[float, float, float, float],
    captions: list[dict],
    proximity: float,
) -> dict | None:
    """Find the best matching caption for an image by spatial proximity."""
    l, t, r, b = img_rect
    icx = (l + r) / 2
    best = None
    best_score = 1e9

    for cap in captions:
        cl, ct, cr, cb = cap["rect"]
        ccx = (cl + cr) / 2
        vertical_gap = ct - b  # positive if caption below image
        above_gap = t - cb      # positive if caption above image
        horiz_dist = abs(ccx - icx)
        score = None

        if 0 <= vertical_gap <= proximity:
            score = vertical_gap + horiz_dist * 0.05
        elif 0 <= above_gap <= proximity:
            score = above_gap + horiz_dist * 0.1 + 100
        else:
            if (abs(ct - b) <= proximity * 1.5) or (abs(t - cb) <= proximity * 1.5):
                score = min(abs(ct - b), abs(t - cb)) + horiz_dist * 0.2 + 200

        if score is not None and score < best_score:
            best_score = score
            best = cap

    return best


def extract_figures(
    pdf_path: Path,
    images_dir: Path,
    doc_id: str,
) -> list[ExtractedFigure]:
    """Extract figures from a PDF using poppler's pdftohtml.

    Args:
        pdf_path: Path to the PDF file.
        images_dir: Directory to save extracted PNG images.
        doc_id: Document ID for image path prefixing.

    Returns:
        List of ExtractedFigure with page_num, image_path, caption, and bbox.
        Returns empty list if poppler is not available or extraction fails.
    """
    if not has_poppler():
        logger.warning("Poppler not available, skipping figure extraction")
        return []

    images_dir.mkdir(parents=True, exist_ok=True)
    config = DEFAULT_CONFIG
    proximity = config["proximity"]
    line_tol = config["line_tolerance"]
    chunk_gap = config["chunk_gap"]
    min_area = config["min_image_area"]

    figures: list[ExtractedFigure] = []

    with tempfile.TemporaryDirectory(prefix=f"poppler_{pdf_path.stem}_") as tmpd:
        xml_dir = Path(tmpd)
        xml_base = Path("doc")
        xml_file = xml_dir / "doc.xml"

        try:
            _run_poppler(
                ["pdftohtml", "-xml", "-hidden", str(pdf_path.resolve()), str(xml_base)],
                cwd=xml_dir,
            )
        except Exception as e:
            logger.warning(f"Poppler pdftohtml failed: {e}")
            return []

        if not xml_file.exists():
            candidates = list(xml_dir.glob("*.xml"))
            if not candidates:
                logger.warning("No XML output from pdftohtml")
                return []
            xml_file = candidates[0]

        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
        except Exception as e:
            logger.warning(f"Failed to parse pdftohtml XML: {e}")
            return []

        for page in root.findall("page"):
            # pdftohtml uses 1-indexed pages, we use 0-indexed
            pnum_1indexed = int(page.get("number", "1"))
            pnum = pnum_1indexed - 1

            # Parse text and find captions
            segments = _parse_page_text(page)
            lines = _group_into_lines(segments, line_tol)
            captions = _extract_captions(lines, chunk_gap)

            # Collect images
            for img_idx, im in enumerate(page.findall("image")):
                top = float(im.get("top", 0))
                left = float(im.get("left", 0))
                width = float(im.get("width", 0))
                height = float(im.get("height", 0))
                src = im.get("src")

                if not src or width * height < min_area:
                    continue

                img_rect = (left, top, left + width, top + height)
                bbox = [left, top, left + width, top + height]

                # Match to caption
                best_cap = _match_caption(img_rect, captions, proximity)
                if best_cap:
                    caption = best_cap["text"].strip()
                else:
                    caption = f"Figure on page {pnum + 1}"

                # Convert and save image
                src_path = Path(src)
                if not src_path.is_absolute():
                    src_path = xml_file.parent / src_path

                if not src_path.exists():
                    logger.debug(f"Image file not found: {src_path}")
                    continue

                filename = f"page{pnum}_img{img_idx}.png"
                dest_png = images_dir / filename
                try:
                    _convert_to_png(src_path, dest_png)
                except Exception as e:
                    logger.warning(f"Failed to convert image {src_path}: {e}")
                    continue

                image_path = f"{doc_id}/{filename}"
                figures.append(ExtractedFigure(
                    page_num=pnum,
                    image_path=image_path,
                    caption=caption,
                    bbox=bbox,
                ))

    logger.info(f"Poppler extracted {len(figures)} figure(s) from {pdf_path.name}")
    return figures
