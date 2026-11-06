"""Guards for scripts/calc_before_after.py: the gate must never report
'no difference' for a figure it could not compute, and must refuse the live DB."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("calc_before_after", ROOT / "scripts" / "calc_before_after.py")
cba = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cba)


def test_delta_numeric():
    assert cba._delta("10.00", "10.00") == "0.00"
    assert cba._delta("12.50", "10.00") == "2.50"


def test_delta_na_on_either_side_is_not_zero():
    assert cba._delta("n/a (KeyError)", "n/a (KeyError)") == "n/a"
    assert cba._delta("5.00", "n/a (AttributeError)") == "n/a"
    assert cba._delta("n/a (X)", "5.00") == "n/a"


def test_delta_non_numeric_equal_vs_different():
    assert cba._delta("none", "none") == "0.00"
    assert cba._delta("none", "5.00") == "differs"


def test_refuses_live_database(capsys):
    assert cba.main(["--db", str(ROOT / "data" / "budget.db"), "--user", "1", "--ref", "HEAD"]) == 2
    assert "Refusing" in capsys.readouterr().err


def test_missing_copy_rejected(tmp_path, capsys):
    assert cba.main(["--db", str(tmp_path / "nope.db"), "--user", "1", "--ref", "HEAD"]) == 2
