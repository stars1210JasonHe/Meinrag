"""Offline tests for poppler_extractor module."""

import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.poppler_extractor import (
    DEFAULT_CONFIG,
    ExtractedFigure,
    _convert_bbox_to_pdf_points,
    _extract_captions,
    _find_poppler_bin,
    _get_caption_regexes,
    _get_nearby_text,
    _group_into_lines,
    _match_caption,
    _run_poppler,
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


class TestRunPoppler:
    @pytest.mark.skipif(not has_poppler(), reason="poppler not available")
    def test_run_poppler_uses_full_exe_path(self):
        """Verify that when bundled poppler exists, the exe resolves to a full path."""
        poppler_bin = _find_poppler_bin()
        if poppler_bin is None:
            pytest.skip("no bundled poppler bin directory")
        exe_name = "pdftohtml" + (".exe" if os.name == "nt" else "")
        full_exe = poppler_bin / exe_name
        assert full_exe.exists(), f"Expected bundled exe at {full_exe}"


class TestMultiLineCaptions:
    def test_continuation_lines_appended(self):
        """Lines immediately following a caption line should be joined."""
        segments = [
            {"top": 300.0, "left": 82.0, "width": 60.0, "height": 12.0, "text": "Figure 1."},
            {"top": 300.0, "left": 150.0, "width": 200.0, "height": 12.0, "text": "Architecture of the T3RL system"},
            {"top": 314.0, "left": 82.0, "width": 300.0, "height": 12.0, "text": "showing the verifier and tool integration pipeline."},
            {"top": 340.0, "left": 82.0, "width": 200.0, "height": 12.0, "text": "In this section, we describe our method."},
        ]
        lines = _group_into_lines(segments, line_tol=2.0)
        captions = _extract_captions(lines, chunk_gap=40.0)
        assert len(captions) == 1
        assert "showing the verifier" in captions[0]["text"]

    def test_stops_at_non_continuation(self):
        """Caption continuation stops when a new paragraph/section begins."""
        segments = [
            {"top": 300.0, "left": 82.0, "width": 60.0, "height": 12.0, "text": "Figure 1."},
            {"top": 300.0, "left": 150.0, "width": 200.0, "height": 12.0, "text": "The pipeline overview."},
            # Gap of 30px (>1 line height) then a new section
            {"top": 350.0, "left": 82.0, "width": 200.0, "height": 12.0, "text": "3. Method"},
            {"top": 364.0, "left": 82.0, "width": 300.0, "height": 12.0, "text": "We propose a new approach."},
        ]
        lines = _group_into_lines(segments, line_tol=2.0)
        captions = _extract_captions(lines, chunk_gap=40.0)
        assert len(captions) == 1
        assert "3. Method" not in captions[0]["text"]
        assert "new approach" not in captions[0]["text"]

    def test_max_continuation_lines(self):
        """Caption should not absorb more than 3 continuation lines."""
        segments = [
            {"top": 300.0, "left": 82.0, "width": 200.0, "height": 12.0, "text": "Figure 1. Title"},
        ]
        # Add 6 continuation lines
        for i in range(6):
            segments.append({
                "top": 314.0 + i * 14.0, "left": 82.0,
                "width": 300.0, "height": 12.0,
                "text": f"Continuation line {i+1}.",
            })
        lines = _group_into_lines(segments, line_tol=2.0)
        captions = _extract_captions(lines, chunk_gap=40.0)
        assert len(captions) == 1
        assert "Continuation line 3" in captions[0]["text"]
        assert "Continuation line 4" not in captions[0]["text"]


class TestNearbyTextFallback:
    def test_collects_nearby_text(self):
        """_get_nearby_text should return text segments close to an image."""
        lines = [
            {"top": 100.0, "bottom": 112.0, "segments": [
                {"top": 100.0, "left": 82.0, "width": 300.0, "height": 12.0,
                 "text": "As shown in the diagram below, the pipeline"},
            ]},
            {"top": 250.0, "bottom": 262.0, "segments": [
                {"top": 250.0, "left": 82.0, "width": 300.0, "height": 12.0,
                 "text": "The results demonstrate clear improvement."},
            ]},
        ]
        img_rect = (82.0, 120.0, 400.0, 240.0)  # image between the two lines
        text = _get_nearby_text(lines, img_rect, max_chars=200)
        assert "diagram below" in text
        assert "results demonstrate" in text

    def test_returns_empty_when_no_nearby_text(self):
        lines = [
            {"top": 500.0, "bottom": 512.0, "segments": [
                {"top": 500.0, "left": 82.0, "width": 100.0, "height": 12.0,
                 "text": "Far away text."},
            ]},
        ]
        img_rect = (82.0, 100.0, 400.0, 200.0)
        text = _get_nearby_text(lines, img_rect, max_chars=200)
        assert text == ""


class TestBboxCoordinateConversion:
    def test_poppler_bbox_converts_to_pdf_points(self):
        """Bbox should be scaled from poppler pixels to PDF points."""
        # Poppler XML page: 1190x1684 pixels, PDF page: 595x842 points
        # Scale: 0.5x, 0.5y
        result = _convert_bbox_to_pdf_points(
            [100.0, 200.0, 500.0, 600.0],
            1190.0, 1684.0, 595.0, 842.0
        )
        assert result == [50.0, 100.0, 250.0, 300.0]

    def test_no_conversion_when_dimensions_match(self):
        """If dimensions match, bbox stays the same."""
        bbox = [100.0, 200.0, 400.0, 500.0]
        result = _convert_bbox_to_pdf_points(bbox, 595.0, 842.0, 595.0, 842.0)
        assert result == bbox

    def test_zero_xml_dimensions_returns_original(self):
        """If XML dimensions are zero, return original bbox."""
        bbox = [100.0, 200.0, 400.0, 500.0]
        result = _convert_bbox_to_pdf_points(bbox, 0.0, 0.0, 595.0, 842.0)
        assert result == bbox


class TestExtractFiguresIntegration:
    _TEST_PDF = Path(__file__).parent.parent / "test cases1" / "ai_tool_verification_ttrl.pdf"

    @pytest.mark.skipif(not has_poppler(), reason="poppler not available")
    def test_extract_returns_figures(self, tmp_path):
        if not self._TEST_PDF.exists():
            pytest.skip(f"Test PDF not found: {self._TEST_PDF}")
        figures = extract_figures(self._TEST_PDF, tmp_path / "images", "test_doc")
        assert len(figures) > 0, "Expected at least one figure from test PDF"
        for fig in figures:
            assert isinstance(fig, ExtractedFigure)
            assert isinstance(fig.page_num, int)
            assert fig.page_num >= 0
            assert isinstance(fig.image_path, str)
            assert fig.image_path.startswith("test_doc/")
            assert isinstance(fig.caption, str)
            assert len(fig.caption) > 0
            assert isinstance(fig.bbox, list)
            assert len(fig.bbox) == 4
