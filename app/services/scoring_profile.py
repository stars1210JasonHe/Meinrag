"""Domain-specific scoring profile loader.

Scoring profiles control the *math inside each scoring stage*:
  - Section weights (how much to weight abstract, methods, etc.)
  - Penalties (reference section, boilerplate)
  - Graph scoring params (normalization factor, edge-type weights)
  - Confidence tiers (raw cosine score -> tier mapping)

Override resolution order:
  1. query_type_overrides[query_type] (most specific)
  2. defaults (profile-level)
  3. built-in defaults (code-level)

Scoring profiles do NOT control:
  - Composite weights (sim/graph/rec/auth) -> query_types.json
  - Feature flags (rerank_enabled, etc.) -> .env / Settings
  - Model selection -> .env / Settings
  - Document classification -> taxonomy.json
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_PROFILES_DIR = Path("data/scoring_profiles")

_DEFAULT_SECTION_WEIGHTS = {
    "abstract": 1.0,
    "introduction": 1.0,
    "related_work": 0.9,
    "methods": 1.0,
    "training": 1.0,
    "results": 1.0,
    "discussion": 1.0,
    "conclusion": 1.0,
    "references": 1.0,
    "appendix": 0.7,
    "acknowledgment": 0.4,
    "body": 1.0,
}

_DEFAULT_PENALTIES = {
    "reference_section": 0.3,
    "boilerplate": 0.2,
}

_DEFAULT_EDGE_TYPE_WEIGHTS = {
    "follows": 1.0,
    "co_located": 1.0,
    "describes": 1.0,
    "references": 1.0,
    "similar_to": 1.0,
}

_DEFAULT_GRAPH = {
    "normalization_factor": 10,
    "edge_type_weights": _DEFAULT_EDGE_TYPE_WEIGHTS,
    "expansion_score_decay": 0.8,
}

_DEFAULT_CONFIDENCE = {
    "high": 0.50,
    "moderate": 0.30,
}


@dataclass(frozen=True)
class ScoringProfile:
    """Immutable scoring profile with per-query-type override support.

    Call `for_query_type(qt)` to get resolved values for a specific query type.
    """
    name: str
    description: str
    _defaults: dict
    _overrides: dict  # {query_type: {partial overrides}}
    normalization: str
    confidence_high: float
    confidence_moderate: float

    @property
    def confidence_tiers(self) -> dict[str, float]:
        return {"high": self.confidence_high, "moderate": self.confidence_moderate}

    def for_query_type(self, query_type: str | None = None) -> ResolvedScoring:
        """Resolve scoring constants for a specific query type.

        Merges: built-in defaults < profile defaults < query_type overrides.
        """
        defaults = self._defaults
        overrides = self._overrides.get(query_type, {}) if query_type else {}

        section_weights = {
            **_DEFAULT_SECTION_WEIGHTS,
            **defaults.get("section_weights", {}),
            **overrides.get("section_weights", {}),
        }

        d_penalties = defaults.get("penalties", {})
        o_penalties = overrides.get("penalties", {})
        reference_penalty = o_penalties.get(
            "reference_section",
            d_penalties.get("reference_section", _DEFAULT_PENALTIES["reference_section"]),
        )
        boilerplate_penalty = o_penalties.get(
            "boilerplate",
            d_penalties.get("boilerplate", _DEFAULT_PENALTIES["boilerplate"]),
        )

        d_graph = defaults.get("graph", {})
        o_graph = overrides.get("graph", {})
        normalization_factor = o_graph.get(
            "normalization_factor",
            d_graph.get("normalization_factor", _DEFAULT_GRAPH["normalization_factor"]),
        )
        edge_type_weights = {
            **_DEFAULT_EDGE_TYPE_WEIGHTS,
            **d_graph.get("edge_type_weights", {}),
            **o_graph.get("edge_type_weights", {}),
        }
        expansion_score_decay = o_graph.get(
            "expansion_score_decay",
            d_graph.get("expansion_score_decay", _DEFAULT_GRAPH["expansion_score_decay"]),
        )

        return ResolvedScoring(
            section_weights=section_weights,
            reference_penalty=reference_penalty,
            boilerplate_penalty=boilerplate_penalty,
            graph_normalization_factor=normalization_factor,
            edge_type_weights=edge_type_weights,
            graph_expansion_score_decay=expansion_score_decay,
        )


@dataclass(frozen=True)
class ResolvedScoring:
    """Fully resolved scoring constants for one query type."""
    section_weights: dict[str, float]
    reference_penalty: float
    boilerplate_penalty: float
    graph_normalization_factor: float
    edge_type_weights: dict[str, float]
    graph_expansion_score_decay: float


def _build_profile(data: dict) -> ScoringProfile:
    tiers = data.get("defaults", data).get("confidence_tiers", data.get("confidence_tiers", {}))
    defaults = data.get("defaults", {})
    if not defaults:
        defaults = {
            k: v for k, v in data.items()
            if k not in ("name", "description", "query_type_overrides", "normalization", "confidence_tiers")
        }

    return ScoringProfile(
        name=data.get("name", "unknown"),
        description=data.get("description", ""),
        _defaults=defaults,
        _overrides=data.get("query_type_overrides", {}),
        normalization=data.get("normalization", "max_scale"),
        confidence_high=tiers.get("high", _DEFAULT_CONFIDENCE["high"]),
        confidence_moderate=tiers.get("moderate", _DEFAULT_CONFIDENCE["moderate"]),
    )


@lru_cache(maxsize=4)
def load_scoring_profile(name: str = "general") -> ScoringProfile:
    path = _PROFILES_DIR / f"{name}.json"
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            logger.info("Loaded scoring profile '%s' from %s", name, path)
            return _build_profile(data)
        except Exception as e:
            logger.warning("Failed to load scoring profile '%s': %s, using general", name, e)

    if name != "general":
        logger.warning("Scoring profile '%s' not found at %s, falling back to general", name, path)
        return load_scoring_profile("general")

    logger.info("Using built-in default scoring profile (general)")
    return _build_profile({"name": "general", "description": "Default scoring — matches original hardcoded values"})
