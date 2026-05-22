"""Compare dev-corpus credibility metrics with/without anonymization.

Runs scripts/test_dev_credibility.py twice — once with the flag off
(baseline), once with the flag on (post-anonymization re-ingest of
the same corpus) — and reports the delta per metric.

Acceptance per plan §6.4:
  - ≥13/14 correct (anon-on), vs the 14/14 baseline
  - No single query going correct → incorrect
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPORT = Path("tmp/anonymization_regression.json")
DEV_CRED_SCRIPT = Path("scripts/test_dev_credibility.py")


def _run(env: dict[str, str]) -> dict:
    """Invoke the credibility script and parse its JSON output."""
    result = subprocess.run(
        ["uv", "run", "python", str(DEV_CRED_SCRIPT), "--json"],
        capture_output=True, text=True,
        env={**os.environ, **env},
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(f"Credibility run failed (env={env}):\n{result.stderr}\n")
        sys.exit(2)
    # The script may print human-readable lines too. Find the JSON line.
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    # If we couldn't find JSON, the script's --json output is broken
    sys.stderr.write(f"Could not parse JSON from credibility output:\n{result.stdout[:2000]}\n")
    sys.exit(3)


def main() -> int:
    REPORT.parent.mkdir(parents=True, exist_ok=True)

    print("→ Running baseline (anonymization OFF)…")
    base = _run({"ANONYMIZATION_ENABLED": "false"})

    print("→ Running with anonymization ON…")
    anon = _run({"ANONYMIZATION_ENABLED": "true"})

    base_per_query = {q["id"]: q["correct"] for q in base["per_query"]}
    anon_per_query = {q["id"]: q["correct"] for q in anon["per_query"]}

    regressed = [
        qid for qid in base_per_query
        if base_per_query[qid] and not anon_per_query.get(qid, False)
    ]

    delta = {
        "baseline_correct": base["correct_count"],
        "anonymization_correct": anon["correct_count"],
        "total_queries": base["total"],
        "regressed_queries": regressed,
    }

    REPORT.write_text(json.dumps(delta, indent=2))
    print(f"\nReport written to: {REPORT}")

    correct_anon = delta["anonymization_correct"]
    total = delta["total_queries"]
    threshold = max(1, total - 1)  # allow at most 1 regression
    if correct_anon < threshold:
        print(
            f"FAIL: anonymized credibility {correct_anon}/{total} < "
            f"threshold {threshold}/{total}",
        )
        return 1
    if regressed:
        print(
            f"WARNING: {len(regressed)} queries went correct→incorrect: {regressed}",
        )
    print(f"PASS: {correct_anon}/{total} (baseline {delta['baseline_correct']}/{total})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
