"""FAISS↔registry orphan reconciliation (Bug 1 residual cleanup).

Pure diff over doc_id sets — the CLI wrapper (scripts/reconcile_faiss_registry.py)
supplies the live sets and applies any fix.
"""
from __future__ import annotations


def find_orphans(faiss_doc_ids: set[str], registry_doc_ids: set[str]) -> tuple[set[str], set[str]]:
    """Return (faiss_only, registry_only): doc_ids present in one store but not the
    other. faiss_only = orphaned chunks (delete from FAISS); registry_only = rows
    whose chunks are gone (review / remove)."""
    return (faiss_doc_ids - registry_doc_ids, registry_doc_ids - faiss_doc_ids)
