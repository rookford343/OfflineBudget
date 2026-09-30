from decimal import Decimal
from backend import schemas
from backend.services.explain import ExplainBuilder, replay, children_consistent


def test_replay_add_subtract():
    ex = (ExplainBuilder("Left")
          .start("Leftover", Decimal("100.00"))
          .subtract("Card spend", Decimal("30.50"))
          .add("Already charged", Decimal("5.25"))
          .build(Decimal("74.75")))
    assert replay(ex) == Decimal("74.75")
    assert ex.result == Decimal("74.75")
    assert [r.op for r in ex.rows] == ["start", "subtract", "add", "result"]
    assert ex.rows[-1].amount == Decimal("74.75")


def test_divide_uses_exact_divisor_and_quantizes():
    weeks = Decimal(24) / Decimal(7)
    expected = (Decimal("1000.00") / weeks).quantize(Decimal("0.01"))
    ex = ExplainBuilder("Week").start("Month", Decimal("1000.00")).divide("Weeks left", weeks).build(expected)
    assert replay(ex) == expected
    assert ex.rows[1].amount == weeks  # exact, not rounded


def test_replay_detects_a_wrong_explanation():
    ex = ExplainBuilder("X").start("A", Decimal("10")).subtract("B", Decimal("3")).build(Decimal("8"))
    assert replay(ex) != ex.result


def test_children_must_sum_to_their_row():
    good = ExplainBuilder("X").start("Leftover", Decimal("70"), children=[
        schemas.ExplainChild(label="Income", amount=Decimal("100")),
        schemas.ExplainChild(label="Bills", amount=Decimal("-30")),
    ]).build(Decimal("70"))
    bad = ExplainBuilder("X").start("Leftover", Decimal("70"), children=[
        schemas.ExplainChild(label="Income", amount=Decimal("100")),
    ]).build(Decimal("70"))
    assert children_consistent(good)
    assert not children_consistent(bad)


def test_start_only_explanation():
    ex = ExplainBuilder("Low").start("Lowest balance", Decimal("512.34"), note="on Oct 22").build(Decimal("512.34"))
    assert replay(ex) == Decimal("512.34")
