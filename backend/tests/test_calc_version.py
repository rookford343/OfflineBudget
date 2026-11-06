from pathlib import Path

from backend.services.calc_version import CALC_VERSION


def test_calc_version_is_positive_int():
    assert isinstance(CALC_VERSION, int) and CALC_VERSION >= 1


def test_architecture_changelog_has_current_version():
    doc = (Path(__file__).resolve().parents[2] / "docs" / "architecture.md").read_text()
    assert f"- v{CALC_VERSION}:" in doc
