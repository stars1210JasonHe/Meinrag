# Contributing to MEINRAG

Thanks for your interest. This is a personal-scale RAG project that's still iterating; PRs welcome but please open an issue first for anything bigger than a typo or one-line bug fix so we can align on direction.

## Quick links

- Bug or unexpected behaviour → [open a bug report](https://github.com/stars1210JasonHe/Meinrag/issues/new?template=bug_report.md)
- Feature idea → [open a feature request](https://github.com/stars1210JasonHe/Meinrag/issues/new?template=feature_request.md)
- General question → use [GitHub Discussions](https://github.com/stars1210JasonHe/Meinrag/discussions) (or an issue if discussions aren't enabled)

## Development setup

See the **Quick start → Dev mode** section in [README.md](README.md). TL;DR:

```bash
git clone https://github.com/stars1210JasonHe/Meinrag.git
cd Meinrag
cp .env.example .env  # set OPENAI_API_KEY
docker compose up -d  # starts Postgres
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

cd frontend && npm install && npm run dev
```

## Running tests

```bash
# Offline suite (no API key, no servers — runs in <30s)
uv run pytest tests/ --ignore=tests/test_frontend_e2e.py --ignore=tests/test_api_workflow.py -v

# Online suite (needs OPENAI_API_KEY)
uv run pytest tests/test_api_workflow.py -v

# Frontend E2E (needs both servers + Playwright)
uv run pytest tests/test_frontend_e2e.py -v -s
```

The credibility benchmark (`scripts/test_dev_credibility.py`) checks 14 curated queries against the dev corpus and scores them with an LLM judge — a useful smoke test for retrieval-quality regressions.

## Pull request guidelines

1. **Branch off `main`** and keep PRs scoped to one logical change.
2. **Run the offline test suite** before pushing. If you change retrieval behaviour, run the credibility benchmark too.
3. **Commit messages** follow Conventional Commits where reasonable: `feat(scope): summary`, `fix(scope): summary`, `chore(scope): summary`. The scope is the affected area (e.g. `chat`, `graph`, `mindmap`, `api`).
4. **DB schema changes** require an Alembic migration: `uv run alembic revision --autogenerate -m "describe change"`. Eyeball the generated migration before committing.
5. **Frontend changes** that affect rendering should include a manual UX check in both light and dark themes (CSS-var driven; toggle in the header).
6. **No secrets in commits.** `.env` is gitignored; verify with `git status` before pushing.

## Code style

- Python: type hints required for new code. Async functions use `async def` (no fake-async wrappers).
- JS/TS: idiomatic React 19; functional components + hooks. No class components.
- Comments default to off — only add when the *why* is non-obvious.

## What we're trying to keep stable

- The `app/services/retrieval.py` pipeline shape (extending the chain via flags is fine; reordering stages is a bigger conversation).
- The 5-edge-type schema in `chunk_edges`. New edge types need a migration + matching frontend handling.
- The Pydantic `Settings` class is the single source of truth for configuration. New flags belong there.

## Questions before you start

If you're unsure whether something fits the project's scope, please open an issue first. The project's strategic stance is documented in `MEMORY.md`-style memos in the maintainer's local notes (not all visible in the repo) — when in doubt, ask.
