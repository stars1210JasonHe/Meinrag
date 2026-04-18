"""Tests for scoring profile loading, override resolution, and domain-specific behavior."""
import pytest
from langchain_core.documents import Document

from app.services.scoring_profile import (
    ScoringProfile,
    ResolvedScoring,
    load_scoring_profile,
    _build_profile,
)


# ---------------------------------------------------------------------------
# Profile loading
# ---------------------------------------------------------------------------

class TestProfileLoading:
    def test_general_profile_loads(self):
        profile = load_scoring_profile("general")
        assert profile.name == "general"

    def test_academic_profile_loads(self):
        profile = load_scoring_profile("academic")
        assert profile.name == "academic"

    def test_law_profile_loads(self):
        profile = load_scoring_profile("law")
        assert profile.name == "law"

    def test_unknown_profile_falls_back_to_general(self):
        profile = load_scoring_profile("nonexistent_domain_xyz")
        assert profile.name == "general"

    def test_profile_is_frozen(self):
        profile = load_scoring_profile("general")
        with pytest.raises(AttributeError):
            profile.name = "hacked"

    def test_normalization_field_parsed(self):
        """Profiles declare their normalization mode — default ships with absolute."""
        profile = load_scoring_profile("general")
        assert profile.normalization == "absolute"
        assert profile.normalization_k == pytest.approx(1.5)  # default k (only used in tanh mode)

    def test_normalization_defaults_when_missing(self):
        """A profile with no normalization field now defaults to absolute."""
        from app.services.scoring_profile import _build_profile
        profile = _build_profile({"name": "minimal"})
        assert profile.normalization == "absolute"

    def test_normalization_custom_k(self):
        """Profile can override the k parameter (tanh mode)."""
        profile = _build_profile({
            "name": "custom",
            "normalization": "tanh",
            "normalization_k": 2.5,
        })
        assert profile.normalization == "tanh"
        assert profile.normalization_k == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# Override resolution: defaults < profile < query_type
# ---------------------------------------------------------------------------

class TestOverrideResolution:
    def test_defaults_without_query_type(self):
        """for_query_type(None) returns profile defaults."""
        profile = load_scoring_profile("general")
        scoring = profile.for_query_type()
        assert scoring.reference_penalty == 0.3
        assert scoring.boilerplate_penalty == 0.2
        assert scoring.section_weights["acknowledgment"] == 0.4

    def test_academic_defaults_differ_from_general(self):
        gen = load_scoring_profile("general").for_query_type()
        acad = load_scoring_profile("academic").for_query_type()
        assert acad.section_weights["abstract"] > gen.section_weights["abstract"]
        assert acad.boilerplate_penalty < gen.boilerplate_penalty

    def test_query_type_override_merges_on_top(self):
        """academic + fact should override abstract to 1.3 (profile default is 1.2)."""
        profile = load_scoring_profile("academic")
        default_scoring = profile.for_query_type()
        fact_scoring = profile.for_query_type("fact")
        assert default_scoring.section_weights["abstract"] == 1.2
        assert fact_scoring.section_weights["abstract"] == 1.3

    def test_non_overridden_keys_inherit_from_defaults(self):
        """fact override only sets abstract/results — methods should inherit from profile defaults."""
        profile = load_scoring_profile("academic")
        fact_scoring = profile.for_query_type("fact")
        assert fact_scoring.section_weights["methods"] == 1.1  # from academic defaults

    def test_overview_has_different_overrides_than_fact(self):
        profile = load_scoring_profile("academic")
        fact = profile.for_query_type("fact")
        overview = profile.for_query_type("overview")
        assert fact.section_weights["abstract"] != overview.section_weights["abstract"]

    def test_unknown_query_type_uses_defaults(self):
        """Query type not in overrides falls back to profile defaults."""
        profile = load_scoring_profile("academic")
        scoring = profile.for_query_type("nonexistent_type")
        assert scoring.section_weights["abstract"] == 1.2  # profile default, no override

    def test_penalty_override_per_query_type(self):
        profile = load_scoring_profile("academic")
        default = profile.for_query_type()
        fact = profile.for_query_type("fact")
        assert default.reference_penalty == 0.25
        assert fact.reference_penalty == 0.2  # fact override

    def test_graph_edge_weights_override(self):
        profile = load_scoring_profile("academic")
        default = profile.for_query_type()
        reference = profile.for_query_type("reference")
        # reference override sets references edge weight to 1.0
        assert reference.edge_type_weights["references"] == 1.0
        # follows should still inherit from academic defaults
        assert reference.edge_type_weights["follows"] == 0.3


class TestBuildProfileDefaults:
    def test_empty_data_gets_all_defaults(self):
        profile = _build_profile({"name": "empty"})
        scoring = profile.for_query_type()
        assert scoring.section_weights["abstract"] == 1.0
        assert scoring.reference_penalty == 0.3
        assert scoring.boilerplate_penalty == 0.2
        assert scoring.graph_normalization_factor == 10
        assert scoring.edge_type_weights["follows"] == 1.0

    def test_partial_section_weights_merged(self):
        profile = _build_profile({
            "name": "custom",
            "defaults": {"section_weights": {"abstract": 2.0}},
        })
        scoring = profile.for_query_type()
        assert scoring.section_weights["abstract"] == 2.0
        assert scoring.section_weights["body"] == 1.0  # from built-in defaults

    def test_resolved_scoring_is_frozen(self):
        scoring = load_scoring_profile("general").for_query_type()
        with pytest.raises(AttributeError):
            scoring.reference_penalty = 0.99


# ---------------------------------------------------------------------------
# Domain behavior verification
# ---------------------------------------------------------------------------

class TestAcademicProfileBehavior:
    def test_abstract_boosted_in_academic(self):
        from app.services.retrieval import _apply_section_weights
        gen = load_scoring_profile("general").for_query_type()
        acad = load_scoring_profile("academic").for_query_type()
        results = [(Document(page_content="Abstract text", metadata={"section_type": "abstract"}), 0.5)]
        assert _apply_section_weights(results, acad)[0][1] > _apply_section_weights(results, gen)[0][1]

    def test_abstract_boosted_more_for_overview(self):
        from app.services.retrieval import _apply_section_weights
        profile = load_scoring_profile("academic")
        fact = profile.for_query_type("fact")
        overview = profile.for_query_type("overview")
        results = [(Document(page_content="Abstract", metadata={"section_type": "abstract"}), 0.5)]
        fact_score = _apply_section_weights(results, fact)[0][1]
        overview_score = _apply_section_weights(results, overview)[0][1]
        assert overview_score > fact_score  # overview weights abstract at 1.5 vs fact at 1.3

    def test_boilerplate_more_penalized_in_academic(self):
        from app.services.retrieval import _apply_boilerplate_penalty
        gen = load_scoring_profile("general").for_query_type()
        acad = load_scoring_profile("academic").for_query_type()
        results = [(Document(page_content="* Equal contribution.", metadata={}), 0.9)]
        assert _apply_boilerplate_penalty(results, acad)[0][1] < _apply_boilerplate_penalty(results, gen)[0][1]


class TestEdgeTypeWeighting:
    @pytest.mark.asyncio
    async def test_follows_edges_demoted_in_academic(self):
        from app.services.retrieval import _apply_composite_scoring

        gen = load_scoring_profile("general").for_query_type()
        acad = load_scoring_profile("academic").for_query_type()

        doc = Document(
            page_content="text",
            metadata={"doc_id": "d1", "chunk_index": 0, "section_type": "methods"},
        )
        retrieved = [(doc, 0.5)]

        class TypedEdgeRepo:
            async def get_edge_type_counts_batch(self, doc_id, indices):
                return {0: {"follows": 10}}

        class FakeSettings:
            query_types_file = "data/query_types.json"

        gen_result = await _apply_composite_scoring(retrieved, TypedEdgeRepo(), "fact", FakeSettings(), gen)
        acad_result = await _apply_composite_scoring(retrieved, TypedEdgeRepo(), "fact", FakeSettings(), acad)

        _, gen_score = gen_result[0]
        _, acad_score = acad_result[0]
        # general: follows=1.0 → graph=1.0; academic: follows=0.3 → graph=0.3
        assert gen_score > acad_score


# ---------------------------------------------------------------------------
# Confidence tiers
# ---------------------------------------------------------------------------

class TestConfidenceTiers:
    def test_general_tiers(self):
        profile = load_scoring_profile("general")
        assert profile.confidence_tiers == {"high": 0.50, "moderate": 0.30}

    def test_law_stricter_tiers(self):
        profile = load_scoring_profile("law")
        assert profile.confidence_high == 0.55
        assert profile.confidence_moderate == 0.35


# ---------------------------------------------------------------------------
# Config separation — profile doesn't overlap with query_types.json or .env
# ---------------------------------------------------------------------------

class TestConfigSeparation:
    def test_profile_has_no_composite_weights(self):
        profile = load_scoring_profile("general")
        assert not hasattr(profile, "weights")
        assert not hasattr(profile, "composite_weights")

    def test_profile_has_no_feature_flags(self):
        profile = load_scoring_profile("general")
        assert not hasattr(profile, "rerank_enabled")
        assert not hasattr(profile, "hybrid_search_enabled")

    def test_profile_has_no_model_selection(self):
        profile = load_scoring_profile("general")
        assert not hasattr(profile, "embedding_model")
        assert not hasattr(profile, "rerank_model")

    def test_resolved_scoring_has_no_composite_weights(self):
        scoring = load_scoring_profile("general").for_query_type("fact")
        assert not hasattr(scoring, "weights")
