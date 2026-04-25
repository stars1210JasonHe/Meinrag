"""One-shot: delete + re-upload 5 docs to backfill chunk summaries.

After today's M6 alignment + summary defaults, re-uploading regenerates
the chunk-level summary metadata that the mindmap pipeline (and other
summary-driven retrieval paths) depend on.

This script is intentionally one-off. It is NOT a general re-ingest CLI.
Run from repo root with backend live on :8000.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

BACKEND = "http://localhost:8000"
USER_ID = "admin"
STAGE = Path(r"C:\Users\Server1.0\AppData\Local\Temp\reingest")

DOCS_TO_REINGEST = [
    ("6a8e78d5afa6", "ai_tool_verification_ttrl.pdf"),
    ("cff31de901cc", "physics_terahertz_spintronic.pdf"),
    ("f513583fe26a", "rag-landscape-report.pdf"),
    ("cdf147155fdb", "attention_is_all_you_need.pdf"),
    ("eba0012d9ec4", "math_degree_sequences.pdf"),
]


def delete(doc_id: str) -> None:
    r = requests.delete(
        f"{BACKEND}/documents/{doc_id}",
        headers={"X-User-Id": USER_ID},
        timeout=30,
    )
    r.raise_for_status()
    print(f"  deleted: {doc_id}")


def upload(filename: str) -> str:
    path = STAGE / filename
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("rb") as fh:
        r = requests.post(
            f"{BACKEND}/documents/upload",
            headers={"X-User-Id": USER_ID},
            files={"file": (filename, fh, "application/pdf")},
            timeout=180,
        )
    r.raise_for_status()
    new_id = r.json().get("doc_id")
    print(f"  uploaded: {filename} -> {new_id}")
    return new_id


def main():
    if not STAGE.exists():
        print(f"ERROR: staging dir {STAGE} missing", file=sys.stderr)
        sys.exit(1)

    print(f"Re-ingesting {len(DOCS_TO_REINGEST)} docs (delete + upload).")
    print()

    results = []
    for old_id, filename in DOCS_TO_REINGEST:
        print(f"[{filename}]")
        t0 = time.monotonic()
        try:
            delete(old_id)
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                print(f"  delete: 404 (already gone, fine)")
            else:
                print(f"  delete failed: {e}")
                continue
        try:
            new_id = upload(filename)
        except requests.HTTPError as e:
            print(f"  upload failed: {e} body={e.response.text[:200]}")
            continue
        elapsed = time.monotonic() - t0
        print(f"  done in {elapsed:.1f}s")
        results.append((filename, new_id, elapsed))
        print()

    print("Summary:")
    for filename, new_id, elapsed in results:
        print(f"  {filename:<40} -> {new_id}  ({elapsed:.1f}s)")
    print()
    print("Note: chunk-summary generation runs as a background task.")
    print("Wait ~30-60s, then run scripts/check_chunk_summaries.py to verify.")


if __name__ == "__main__":
    main()
