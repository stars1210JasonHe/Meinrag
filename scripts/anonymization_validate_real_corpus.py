"""Validate the anonymization plugin against a real PII corpus.

Walks --corpus <dir>, loads each docx/pdf/doc via the project's
DocumentProcessor, anonymizes every chunk, and emits per-doc CSVs +
a markdown summary fragment for the validation report.

⚠️  PRIVACY NOTICE
The per-doc CSV outputs contain the ORIGINAL entity text in plaintext
(alongside its pseudonym) so that a human reviewer can spot-check Check 1
precision/recall against ground truth. That is *the point* of this
validation tool — but it also means each output CSV is a secondary
plaintext PII artifact. Treat the --output directory as sensitive:
- Don't commit it (tmp/ is already gitignored as a default-safe location).
- Don't transmit unredacted CSVs over insecure channels.
- Delete the outputs when validation is finished.
If you only need the aggregate report (entity counts, perf, consistency)
without per-row plaintext, redact the CSVs after spot-checking.

Usage:
    uv run python scripts/anonymization_validate_real_corpus.py \\
        --corpus "\\\\100.85.155.22\\homes\\贺富强\\杂项" \\
        --output tmp/anon_validation/ \\
        --limit 10
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

# Ensure project root is on sys.path when the script is run directly
# (uv run does not add it automatically for files under scripts/).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("validate")

# Ordered list (not set): makes the --limit slice deterministic across
# Python implementations and hash-randomization seeds. Without this, a
# user running with --limit=5 against a corpus of mixed docx/pdf/doc
# could get a different 5 each run.
SUPPORTED_EXTS = [".docx", ".pdf", ".doc"]


def discover_files(corpus: Path, limit: int | None) -> list[Path]:
    files: list[Path] = []
    for ext in SUPPORTED_EXTS:
        files.extend(sorted(corpus.rglob(f"*{ext}")))
    if limit:
        files = files[:limit]
    return files


async def validate_doc(file_path: Path, engine, processor) -> dict:
    """Process one file and return a result dict."""
    from app.anonymization.registry import EntityRegistry

    t0 = time.perf_counter()
    try:
        chunks = await processor.load_and_split(file_path)
    except Exception as e:
        return {
            "file": str(file_path),
            "error": f"load_failed: {e}",
            "n_chunks": 0,
            "entities": [],
        }
    load_ms = (time.perf_counter() - t0) * 1000

    if not chunks:
        return {
            "file": str(file_path),
            "error": "empty_chunks (possibly scanned PDF without OCR)",
            "n_chunks": 0,
            "entities": [],
        }

    registry = EntityRegistry()
    entities = []
    latencies = []
    type_counter: Counter[str] = Counter()
    lang_counter: Counter[str] = Counter()
    # Track which entity-text values we've already emitted to entities[]
    # so a cross-chunk repeat doesn't double-count.
    seen_originals: set[str] = set()

    for idx, chunk in enumerate(chunks):
        text = chunk.page_content
        t1 = time.perf_counter()
        result = engine.analyze_and_anonymize(text, registry)
        elapsed_ms = (time.perf_counter() - t1) * 1000
        latencies.append(elapsed_ms)
        lang_counter[result.language] += 1

        # registry.new_mappings is the authoritative public list of every
        # original-text -> pseudonym minted during this doc's run. Each
        # EntityMapping has .original / .pseudonym / .entity_type already
        # broken out, so we don't have to parse the typed-placeholder
        # string. We walk it after each chunk to attribute first-sighting
        # to the chunk where it was minted.
        for em in registry.new_mappings:
            if em.original in seen_originals:
                continue
            seen_originals.add(em.original)
            entities.append({
                "chunk_idx": idx,
                "entity_text": em.original,
                "pseudonym": em.pseudonym,
                "entity_type": em.entity_type,
            })
            type_counter[em.entity_type] += 1

    n_unique_pseudonyms = len({e["pseudonym"] for e in entities})

    return {
        "file": str(file_path),
        "error": None,
        "n_chunks": len(chunks),
        "load_ms": load_ms,
        "anon_mean_ms": statistics.mean(latencies) if latencies else 0,
        "anon_p95_ms": (
            sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0
        ),
        "anon_p99_ms": (
            sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0
        ),
        "type_counts": dict(type_counter),
        "lang_counts": dict(lang_counter),
        "entities": entities,
        "n_unique_pseudonyms": n_unique_pseudonyms,
    }


def _safe_stem(file_path: Path, corpus_root: Path) -> str:
    """Build a collision-free CSV stem from a file's path relative to the
    corpus root. Two files named `contract.docx` and `contract.pdf` in the
    same dir, or in different subdirs, would otherwise share a stem and
    one's CSV would silently overwrite the other.
    """
    try:
        rel = file_path.relative_to(corpus_root)
    except ValueError:
        # corpus_root isn't an ancestor (shouldn't happen post-discover_files,
        # but be defensive) — fall back to just the filename with suffix.
        rel = Path(file_path.name)
    # Path-separator + extension + spaces → underscore; preserves UTF-8
    # filename characters (Chinese names render fine in modern explorers).
    return str(rel).replace("/", "_").replace("\\", "_").replace(" ", "_").replace(".", "_")


def write_csv(out_dir: Path, corpus_root: Path, file_path: Path, result: dict) -> None:
    safe = _safe_stem(file_path, corpus_root)
    csv_path = out_dir / f"validation_{safe}.csv"
    # utf-8-sig (UTF-8 with BOM) so Excel opens Chinese entity_text values
    # correctly on Windows. The BOM is invisible to other UTF-8 readers.
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["chunk_idx", "entity_text", "pseudonym", "entity_type"])
        for e in result["entities"]:
            w.writerow([e["chunk_idx"], e["entity_text"], e["pseudonym"], e["entity_type"]])


def write_summary(out_dir: Path, results: list[dict]) -> None:
    md = out_dir / "validation_summary.md"
    lines = []
    lines.append("# Anonymization Validation — Summary Fragment\n")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    lines.append(
        "> ⚠️ The per-doc `validation_*.csv` files in this directory contain "
        "ORIGINAL `entity_text` values in plaintext (for ground-truth spot-checking). "
        "Treat the output directory as sensitive — do not commit or transmit "
        "unredacted CSVs, and delete after validation review.\n\n"
    )

    lines.append("## Per-doc rollup\n\n")
    lines.append("| file | n_chunks | n_entities | lang_mix | mean ms | p95 ms | p99 ms | error |\n")
    lines.append("|---|---|---|---|---|---|---|---|\n")
    for r in results:
        if r["error"]:
            lines.append(
                f"| {Path(r['file']).name} | {r['n_chunks']} | 0 | - | - | - | - | {r['error']} |\n"
            )
            continue
        lang_mix = ",".join(f"{k}={v}" for k, v in r["lang_counts"].items())
        lines.append(
            f"| {Path(r['file']).name} | {r['n_chunks']} | "
            f"{len(r['entities'])} | {lang_mix} | "
            f"{r['anon_mean_ms']:.1f} | {r['anon_p95_ms']:.1f} | "
            f"{r['anon_p99_ms']:.1f} | - |\n"
        )

    # Per-type aggregate
    type_agg: Counter[str] = Counter()
    for r in results:
        if r["error"]:
            continue
        for t, n in r["type_counts"].items():
            type_agg[t] += n

    lines.append("\n## Per-type entity counts (aggregate)\n\n")
    lines.append("| entity_type | count |\n|---|---|\n")
    for t, n in type_agg.most_common():
        lines.append(f"| {t} | {n} |\n")

    # Cross-chunk consistency check
    lines.append("\n## Cross-chunk consistency\n\n")
    lines.append(
        "Per-doc, the registry maps each unique entity text to ONE pseudonym "
        "for the lifetime of that doc. n_entities == n_unique_pseudonyms is "
        "the invariant. Mismatch indicates a registry bug.\n\n"
    )
    lines.append("| file | n_entities | n_unique_pseudonyms | consistent? |\n|---|---|---|---|\n")
    for r in results:
        if r["error"]:
            continue
        ok = "OK" if len(r["entities"]) == r["n_unique_pseudonyms"] else "MISMATCH"
        lines.append(
            f"| {Path(r['file']).name} | {len(r['entities'])} | "
            f"{r['n_unique_pseudonyms']} | {ok} |\n"
        )

    # Perf rollup
    all_means = []
    all_p95s = []
    for r in results:
        if not r["error"]:
            all_means.append(r["anon_mean_ms"])
            all_p95s.append(r["anon_p95_ms"])
    lines.append("\n## Perf rollup (per-doc summary)\n\n")
    if all_means:
        lines.append(f"- {len(all_means)} successful docs\n")
        lines.append(f"  - mean of per-doc means: {statistics.mean(all_means):.1f} ms\n")
        lines.append(f"  - max of per-doc means: {max(all_means):.1f} ms\n")
        lines.append(f"  - mean of per-doc p95s: {statistics.mean(all_p95s):.1f} ms\n")
        lines.append(f"  - max of per-doc p95s: {max(all_p95s):.1f} ms\n")

    md.write_text("".join(lines), encoding="utf-8")


async def _run():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if not args.corpus.exists():
        logger.error("Corpus dir not found or not accessible: %s", args.corpus)
        sys.exit(2)
    args.output.mkdir(parents=True, exist_ok=True)

    # Loud privacy banner — the CSVs we're about to write contain plaintext
    # entity_text by design (so a human can spot-check Check 1 recall against
    # ground truth). That makes the --output dir a secondary PII artifact.
    logger.warning(
        "PRIVACY: per-doc CSVs will contain ORIGINAL entity_text in plaintext. "
        "Treat %s as sensitive — do not commit or transmit unencrypted, and "
        "delete after validation review.",
        args.output,
    )

    from app.config import get_settings
    from app.anonymization import AnonymizationEngine
    from app.services.document_processor import DocumentProcessor

    settings = get_settings()
    if not settings.anonymization_enabled:
        logger.error(
            "ANONYMIZATION_ENABLED is false — set it true in .env before "
            "running the validation script."
        )
        sys.exit(3)

    engine = AnonymizationEngine(settings)
    processor = DocumentProcessor(settings)

    files = discover_files(args.corpus, args.limit)
    if not files:
        logger.error("No %s files found in corpus dir.", SUPPORTED_EXTS)
        sys.exit(4)
    logger.info("Validating %d files", len(files))

    results = []
    for i, f in enumerate(files, 1):
        logger.info("(%d/%d) %s", i, len(files), f.name)
        r = await validate_doc(f, engine, processor)
        write_csv(args.output, args.corpus, f, r)
        results.append(r)

    write_summary(args.output, results)
    logger.info("Done. Outputs in %s", args.output)


def main():
    asyncio.run(_run())


if __name__ == "__main__":
    main()
