from pathlib import Path

from backend.services.calc_version import CALC_VERSION


def test_calc_version_is_positive_int():
    assert isinstance(CALC_VERSION, int) and CALC_VERSION >= 1


def test_architecture_changelog_has_current_version():
    doc = (Path(__file__).resolve().parents[2] / "docs" / "architecture.md").read_text()
    assert f"- v{CALC_VERSION}:" in doc


def test_changelog_dict_matches_doc():
    import re

    from backend.services.calc_version import CALC_CHANGELOG

    doc = (Path(__file__).resolve().parents[2] / "docs" / "architecture.md").read_text()
    in_doc = {int(n): text for n, text in re.findall(r"^- v(\d+): (.+)$", doc, re.M)}
    assert in_doc
    assert CALC_CHANGELOG == in_doc
    assert max(CALC_CHANGELOG) == CALC_VERSION
