"""A caller may declare the collection it is confined to, and the backend holds it.

Why a declaration rather than a derivation: the backend cannot infer which
collection a caller should see from its identity, because a deployment can route
many callers through one identity. The caller states its confinement; the
boundary is what refuses. That is not the same as filtering in the caller — the
caller supplies a fact, the backend supplies the decision.

What this is and is not, stated so nobody has to guess:

  IS      a narrowing that binds any caller which declares a scope, enforced at
          the boundary and therefore uniform across every route that reaches
          document content.
  IS NOT  protection against a client that declares nothing. `scope_collection_
          required` exists for deployments that want that posture; it is off by
          default so turning it on is a decision, not a side effect.

Both cells for every rule: a document inside the declared collection must still
come back, and one outside it must not. A filter that refuses everything would
pass the second on its own.
"""
from __future__ import annotations

import types

import pytest
from fastapi import HTTPException

from app.dependencies import resolve_doc_scope, resolve_multi_doc_scope


class _Registry:
    """Documents carry their collections on the record `get()` already loads."""

    def __init__(self, docs: dict[str, tuple[str, list[str]]]):
        # doc_id -> (owner, collections)
        self._docs = docs

    async def get(self, doc_id):
        row = self._docs.get(doc_id)
        if row is None:
            return None
        owner, collections = row
        return {"doc_id": doc_id, "user_id": owner, "collections": list(collections)}

    async def get_many_by_ids(self, doc_ids, user_id=None):
        out = []
        for d in doc_ids:
            row = self._docs.get(d)
            if row is None:
                continue
            owner, collections = row
            if user_id is None or owner == user_id:
                out.append({"doc_id": d, "user_id": owner,
                            "collections": list(collections)})
        return out


def _settings(user_isolation="all", required=False):
    return types.SimpleNamespace(
        user_isolation=user_isolation, scope_collection_required=required)


# One identity, two collections — the condition that actually holds in a
# deployment where every document was ingested by the same account.
REG = _Registry({
    "legal1": ("admin", ["legal"]),
    "legal2": ("admin", ["legal"]),
    "other1": ("admin", ["research"]),
    "shared": ("admin", ["legal", "research"]),
})


@pytest.mark.asyncio
class TestDeclaredScopeSingleDoc:
    async def test_document_inside_the_declared_collection_is_returned(self):
        doc, allowed = await resolve_doc_scope(
            "legal1", REG, _settings(), "admin", scope_collection="legal")
        assert doc["doc_id"] == "legal1"
        assert allowed == {"legal1"}

    async def test_document_outside_the_declared_collection_is_refused(self):
        """The cell the user dimension cannot cover: same owner, other collection."""
        with pytest.raises(HTTPException) as e:
            await resolve_doc_scope(
                "other1", REG, _settings(), "admin", scope_collection="legal")
        assert e.value.status_code in (403, 404)

    async def test_membership_in_any_declared_collection_suffices(self):
        doc, _ = await resolve_doc_scope(
            "shared", REG, _settings(), "admin", scope_collection="research")
        assert doc["doc_id"] == "shared"

    async def test_no_declaration_behaves_exactly_as_before(self):
        """No regression for callers that do not declare — the default posture."""
        doc, allowed = await resolve_doc_scope(
            "other1", REG, _settings(), "admin", scope_collection=None)
        assert doc["doc_id"] == "other1" and allowed == {"other1"}

    async def test_required_mode_refuses_an_undeclared_request(self):
        """Opt-in fail-closed. Off by default so enabling it is a decision."""
        with pytest.raises(HTTPException) as e:
            await resolve_doc_scope(
                "legal1", REG, _settings(required=True), "admin",
                scope_collection=None)
        assert e.value.status_code == 403

    async def test_required_mode_still_serves_a_declared_request(self):
        """Control: the strict posture must not refuse the legitimate case too."""
        doc, _ = await resolve_doc_scope(
            "legal1", REG, _settings(required=True), "admin",
            scope_collection="legal")
        assert doc["doc_id"] == "legal1"

    async def test_user_dimension_is_unchanged_by_this(self):
        with pytest.raises(HTTPException) as e:
            await resolve_doc_scope(
                "legal1", _Registry({"legal1": ("someone_else", ["legal"])}),
                _settings(), "admin", scope_collection="legal")
        assert e.value.status_code == 403


@pytest.mark.asyncio
class TestDeclaredScopeMultiDoc:
    async def test_out_of_collection_ids_are_dropped_from_the_set(self):
        allowed = await resolve_multi_doc_scope(
            ["legal1", "other1", "legal2"], REG, _settings(), "admin",
            scope_collection="legal")
        assert allowed == {"legal1", "legal2"}

    async def test_without_a_declaration_the_set_is_unchanged(self):
        allowed = await resolve_multi_doc_scope(
            ["legal1", "other1"], REG, _settings(), "admin", scope_collection=None)
        assert allowed == {"legal1", "other1"}

    async def test_isolation_off_still_means_unrestricted(self):
        allowed = await resolve_multi_doc_scope(
            ["legal1", "other1"], REG, _settings(user_isolation="none"), "admin",
            scope_collection=None)
        assert allowed is None


class TestHeaderPlumbing:
    def test_dependency_reads_the_header(self):
        from app.dependencies import get_scope_collection
        import inspect
        sig = inspect.signature(get_scope_collection)
        assert list(sig.parameters), "dependency must take the header parameter"

    def test_every_content_route_receives_the_declaration(self):
        """Leaving some content routes outside the declaration recreates the
        'there is always one nobody thought of' shape one layer up."""
        import re
        from pathlib import Path
        import app.routers.documents as d, app.routers.graph as g, app.routers.query as q
        missing = []
        for mod in (d, g, q):
            src = Path(mod.__file__).read_text(encoding="utf-8")
            for m in re.finditer(r"await resolve_(?:multi_)?doc_scope\((.*?)\)",
                                 src, flags=re.S):
                if "scope_collection" not in m.group(1):
                    missing.append(f"{Path(mod.__file__).name}: {m.group(1)[:60]}")
        assert not missing, f"scope declaration not threaded through: {missing}"

    def test_config_default_is_permissive(self):
        from app.config import Settings
        assert Settings().scope_collection_required is False
