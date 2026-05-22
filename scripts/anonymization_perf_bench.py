"""Measure anonymization overhead per chunk on a 100-chunk synthetic doc.

Acceptance per plan §6.5: <100 ms overhead per chunk (p95).

The script:
  1. Configures Settings with anonymization enabled (en only — zh adds
     5-15s cold start that we don't want in this bench).
  2. Warms the engine (forces the lazy load of spaCy + Presidio) so
     the timing loop measures steady-state cost only.
  3. Runs analyze_and_anonymize on a synthetic chunk 100 times.
  4. Prints p50/p95/p99/mean and a PASS/FAIL gate.

Exit code 0 if p95 < 100ms, 1 otherwise.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path when the script is run directly
# (uv run does not add it automatically for files under scripts/).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.fernet import Fernet

from app.anonymization import AnonymizationEngine, EntityRegistry
from app.config import Settings


def main() -> int:
    settings = Settings(
        anonymization_enabled=True,
        anonymization_encryption_key=Fernet.generate_key().decode(),
        anonymization_languages=["en"],
        openai_api_key="not-used-by-presidio",
    )
    engine = AnonymizationEngine(settings)

    # Force the lazy init OUTSIDE the timing loop so the first call's
    # cold-start (5-15s for spaCy model load) doesn't pollute p99.
    print("Warming up engine (lazy-load spaCy + Presidio)...")
    t_warmup = time.perf_counter()
    engine.analyze_and_anonymize("warmup", EntityRegistry())
    print(f"  Warmup took {(time.perf_counter() - t_warmup):.2f}s")

    sample = (
        "On 2026-04-15, Alice Smith (alice.smith@example.com) called "
        "Bob Jones at 555-123-4567 regarding case 24-CV-9981."
    )

    print(f"\nMeasuring 100 iterations on a {len(sample)}-char sample...")
    durations_ms: list[float] = []
    for _ in range(100):
        reg = EntityRegistry()
        t0 = time.perf_counter()
        engine.analyze_and_anonymize(sample, reg)
        durations_ms.append((time.perf_counter() - t0) * 1000)

    p50 = statistics.median(durations_ms)
    p95 = statistics.quantiles(durations_ms, n=20)[-1]
    p99 = max(durations_ms)
    mean = statistics.mean(durations_ms)

    print(f"\nper-chunk overhead (ms): mean={mean:.1f} p50={p50:.1f} p95={p95:.1f} p99={p99:.1f}")
    print(f"\nAcceptance: p95 < 100 ms -> {'PASS' if p95 < 100 else 'FAIL'}")
    return 0 if p95 < 100 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
