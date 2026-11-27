import pytest
import re
from pathlib import Path

def test_index_html_has_help_guide_buttons_and_overlay():
    html_path = Path("frontend/index.html")
    assert html_path.exists(), "frontend/index.html must exist"
    content = html_path.read_text(encoding="utf-8")

    # Navbar help button
    assert 'id="btn-navbar-help"' in content, "Navbar must contain Help Guide button"
    
    # Page help buttons across tabs
    assert 'data-tab-help="tab-dashboard"' in content, "Dashboard must contain Help Guide button"
    assert 'data-tab-help="tab-timetable"' in content, "Timetable must contain Help Guide button"
    assert 'data-tab-help="tab-faculty"' in content, "Faculty must contain Help Guide button"
    assert 'data-tab-help="tab-subjects"' in content, "Subjects must contain Help Guide button"
    assert 'data-tab-help="tab-divisions"' in content, "Divisions must contain Help Guide button"
    assert 'data-tab-help="tab-settings"' in content, "Settings must contain Help Guide button"

    # Help tour overlay elements
    assert 'id="help-tour-overlay"' in content
    assert 'id="help-tour-backdrop"' in content
    assert 'id="help-tour-spotlight"' in content
    assert 'id="help-tour-popover"' in content
    assert 'id="help-tour-arrow"' in content
    assert 'id="help-tour-step-badge"' in content
    assert 'id="help-tour-tab-badge"' in content
    assert 'id="help-tour-close-btn"' in content
    assert 'id="help-tour-title"' in content
    assert 'id="help-tour-desc"' in content
    assert 'id="help-tour-prev-btn"' in content
    assert 'id="help-tour-next-btn"' in content
    assert 'id="help-tour-dots"' in content


def test_style_css_contains_help_tour_styles():
    css_path = Path("frontend/style.css")
    assert css_path.exists(), "frontend/style.css must exist"
    content = css_path.read_text(encoding="utf-8")

    assert ".help-tour-overlay" in content
    assert ".help-tour-backdrop" in content
    assert "backdrop-filter: blur(" in content
    assert ".help-tour-spotlight" in content
    assert ".help-tour-popover" in content
    assert ".help-tour-arrow" in content
    assert "body.help-tour-active" in content
    assert "[data-tour-target-active=" in content


def test_app_js_help_tour_engine():
    js_path = Path("frontend/app.js")
    assert js_path.exists(), "frontend/app.js must exist"
    content = js_path.read_text(encoding="utf-8")

    # Functions
    assert "setupInteractiveHelpTour" in content
    assert "startHelpTour" in content
    assert "renderTourStep" in content
    assert "positionSpotlightAndPopover" in content
    assert "nextTourStep" in content
    assert "prevTourStep" in content
    assert "exitHelpTour" in content
    assert "markTourTargetElements" in content

    # Tours defined for all tabs
    for tab in ["tab-timetable", "tab-dashboard", "tab-faculty", "tab-subjects", "tab-divisions", "tab-settings"]:
        assert f'"{tab}":' in content, f"Tour config for {tab} must exist"

    # Click-to-inspect feature
    assert "data-tour-target-active" in content
    assert "data-tour-step-idx" in content
