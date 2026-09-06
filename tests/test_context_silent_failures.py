"""Silent failures on the context-budget path (Gauss 2026-09-02 report, items G1/G2/G3/G12).

Each test names the failure it guards against. They were run against the unpatched
code first: G1, G2 and G12 fail there, which is the proof they can fail.
"""
import logging

from app.config import DEFAULT_MODEL_WINDOW, MODEL_WINDOWS, QUERY_BUDGET_RATIOS, lookup_model_window
from app.models.schemas import QueryRequest


# ---- G1: an unknown model name used to fall back to an 8,192-token window silently, which
# collapsed the fact-type chunk budget to one or two chunks with no error anywhere.

def test_unknown_model_falls_back_to_a_large_window_and_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="app.config"):
        window = lookup_model_window("gpt-5")
    assert window == DEFAULT_MODEL_WINDOW
    assert DEFAULT_MODEL_WINDOW >= 128_000
    assert any("gpt-5" in rec.getMessage() for rec in caplog.records), "the fallback must be loud"


def test_known_model_resolves_without_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="app.config"):
        assert lookup_model_window("openai/GPT-4o-mini") == 128_000
    assert not caplog.records


def test_current_claude_models_are_in_the_table():
    # Sourced from the Anthropic models reference (1M context on Opus 4.6+ / Sonnet 4.6+ / Sonnet 5).
    for name in ("claude-opus-5", "claude-sonnet-5", "claude-opus-4-7"):
        assert MODEL_WINDOWS[name] == 1_000_000
        assert lookup_model_window(name) == 1_000_000


# ---- G2: a budget ratio for a query type the classifier can never emit is dead configuration.

def test_budget_ratio_keys_are_reachable_query_types():
    from app.services.query_types import get_type_names, load_query_types
    reachable = set(get_type_names(load_query_types()))
    assert set(QUERY_BUDGET_RATIOS) <= reachable, set(QUERY_BUDGET_RATIOS) - reachable


# ---- G12: the chat path hardcoded top_k in three places that never met; the request schema
# defaulted to 4 while /search fell back to settings.retrieval_top_k.

def test_query_request_top_k_defaults_to_none_like_search():
    assert QueryRequest(question="q").top_k is None


def test_effective_top_k_falls_back_to_settings():
    from app.routers.query import _effective_top_k

    class S:
        retrieval_top_k = 7

    assert _effective_top_k(None, S()) == 7
    assert _effective_top_k(3, S()) == 3


# ---- G3: the history budget was computed and subtracted from the chunk budget but the history
# itself was never trimmed to it.

def test_history_is_trimmed_to_budget_oldest_first():
    from langchain_core.messages import AIMessage, HumanMessage
    from app.services.retrieval import _count_tokens, _trim_history_to_budget

    msgs = [HumanMessage(content="one " * 50), AIMessage(content="two " * 50),
            HumanMessage(content="three " * 50), AIMessage(content="four " * 50)]
    per = [_count_tokens(m.content) for m in msgs]
    assert min(per) > 0
    budget = per[-1] + per[-2]  # exactly the two newest fit
    kept = _trim_history_to_budget(msgs, budget)
    assert [m.content for m in kept] == [msgs[-2].content, msgs[-1].content]
    assert _trim_history_to_budget(msgs, sum(per)) == msgs           # enough budget: untouched
    assert _trim_history_to_budget(msgs, 0) == [msgs[-1]]            # never returns empty for non-empty input
    assert _trim_history_to_budget([], 100) == []
    assert _trim_history_to_budget(None, 100) is None
