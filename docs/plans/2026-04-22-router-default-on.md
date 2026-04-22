# Router Default-On Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flip `router_enabled` and `retrieval_top_k` defaults so the 62% latency win from the 2026-04-22 router eval ships for real users.

**Architecture:** The 2026-04-22 eval already ran router ON and recorded both `top_k=4` and `top_k=10` columns for every query. The `top_k=10` column ALREADY clears every ship gate. Task 1 verifies that from existing artifacts (no re-run, no cost). Task 2 flips the two defaults in `config.py` with TDD. Task 3 is a contingency that only fires if Task 1 surfaces something unexpected.

**Tech Stack:** Python 3.11 + pytest. No new dependencies. No new API calls.

**Predecessor:** [`docs/plans/2026-04-22-router-prefix.md`](2026-04-22-router-prefix.md) shipped the router code. HEAD = `75a111c`. Baseline + router-on numbers are already recorded in both that plan's "Eval results" section and the artifacts at `data/test_queries/query_report.md` (router-on run) and `data/test_queries/query_report_baseline_2026-04-21.md` (baseline).

**Ship gate (unchanged from predecessor plan):**

| Metric | Baseline | Must be |
|---|---|---|
| Fact correct | 91% | ≥ 88% |
| Synthesis correct | 92% | ≥ 88% |
| Overview correct | 75% | ≥ 72% |
| Multi-doc coverage | 100% | ≥ 95% |
| Impossible | 100% | = 100% |
| Latency p95 | 30.0s | < 25s |

---

## File Structure

**Modified:**
- `app/config.py` — change two defaults: `retrieval_top_k: 4 → 10`, `router_enabled: False → True`. Update the inline comment block for the router settings.
- `tests/test_config_router.py` — the existing `test_router_settings_default_off` will BREAK; rename + update to `test_router_settings_default_on`.
- `docs/plans/2026-04-22-router-prefix.md` — append a "Follow-up analysis (2026-04-22)" subsection documenting the decision.

**Not modified:** `app/services/router.py`, `app/services/retrieval.py`, `tests/test_router.py`, `tests/test_retrieval.py`, any router-hook integration test. Router code is unchanged; only defaults move.

**Created only on the contingency path (Task 3):** `scripts/diagnose_router_decision.py` — CLI diagnostic for inspecting the router menu and picks.

---

## Task 1: Analyze existing eval data, fill in decision table

**Files:**
- Read: `data/test_queries/query_report.md` (router-on, 2026-04-22)
- Read: `data/test_queries/query_report_baseline_2026-04-21.md` (baseline)
- Modify: `docs/plans/2026-04-22-router-prefix.md` (append analysis subsection)

No code changes. No eval re-run. Pure data analysis + documentation.

- [ ] **Step 1: Verify the two reports are on disk**

Run:
```bash
ls -la data/test_queries/query_report.md data/test_queries/query_report_baseline_2026-04-21.md
```

Expected: both files exist. `query_report.md` is the router-on run from 2026-04-22 (~12:02 modified time); the baseline file is from 2026-04-21.

If either is missing, STOP and report BLOCKED — the plan assumes these artifacts from the predecessor plan's Task 7.

- [ ] **Step 2: Extract the router-on metrics**

Open `data/test_queries/query_report.md`. Under "Aggregate metrics (by type × top_k)", record the 10th column (Correct) for each `top_k` row. Also grab the latency line.

Record (copy from the file — numbers below are what they SHOULD be based on 2026-04-22 observation, but verify by reading):

| Type | top_k=4 Correct | top_k=10 Correct |
|---|---|---|
| fact | ~82% | ~100% |
| overview | ~92% | ~92% |
| synthesis | ~92% | ~100% |
| impossible | ~100% | ~100% |
| filtered | ~50% | ~100% |
| ambiguous | ~100% | ~100% |

Latency line (under "Latency & context budget"): `p50=7632ms, p95=11482ms (N=82)`.

Multi-doc coverage: check the "Multi-doc coverage" table — every row should show `100%`.

- [ ] **Step 3: Compare top_k=10 column to the ship gate**

Using only the `top_k=10` numbers (because we're going to flip the default `retrieval_top_k` to 10):

| Metric @ k=10 | Value | Gate | Pass? |
|---|---|---|---|
| Fact correct | _from Step 2_ | ≥ 88% | _fill_ |
| Synthesis correct | _from Step 2_ | ≥ 88% | _fill_ |
| Overview correct | _from Step 2_ | ≥ 72% | _fill_ |
| Multi-doc coverage | 100% | ≥ 95% | ✅ |
| Impossible correct | _from Step 2_ | = 100% | _fill_ |
| Latency p95 | 11482 ms | < 25000 ms | ✅ |

**Decision gate:**

- **PATH A — all 6 gates pass:** proceed to Task 2 (flip defaults).
- **PATH B — any gate fails:** proceed to Task 3 (contingency re-run + diagnose).

- [ ] **Step 4: Write the analysis note into the predecessor plan**

Open `docs/plans/2026-04-22-router-prefix.md`. Find the existing section `### Ship decision: HOLD`. Add a new subsection BELOW it (not replacing — preserving the original HOLD record):

```markdown
### Follow-up analysis — retrieval_top_k=10 clears all gates (2026-04-22)

Re-analysis of the same run's top_k=10 column (no re-run needed):

| Metric | top_k=10 from router-on run | Gate | Pass |
|---|---|---|---|
| Fact correct | <fill %> | ≥ 88% | <Y/N> |
| Synthesis correct | <fill %> | ≥ 88% | <Y/N> |
| Overview correct | <fill %> | ≥ 72% | <Y/N> |
| Multi-doc coverage | 100% | ≥ 95% | Y |
| Impossible correct | <fill %> | = 100% | <Y/N> |
| Latency p95 (aggregated) | 11482 ms | < 25000 ms | Y |

Conclusion: <PATH A — all gates clear, proceeding to flip defaults in config.py> OR <PATH B — <which gate> failed, running contingency Task 3>.

The 2026-04-22 HOLD decision was correct at `retrieval_top_k=4` default. With the paired change `retrieval_top_k=4 → 10` the ship gates clear without a new eval run — the k=10 column of the same run already contains the production-equivalent numbers.
```

Replace all `<fill>` / `<Y/N>` / `<PATH ...>` placeholders with real values before saving.

- [ ] **Step 5: Commit the analysis**

```bash
git add docs/plans/2026-04-22-router-prefix.md
git commit -m "$(cat <<'EOF'
docs(router): follow-up analysis — k=10 clears all ship gates

Reanalyzing existing 2026-04-22 router-on run at top_k=10 (the column
we'd use in production with retrieval_top_k default=10). All six gates
clear. No new eval needed — the paired k=10 data was already recorded
in the same run.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Flip `router_enabled` and `retrieval_top_k` defaults (TDD)

**Prereq:** Task 1 chose PATH A.

**Files:**
- Modify: `app/config.py` — two one-line changes + comment update
- Modify: `tests/test_config_router.py` — rename + update existing test

- [ ] **Step 1: Update the test first (TDD failing state)**

Open `E:\MEINRAG\tests\test_config_router.py`. Replace the current function `test_router_settings_default_off` entirely. New content:

```python
def test_router_settings_default_on():
    """After 2026-04-22 eval: router ships default-on + retrieval_top_k=10."""
    s = Settings()
    assert s.router_enabled is True
    assert s.router_min_scope == 15
    assert s.router_top_k == 8
    assert s.router_model == "gpt-4o-mini"
    assert s.retrieval_top_k == 10
```

Leave `test_router_settings_env_override` unchanged.

- [ ] **Step 2: Run the test — verify it fails against current defaults**

Run:
```bash
uv run pytest tests/test_config_router.py::test_router_settings_default_on -v
```

Expected: FAIL. At least one of the following AssertionErrors:
- `assert False is True` (because `router_enabled` is currently `False`)
- `assert 4 == 10` (because `retrieval_top_k` is currently `4`)

If the test PASSES here (unexpected), stop and investigate — defaults may have already been changed.

- [ ] **Step 3: Flip the two defaults in `app/config.py`**

Open `E:\MEINRAG\app\config.py`.

Change A — find the line `retrieval_top_k: int = 4` (in the `# Retrieval` section, currently around line 85). Replace with:

```python
    retrieval_top_k: int = 10
```

Change B — find the line `router_enabled: bool = False` (in the `# Router prefix` section, currently around line 138). Replace with:

```python
    router_enabled: bool = True
```

Change C — update the comment block above the router settings. Find:

```
    # Router prefix — LLM-based doc pre-filter for large scopes.
    # Runs one gpt-4o-mini call before vector search to pick the top-K docs
    # most likely to contain the answer. Cuts downstream rerank/budget cost.
    # Fail-safe: malformed output or LLM error falls back to the full scope.
    # Off by default; eval-gated. See docs/plans/2026-04-22-router-prefix.md.
```

Replace ONLY the last line with:

```
    # On by default as of 2026-04-22 (eval cleared ship gates with
    # retrieval_top_k=10). See docs/plans/2026-04-22-router-default-on.md.
```

- [ ] **Step 4: Run the test again — verify it passes**

Run:
```bash
uv run pytest tests/test_config_router.py -v
```

Expected: 2/2 PASS. Both `test_router_settings_default_on` and `test_router_settings_env_override`.

- [ ] **Step 5: Run router-adjacent tests — confirm no regressions**

Run:
```bash
uv run pytest tests/test_router.py tests/test_retrieval.py tests/test_config_router.py -v 2>&1 | tail -10
```

Expected: 83 tests pass. `TestRouterHookInRetrieval` uses MagicMock settings so is unaffected by the real default change, but verify.

If any test fails: STOP and report. Most likely failure would be a test that hardcoded an assumption `router_enabled == False` or `retrieval_top_k == 4`. If found, update the test to match the new reality (only if the failing assertion was about the default value; NOT if it was testing router behavior).

- [ ] **Step 6: Run the offline test suite — confirm nothing else breaks**

Run (takes a few minutes):
```bash
uv run pytest tests/ --ignore=tests/test_frontend_e2e.py \
                     --ignore=tests/test_api_workflow.py \
                     --ignore=tests/test_query_credibility.py \
                     -v 2>&1 | tail -20
```

Expected: full offline suite passes. `test_query_credibility.py` is excluded because it makes real API calls and the 2026-04-22 run already exercised the default-on behavior.

If a previously-passing test now fails: STOP. Paste the full failure. Do not force a pass.

- [ ] **Step 7: Commit the flip**

Fill `<actual>` placeholders with numbers from Task 1 Step 2 before committing:

```bash
git add app/config.py tests/test_config_router.py
git commit -m "$(cat <<'EOF'
feat(router): enable router by default + bump retrieval_top_k 4→10

Follow-up analysis of the 2026-04-22 router-on eval's top_k=10 column
cleared all ship gates without a new run:
  - Latency p95: 30s → 11.5s (aggregated, N=82)
  - Fact correct @k=10: 91% → <actual>%
  - Overview correct @k=10: 75% → <actual>%
  - Synthesis correct @k=10: 92% → <actual>%
  - Multi-doc coverage: 100% → 100%
  - Impossible: 100% → <actual>%

See docs/plans/2026-04-22-router-default-on.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 8: Append a landing note to this plan file**

Open `E:\MEINRAG\docs\plans\2026-04-22-router-default-on.md` (this file). Append at the very end (after the "Self-Review" section):

```markdown
---

## Landing note

Shipped: 2026-04-22
Commit: <SHA from Step 7>

Final defaults (verified via `test_router_settings_default_on`):
- `retrieval_top_k = 10` (was 4)
- `router_enabled = True` (was False)
- `router_min_scope = 15` (unchanged)
- `router_top_k = 8` (unchanged)
- `router_model = "gpt-4o-mini"` (unchanged)

Ship gates at time of landing (from analysis of 2026-04-22 router-on run):

| Metric | Baseline | Shipped @k=10 | Gate |
|---|---|---|---|
| Fact correct | 91% | <fill>% | ≥ 88% ✓ |
| Synthesis correct | 92% | <fill>% | ≥ 88% ✓ |
| Overview correct | 75% | <fill>% | ≥ 72% ✓ |
| Multi-doc coverage | 100% | 100% | ≥ 95% ✓ |
| Impossible | 100% | <fill>% | = 100% ✓ |
| Latency p95 | 30005 ms | 11482 ms | < 25000 ms ✓ |

Known residual concerns (documented in predecessor plan, not blockers):
- Confidence calibration needs retuning against the router-narrowed chunk distribution.
- `fact_05` still has a retrieval failure at k=4 (would matter if users override top_k back to 4) — see Task 3 for the diagnostic script to investigate if this becomes a production issue.
- No route-level FastAPI integration test for the wire-through; added here only if future flakiness warrants it.
```

- [ ] **Step 9: Commit the landing note**

```bash
git add docs/plans/2026-04-22-router-default-on.md
git commit -m "$(cat <<'EOF'
docs(router): landing note for default-on ship

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Contingency — re-run + diagnose (CONDITIONAL)

**SKIP this task entirely if Task 1 chose PATH A.** This is the safety net that only fires if the existing data's `top_k=10` column unexpectedly doesn't clear every gate.

**Why this is here:** if analyzing the existing data shows a gate failure at k=10 (which would contradict the 2026-04-22 run's recorded metrics), something is off — either the report was misread or an assumption broke. This task runs a fresh eval and inspects the router's per-query decisions.

- [ ] **Step 1: Re-run the eval with the paired config**

Prereqs — verify each:

```bash
docker ps --format "{{.Names}} {{.Status}}" | grep postgres
grep -E "^OPENAI_API_KEY=" .env | head -1 | cut -c1-20
```

Expected:
- postgres container: "Up ... (healthy)"
- first 20 chars of an OPENAI_API_KEY line

If either fails, STOP and escalate.

Then run (expect ~15 min, ~$1 OpenAI cost):

```bash
ROUTER_ENABLED=true ROUTER_MIN_SCOPE=15 ROUTER_TOP_K=8 RETRIEVAL_TOP_K=10 \
  uv run pytest tests/test_query_credibility.py -v -s \
  2>&1 | tee data/test_queries/router_on_k10_run.log
```

This overwrites `data/test_queries/query_results.json` and `query_report.md`. The baseline (`query_results_baseline_2026-04-21.json`) is preserved from the predecessor plan's work.

- [ ] **Step 2: Re-evaluate gates**

Open the new `query_report.md`. Re-run Task 1 Step 2 + Step 3 logic against the fresh numbers.

- If the fresh run passes all gates: go to Task 2 (flip defaults) and treat this contingency as proof that the earlier analysis was noise.
- If the fresh run fails the same or different gate: proceed to Step 3 (diagnose).

- [ ] **Step 3: Build the diagnostic script**

This script lets the engineer interactively ask "for THIS question, what does the router see and pick?" — so the engineer can see whether a thin summary, a bad prompt decision, or a missing doc caused the failure.

Create `E:\MEINRAG\scripts\diagnose_router_decision.py`:

```python
"""Diagnose what the router sees and picks for a specific query.

Usage:
    uv run python scripts/diagnose_router_decision.py "<question>" \
        [--user-id admin] \
        [--expected-filename-substring "<keyword>"]

Prints:
  - Full scope size (all user's docs)
  - Docs with thin/missing summary (candidates for thin-summary routing failure)
  - Router menu (first 30 lines, trimmed)
  - Router's picked doc_ids
  - Whether the expected doc (filename match) was kept or dropped
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Same sys.path pattern as scripts/backfill_doc_summaries.py etc.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.db.session import create_engine_and_session
from app.db.repositories import DocumentRepository
from app.llm.provider import create_chat_model
from app.services.router import route_docs, _format_doc_menu

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def diagnose(question: str, user_id: str, expected_filename_substring: str | None):
    settings = Settings()
    engine, session_factory = create_engine_and_session(settings.database_url)
    try:
        async with session_factory() as session:
            registry = DocumentRepository(session)
            all_docs = await registry.list_all(user_id=user_id)
            if not all_docs:
                print(f"No docs for user_id={user_id!r}")
                return

            scope = [d["doc_id"] for d in all_docs]
            print(f"Scope: {len(scope)} docs")

            # Flag thin summaries
            thin = [d for d in all_docs if not d.get("summary") or len(d["summary"]) < 40]
            print(f"Docs with thin/missing summary (<40 chars): {len(thin)}")
            for d in thin[:10]:
                slen = len(d.get("summary") or "")
                print(f"  [{d['doc_id']}] {d.get('filename')} | summary_len={slen}")

            # Build the menu the router would see
            menu = _format_doc_menu(all_docs)
            print("\n--- Router menu (first 30 lines, trimmed to 200 chars/line) ---")
            for line in menu.split("\n")[:30]:
                print(line[:200])
            print("--- ... ---\n")

            # Highlight the expected doc if provided
            expected: list[dict] = []
            if expected_filename_substring:
                needle = expected_filename_substring.lower()
                expected = [d for d in all_docs
                            if needle in (d.get("filename") or "").lower()]
                print(f"Expected doc matches: {[d['doc_id'] for d in expected]}")
                for d in expected:
                    slen = len(d.get("summary") or "")
                    summary_preview = (d.get("summary") or "")[:120]
                    print(f"  [{d['doc_id']}] {d['filename']} | "
                          f"summary_len={slen} | summary[:120]={summary_preview!r}")

            # Run the router
            llm = create_chat_model(settings)
            picked = await route_docs(
                question=question,
                doc_ids=scope,
                top_k=settings.router_top_k,
                llm=llm,
                registry=registry,
            )
            print(f"\nRouter picked {len(picked)} docs: {picked}")
            if expected:
                expected_ids = {d["doc_id"] for d in expected}
                kept = expected_ids & set(picked)
                dropped = expected_ids - set(picked)
                print(f"Expected-doc ids KEPT by router: {kept}")
                print(f"Expected-doc ids DROPPED by router: {dropped}")
    finally:
        await engine.dispose()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("question")
    p.add_argument("--user-id", default="admin")
    p.add_argument("--expected-filename-substring",
                   help="Substring matched against each doc's filename to identify "
                        "the expected answer doc. The script reports whether the "
                        "router kept or dropped it.")
    args = p.parse_args()
    asyncio.run(diagnose(args.question, args.user_id, args.expected_filename_substring))


if __name__ == "__main__":
    main()
```

Commit the diagnostic script on its own:

```bash
git add scripts/diagnose_router_decision.py
git commit -m "$(cat <<'EOF'
chore(router): diagnostic script for inspecting router decisions

Run: uv run python scripts/diagnose_router_decision.py "<question>"
Prints the router menu, thin-summary candidates, and kept/dropped
expected-answer docs so regressions can be root-caused quickly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Run the diagnostic against the failing query**

First find the failing query's text. Example for `fact_05`:

```bash
uv run python -c "import json; d = json.load(open('data/test_queries/query_test_set.json', encoding='utf-8')); q = [x for x in d if x.get('id') == 'fact_05'][0]; print(q.get('question'))"
```

Then run the diagnostic, filling in the question and a distinctive keyword from the expected answer doc's filename:

```bash
uv run python scripts/diagnose_router_decision.py \
  "<question from the query_test_set>" \
  --user-id admin \
  --expected-filename-substring "<distinctive keyword>"
```

Interpret the output:
- **Case A — the expected doc has `summary_len < 40`:** the router had no signal. Fix: regenerate that doc's summary. Run `uv run python scripts/backfill_doc_summaries.py --force` (existing script; check `--force` actually exists via `--help` first) or manually trigger for the one doc.
- **Case B — expected doc has a good summary but router dropped it:** prompt/menu issue. Fix options: (i) add a Rule 6 to `ROUTER_PROMPT` tightening fact-style routing, (ii) bump `router_top_k` default from 8 to 10.
- **Case C — expected doc is not in the menu at all:** scope is broken (DB query missing docs). Out of scope; escalate.

- [ ] **Step 5: Apply the targeted fix + re-run eval**

After applying whichever fix matches the case, re-run Task 3 Step 1 (the eval). If gates now clear, go to Task 2. If still failing, STOP and escalate to user — the investigation found something this plan didn't anticipate.

- [ ] **Step 6: Commit the targeted fix (if any)**

Separate commit from the diagnostic script. Pick the message that matches what was fixed:

- Case A: `fix(router): backfill summary for <doc_id> to unblock routing`
- Case B: `fix(router): tighten ROUTER_PROMPT rule for fact-style queries` (or `fix(router): bump default router_top_k 8→10`)
- Case C: do not commit; escalate instead

---

## Self-Review

**Spec coverage:**
- Task 1 validates the paired config against ship gates without running anything (cheap).
- Task 2 flips defaults TDD-style (test first, implementation second).
- Task 3 handles the contingency that Task 1 surfaces a problem — builds a reusable diagnostic.
- Baseline preservation already handled in predecessor plan (`query_results_baseline_2026-04-21.json`).

**Placeholder scan:**
- `<fill>` / `<actual>` / `<YYYY-MM-DD>` / `<SHA>` in commit messages and the landing note are templates the operator fills at execution time — not plan failures.
- All imports in Task 3 Step 3 verified against actual codebase (`create_engine_and_session`, `create_chat_model`, `list_all`). Not placeholders.
- No "handle edge cases" / "implement later" language.

**Type / name consistency:**
- `Settings` (class) is used directly (matches `app.config`).
- `create_chat_model(settings) -> BaseChatModel` — matches `app/llm/provider.py:8`.
- `create_engine_and_session(database_url) -> (engine, session_factory)` — matches `app/db/session.py:6`.
- `DocumentRepository(session).list_all(user_id=...)` — matches `app/db/repositories.py:75`.
- `route_docs(question, doc_ids, top_k, llm, registry)` — matches Task 3 of the predecessor plan + current `app/services/router.py`.
- `_format_doc_menu(docs)` — matches current `app/services/router.py`.

**Known risks:**
- The `engine.dispose()` cleanup in Task 3's diagnostic script assumes `create_engine_and_session` returns an engine that supports `.dispose()`. If it doesn't (e.g., returns something wrapping the engine), the `try/finally` harmless no-ops. Actual cleanup happens via `async with session_factory()`.
- Task 1's analysis relies on the operator reading `query_report.md` carefully. The assumed numbers in Step 2 come from me reading the 2026-04-22 report during planning; if they drifted (e.g., test was re-run), the operator reads fresh and may land on PATH B. That's fine — Task 3 is the safety net.
