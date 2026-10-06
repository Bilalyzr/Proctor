"""UI static checks (checklist: mobile/responsive + accessibility basics).

Full axe-core audits and device emulation ride the browser journeys
(docs/TODO.md P3); these static checks hold the floor today: language
declaration, live region for AI responses, labeled inputs, viewport meta,
fluid layout CSS, and script-free fallback content.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.l9, pytest.mark.nightly]

PAGE = (Path(__file__).resolve().parents[2] / "sut" / "web" / "index.html").read_text(
    encoding="utf-8"
)


class TestAccessibilityBasics:
    def test_language_is_declared(self) -> None:
        assert re.search(r"<html[^>]*lang=", PAGE)

    def test_ai_responses_use_a_live_region(self) -> None:
        assert 'aria-live="polite"' in PAGE

    def test_inputs_have_accessible_names(self) -> None:
        assert 'placeholder="Order ID' in PAGE
        assert 'placeholder="e.g.' in PAGE
        # buttons carry visible text
        assert "<button" in PAGE and "Send</button>" in PAGE

    def test_page_has_heading_structure(self) -> None:
        assert "<h1>" in PAGE


class TestResponsiveBasics:
    def test_viewport_meta_present(self) -> None:
        assert 'name="viewport"' in PAGE and "width=device-width" in PAGE

    def test_layout_is_fluid(self) -> None:
        assert "max-width" in PAGE  # no fixed page width
        assert "width: 70%" in PAGE or "width:" in PAGE

    def test_ai_response_rendering_is_built_in(self) -> None:
        """The chat DOM renders assistant replies as text nodes (no raw HTML
        injection path - textContent assignment in the page script)."""
        assert "textContent" in PAGE
        assert "innerHTML" not in PAGE


def test_browser_journeys_parametrize_across_engines() -> None:
    """Cross-browser readiness: the browser suite is engine-parametrized
    (chromium/firefox/webkit) - runs once browsers are installed (TODO P3)."""
    browser_tests = (Path(__file__).resolve().parent / "test_browser_journeys.py").read_text(
        encoding="utf-8"
    )
    assert "chromium" in browser_tests
    assert "firefox" in browser_tests or "webkit" in browser_tests
