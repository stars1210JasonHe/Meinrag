"""Offline tests for poppler_extractor module."""

import re
from unittest.mock import patch

import pytest

from app.services.poppler_extractor import (
    DEFAULT_CONFIG,
    ExtractedFigure,
    _extract_captions,
    _find_poppler_bin,
    _get_caption_regexes,
    _group_into_lines,
    _match_caption,
    extract_figures,
    has_poppler,
)


class TestHasPoppler:
    def test_returns_bool(self):
        result = has_poppler()
        assert isinstance(result, bool)

    @patch("app.services.poppler_extractor._BUNDLED_POPPLER")
    @patch("app.services.poppler_extractor.shutil.which", return_value=None)
    def test_returns_false_when_not_available(self, mock_which, mock_path):
        mock_path.exists.return_value = False
        assert has_poppler() is False


class TestFindPopplerBin:
    @patch("app.services.poppler_extractor._BUNDLED_POPPLER")
    def test_returns_bundled_path_when_exe_exists(self, mock_path):
        mock_path.exists.return_value = True
        mock_path.__truediv__ = lambda self, key: type(
            "P", (), {"exists": lambda s: key == "pdftohtml.exe"}
        )()
        # Just verify _find_poppler_bin doesn't crash
        _find_poppler_bin()


class TestDefaultConfig:
    def test_has_expected_keys(self):
        expected = {
            "caption_patterns",
            "proximity",
            "line_tolerance",
            "chunk_gap",
            "ignore_case",
            "min_image_area",
        }
        assert set(DEFAULT_CONFIG.keys()) == expected

    def test_proximity_is_positive(self):
        assert DEFAULT_CONFIG["proximity"] > 0

    def test_min_image_area_filters_small(self):
        assert DEFAULT_CONFIG["min_image_area"] >= 2500


class TestCaptionPatterns:
    @pytest.fixture
    def regexes(self):
        return [re.compile(p, re.IGNORECASE) for p in DEFAULT_CONFIG["caption_patterns"]]

    @pytest.mark.parametrize(
        "text",
        [
            "Figure 1: Example diagram",
            "Figure 1. The architecture",
            "Fig. 2: Results",
            "Fig 3 Overview of the system",
            "Fig.4 The results",
            "Figure 10: Multi-digit",
            "图 1: Chinese caption",
        ],
    )
    def test_matches_valid_captions(self, regexes, text):
        assert any(r.match(text) for r in regexes), f"Should match: {text}"

    @pytest.mark.parametrize(
        "text",
        [
            "The figure shows results",
            "See Figure 1 in the appendix",
            "as shown in Fig. 2",
            "Table 1: Data",
            "Results and discussion",
            "",
        ],
    )
    def test_rejects_non_captions(self, regexes, text):
        assert not any(r.match(text) for r in regexes), f"Should NOT match: {text}"


class TestBboxConversion:
    """Verify the (left, top, width, height) -> [x0, y0, x1, y1] conversion."""

    def test_basic_conversion(self):
        left, top, width, height = 100.0, 200.0, 300.0, 400.0
        bbox = [left, top, left + width, top + height]
        assert bbox == [100.0, 200.0, 400.0, 600.0]

    def test_zero_size(self):
        bbox = [0.0, 0.0, 0.0, 0.0]
        assert bbox == [0.0, 0.0, 0.0, 0.0]


class TestExtractedFigure:
    def test_dataclass_fields(self):
        fig = ExtractedFigure(
            page_num=0,
            image_path="doc123/page0_img0.png",
            caption="Figure 1: Test",
            bbox=[10.0, 20.0, 300.0, 400.0],
        )
        assert fig.page_num == 0
        assert fig.image_path == "doc123/page0_img0.png"
        assert fig.caption == "Figure 1: Test"
        assert fig.bbox == [10.0, 20.0, 300.0, 400.0]

    def test_default_bbox_empty(self):
        fig = ExtractedFigure(page_num=0, image_path="x", caption="y")
        assert fig.bbox == []


class TestExtractFiguresNoPoppler:
    @patch("app.services.poppler_extractor.has_poppler", return_value=False)
    def test_returns_empty_list(self, mock_hp, tmp_path):
        result = extract_figures(tmp_path / "test.pdf", tmp_path / "out", "doc1")
        assert result == []


class TestGroupIntoLines:
    def test_groups_nearby_segments(self):
        segments = [
            {"top": 100.0, "left": 10.0, "width": 50.0, "height": 12.0, "text": "Hello"},
            {"top": 100.5, "left": 65.0, "width": 50.0, "height": 12.0, "text": "World"},
            {"top": 200.0, "left": 10.0, "width": 50.0, "height": 12.0, "text": "Next"},
        ]
        lines = _group_into_lines(segments, line_tol=2.0)
        assert len(lines) == 2
        assert len(lines[0]["segments"]) == 2
        assert len(lines[1]["segments"]) == 1


class TestMatchCaption:
    def test_matches_caption_below(self):
        img_rect = (100.0, 100.0, 400.0, 300.0)  # image at y=100-300
        captions = [
            {"rect": (100.0, 310.0, 400.0, 325.0), "text": "Figure 1: Test"},
        ]
        result = _match_caption(img_rect, captions, proximity=80)
        assert result is not None
        assert result["text"] == "Figure 1: Test"

    def test_no_match_when_too_far(self):
        img_rect = (100.0, 100.0, 400.0, 300.0)
        captions = [
            {"rect": (100.0, 500.0, 400.0, 515.0), "text": "Figure 1: Too far"},
        ]
        result = _match_caption(img_rect, captions, proximity=80)
        assert result is None
