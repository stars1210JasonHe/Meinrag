"""Configurable query type system.

Loads query types from a JSON config file. Each type defines:
- name: identifier (e.g., "fact", "overview")
- description: for LLM classification prompt
- strategy: retrieval strategy ("top_k", "section_sampling", "label_lookup")
- weights: [similarity, graph, recency, authority] scoring weights
"""
import json
import logging
from pathlib import Path
from functools import lru_cache

logger = logging.getLogger(__name__)

_DEFAULT_TYPES = {
    "types": [
        {"name": "fact", "description": "specific data lookup", "strategy": "top_k", "weights": [0.8, 0.1, 0.0, 0.1]},
        {"name": "overview", "description": "broad coverage, summarization", "strategy": "section_sampling", "weights": [0.5, 0.2, 0.1, 0.2]},
        {"name": "reference", "description": "asks about a specific table/figure/equation by number", "strategy": "label_lookup", "weights": [0.3, 0.3, 0.0, 0.4]},
        {"name": "exploratory", "description": "open exploration, comparison", "strategy": "top_k", "weights": [0.6, 0.2, 0.1, 0.1]},
    ],
    "label_instruction": "If reference type, extract the label normalized to English. null if no reference.",
    "strategies": {
        "top_k": {"fetch_multiplier": 1.5, "demote_references": True},
        "section_sampling": {"fetch_multiplier": 25, "text_only": True, "demote_references": False},
        "label_lookup": {"fetch_multiplier": 1.5, "demote_references": True},
    },
}


@lru_cache(maxsize=1)
def load_query_types(config_path: str = "data/query_types.json") -> dict:
    """Load query types from JSON config. Falls back to defaults if file missing."""
    path = Path(config_path)
    if path.exists():
        try:
            with open(path) as f:
                data = json.load(f)
            logger.info("Loaded %d query types from %s", len(data.get("types", [])), path)
            return data
        except Exception as e:
            logger.warning("Failed to load query types from %s: %s, using defaults", path, e)
    return _DEFAULT_TYPES


def get_type_names(config: dict) -> list[str]:
    """Get list of valid type names."""
    return [t["name"] for t in config.get("types", [])]


def get_type_config(config: dict, type_name: str) -> dict | None:
    """Get config for a specific type."""
    for t in config.get("types", []):
        if t["name"] == type_name:
            return t
    return None


def get_strategy(config: dict, strategy_name: str) -> dict:
    """Get strategy config by name."""
    return config.get("strategies", {}).get(strategy_name, {"fetch_multiplier": 1.5, "demote_references": True})


def build_analyze_prompt(config: dict) -> str:
    """Build the LLM classification prompt dynamically from config."""
    types = config.get("types", [])
    label_instruction = config.get("label_instruction", "")

    type_lines = []
    for t in types:
        type_lines.append(f"   - {t['name']}: {t['description']}")

    prompt = (
        "Analyze this question and return a JSON object with two fields:\n"
        "1. \"types\": array of ALL applicable types. A question often has MULTIPLE types:\n"
        + "\n".join(type_lines) + "\n"
        "2. \"label\": " + label_instruction + "\n"
        "Return ONLY valid JSON, nothing else."
    )
    return prompt
