"""The pure parts of scripts/eval_context_sweep.py and the /health/config snapshot."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "eval_context_sweep.py"
spec = importlib.util.spec_from_file_location("eval_context_sweep", SCRIPT)
ecs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ecs)


# ---- query set

def test_load_queries_rejects_missing_fields(tmp_path):
    p = tmp_path / "q.json"
    p.write_text(json.dumps([{"id": "q1", "question": "?", "doc_id": "d", "chunk_index": 0}]), encoding="utf-8")
    with pytest.raises(ValueError, match="expected"):
        ecs.load_queries(p)
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        ecs.load_queries(p)


def test_load_queries_accepts_a_complete_set(tmp_path):
    p = tmp_path / "q.json"
    p.write_text(json.dumps([{"id": "q1", "question": "?", "doc_id": "d", "chunk_index": 3, "expected": "x"}]), encoding="utf-8")
    assert ecs.load_queries(p)[0]["chunk_index"] == 3


# ---- hits

def test_is_hit_distinguishes_chunk_from_document():
    sources = [{"doc_id": "d", "chunk_index": 2}, {"doc_id": "e", "chunk_index": 0}]
    assert ecs.is_hit(sources, "d", 2) == (True, True)
    assert ecs.is_hit(sources, "d", 5) == (False, True)
    assert ecs.is_hit(sources, "z", 0) == (False, False)
    assert ecs.is_hit([], "d", 2) == (False, False)


# ---- judges

@pytest.mark.parametrize("text,expected", [
    ("YES - the answer names the same article", True),
    ("no. It gives a different number.", False),
    ("**Yes**, matches.", True),
    ("Maybe", None),
    ("", None),
    (None, None),
])
def test_parse_verdict(text, expected):
    assert ecs.parse_verdict(text) is expected


def test_vote_never_turns_an_abstention_into_a_verdict():
    assert ecs.vote([True, True]) == ("correct", True)
    assert ecs.vote([False, False]) == ("wrong", True)
    assert ecs.vote([True, False]) == ("split", False)
    assert ecs.vote([True, None]) == ("no reading", False)
    assert ecs.vote([]) == ("no reading", False)


# ---- cost, summary, table

def test_estimate_cost_scales_with_cells_and_judges():
    base = ecs.estimate_cost(30, 5, 2)
    assert base > 0
    assert ecs.estimate_cost(30, 10, 2) == pytest.approx(2 * base)
    assert ecs.estimate_cost(30, 5, 0) < base


def test_summarize_and_render():
    recs = [
        {"id": "q1", "top_k": 4, "hit_exact": True, "hit_doc": True, "label": "correct", "latency_s": 1.0, "context_used_tokens": 900, "chunks_included": 4},
        {"id": "q2", "top_k": 4, "hit_exact": False, "hit_doc": True, "label": "split", "latency_s": 3.0, "context_used_tokens": 1100, "chunks_included": 4},
        {"id": "q1", "top_k": 8, "hit_exact": True, "hit_doc": True, "label": "correct", "latency_s": 2.0, "context_used_tokens": 1800, "chunks_included": 8},
        {"id": "q2", "top_k": 8, "hit_exact": True, "hit_doc": True, "label": "no reading", "latency_s": 2.0, "context_used_tokens": None, "chunks_included": 8},
    ]
    rows = ecs.summarize(recs)
    assert [r["top_k"] for r in rows] == [4, 8]
    r4, r8 = rows
    assert (r4["n"], r4["hit_exact"], r4["hit_doc"], r4["correct"], r4["split"]) == (2, 1, 2, 1, 1)
    assert (r8["hit_exact"], r8["correct"], r8["no_reading"]) == (2, 1, 1)
    assert r4["latency_p50"] == 2.0 and r4["ctx_tokens_median"] == 1000
    table = ecs.render_table(rows)
    assert table.count("\n") == 4 and "| 8 | 2 | 2 | 2 | 1 | 0 | 1 |" in table


# ---- /health/config

def test_config_snapshot_reads_only_named_settings_and_no_secret():
    from app.config import Settings
    from app.routers.health import config_snapshot, RETRIEVAL_SETTINGS
    snap = config_snapshot(Settings(openai_api_key="sk-test-not-a-real-key", database_url="sqlite+aiosqlite:///:memory:"))
    assert set(snap) == set(RETRIEVAL_SETTINGS)
    assert "sk-test" not in json.dumps(snap)
    assert snap["retrieval_top_k"] == Settings.model_fields["retrieval_top_k"].default
    assert isinstance(snap["llm_provider"], str)     # enum unwrapped to its value
