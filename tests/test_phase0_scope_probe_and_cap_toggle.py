"""Phase 0: the scope probe (PR-1) and the per-doc cap toggle (PR-2).

Spec: OpenClaw_Supervisor `neo/outputs/20260915-meinrag-phase0-pr-spec.md`.
Neither change alters what is returned to the user; both exist to be MEASURED.

The tests that matter most are the negative-control cells, and they are the ones
easiest to skip:

  PR-1  a query carrying NO scope must still EMIT the line, with `scope=none`.
        "no log line" is compatible with {not deployed, no traffic, no scope
        passed} all at once -- the three things this probe exists to separate.
  PR-2  with the toggle untouched, behaviour must equal today's. Testing only
        that the toggle turns the cap OFF proves nothing about that.
"""
from __future__ import annotations

import logging
import types

import pytest
from langchain_core.documents import Document

from app.services.retrieval import _apply_per_doc_cap
from app.routers.query import _resolve_doc_ids


def _doc(doc_id: str, chunk_index: int = 0, content: str = "content") -> Document:
    return Document(page_content=content,
                    metadata={"doc_id": doc_id, "chunk_index": chunk_index})


# ------------------------------------------------------------------ PR-2 -----
def _retrieved(n_docs: int, per_doc: int) -> list[tuple]:
    return [(_doc(f"d{d}", c), 1.0 - (d * per_doc + c) / 1000.0)
            for d in range(n_docs) for c in range(per_doc)]


class TestPerDocCapToggle:
    def test_default_behaviour_is_unchanged(self):
        """No toggle argument == today's behaviour. 50 // 24 = 2 chunks per doc."""
        retrieved = _retrieved(n_docs=24, per_doc=2)
        kept = _apply_per_doc_cap(retrieved, 24, 50)
        assert len(kept) == 48
        per_doc: dict[str, int] = {}
        for doc, _ in kept:
            did = doc.metadata["doc_id"]
            per_doc[did] = per_doc.get(did, 0) + 1
        assert max(per_doc.values()) <= 2

    def test_default_caps_a_dominating_doc(self):
        """The case the cap exists for -- one doc dominating the result set."""
        retrieved = ([(_doc("hog", i), 0.9) for i in range(40)]
                     + [(_doc(f"d{d}", 0), 0.5) for d in range(9)])
        kept = _apply_per_doc_cap(retrieved, 10, 50)
        hogs = sum(1 for doc, _ in kept if doc.metadata["doc_id"] == "hog")
        assert hogs == 5, f"cap = 50 // 10 = 5, got {hogs}"

    def test_disabled_returns_the_input_untouched(self):
        retrieved = ([(_doc("hog", i), 0.9) for i in range(40)]
                     + [(_doc(f"d{d}", 0), 0.5) for d in range(9)])
        kept = _apply_per_doc_cap(retrieved, 10, 50, enabled=False)
        assert kept == retrieved
        assert len(kept) == 49

    def test_disabled_emits_no_cap_log(self, caplog):
        """Acceptance cell 2: the `Per-doc cap` line must disappear."""
        retrieved = [(_doc("hog", i), 0.9) for i in range(40)]
        with caplog.at_level(logging.INFO, logger="app.services.retrieval"):
            _apply_per_doc_cap(retrieved, 10, 50, enabled=False)
        assert "Per-doc cap" not in caplog.text

    def test_enabled_still_emits_the_cap_log(self, caplog):
        """Control for the cell above -- proves that assertion is able to fail."""
        retrieved = [(_doc("hog", i), 0.9) for i in range(40)]
        with caplog.at_level(logging.INFO, logger="app.services.retrieval"):
            _apply_per_doc_cap(retrieved, 10, 50, enabled=True)
        assert "Per-doc cap" in caplog.text

    def test_config_default_is_true(self):
        """Default True == zero change to production behaviour on merge."""
        from app.config import Settings
        assert Settings().per_doc_cap_enabled is True


# ------------------------------------------------------------------ PR-1 -----
class _Registry:
    def __init__(self, user_docs=(), by_collection=(), by_subtag=()):
        self._user = user_docs
        self._coll = by_collection
        self._sub = by_subtag

    async def list_all(self, user_id=None):
        return [{"doc_id": d} for d in self._user]

    async def list_by_collection(self, collection, user_id=None):
        return [{"doc_id": d} for d in self._coll]

    async def list_by_subtag(self, subtag, user_id=None):
        return [{"doc_id": d} for d in self._sub]


def _req(**kw):
    base = {"doc_ids": None, "collection": None, "subtags": None, "session_id": None}
    base.update(kw)
    return types.SimpleNamespace(**base)


def _settings(user_isolation="none"):
    return types.SimpleNamespace(user_isolation=user_isolation)


async def _probe_lines(caplog, request, settings, registry, user="u1"):
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.routers.query"):
        await _resolve_doc_ids(request, settings, registry, user)
    return [r.getMessage() for r in caplog.records if "Scope probe:" in r.getMessage()]


def _field(line: str, name: str) -> str:
    return line.split(f"{name}=")[1].split()[0]


class TestScopeProbe:
    @pytest.mark.asyncio
    async def test_unscoped_query_still_emits_the_line(self, caplog):
        """THE negative control. Absence of the line is not an acceptable answer:
        it is compatible with not-deployed / no-traffic / no-scope simultaneously."""
        lines = await _probe_lines(caplog, _req(), _settings(), _Registry())
        assert len(lines) == 1, "the probe must be unconditional"
        assert _field(lines[0], "scope") == "none"

    @pytest.mark.asyncio
    async def test_empty_resolution_is_zero_not_none(self, caplog):
        """Scope passed but filtered to nothing -- distinguishable from `none`."""
        lines = await _probe_lines(
            caplog, _req(collection="c1"), _settings(), _Registry(by_collection=()))
        assert len(lines) == 1 and _field(lines[0], "scope") == "0", lines

    @pytest.mark.asyncio
    async def test_resolved_scope_reports_its_size(self, caplog):
        lines = await _probe_lines(
            caplog, _req(collection="c1"), _settings(),
            _Registry(by_collection=("a", "b", "c")))
        assert len(lines) == 1 and _field(lines[0], "scope") == "3", lines

    @pytest.mark.asyncio
    async def test_the_three_cells_are_distinguishable(self, caplog):
        """Two cells returning the same literal would mean it is not measuring."""
        cases = ((_req(), _Registry()),
                 (_req(collection="c1"), _Registry(by_collection=())),
                 (_req(collection="c1"), _Registry(by_collection=("a", "b"))))
        seen = []
        for request, registry in cases:
            lines = await _probe_lines(caplog, request, _settings(), registry)
            seen.append(_field(lines[0], "scope"))
        assert len(set(seen)) == 3, f"cells collapsed to {seen}"

    @pytest.mark.asyncio
    async def test_user_scoped_flag_travels_with_the_reading(self, caplog):
        unscoped = await _probe_lines(caplog, _req(), _settings(), _Registry())
        scoped = await _probe_lines(
            caplog, _req(collection="c1"), _settings(), _Registry(by_collection=("a",)))
        assert _field(unscoped[0], "user_scoped") == "False"
        assert _field(scoped[0], "user_scoped") == "True"

    @pytest.mark.asyncio
    async def test_actor_is_a_short_hash_not_the_user_id(self, caplog):
        """176 calls may be 3 people. The hash must DISTINGUISH, not RESTORE."""
        a = (await _probe_lines(
            caplog, _req(), _settings(), _Registry(), "lawyer@firm.example"))[0]
        b = (await _probe_lines(
            caplog, _req(), _settings(), _Registry(), "someone.else"))[0]
        assert "lawyer@firm.example" not in a, "raw user id must never be logged"
        ha, hb = _field(a, "actor"), _field(b, "actor")
        assert len(ha) == 8, ha
        assert ha != hb, (ha, hb)

    @pytest.mark.asyncio
    async def test_same_actor_hashes_stably(self, caplog):
        """Otherwise you cannot count PEOPLE, which is the point of the field."""
        a = (await _probe_lines(caplog, _req(), _settings(), _Registry(), "u9"))[0]
        b = (await _probe_lines(caplog, _req(), _settings(), _Registry(), "u9"))[0]
        assert _field(a, "actor") == _field(b, "actor")

    @pytest.mark.asyncio
    async def test_probe_does_not_change_what_is_returned(self, caplog):
        """PR-1 is observability only -- the resolution itself must be untouched."""
        doc_ids, user_scoped = await _resolve_doc_ids(
            _req(collection="c1"), _settings(), _Registry(by_collection=("a", "b")), "u1")
        assert sorted(doc_ids) == ["a", "b"]
        assert user_scoped is True
