import json
from decimal import Decimal
from backend import models


def test_verification_flag_round_trips_observed_json(db_session):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db_session.add(user)
    db_session.flush()

    flag = models.VerificationFlag(
        user_id=user.id,
        feature=models.VerificationFeature.household_snapshot,
        reference_type="account",
        reference_id=3,
        observed_json=json.dumps({"left_to_spend": "945.85", "flagged_field": "left_to_spend"}),
        expected_value=Decimal("945.85"),
        note="Spreadsheet says this",
    )
    db_session.add(flag)
    db_session.commit()
    db_session.refresh(flag)

    assert flag.status == models.VerificationFlagStatus.open
    assert flag.resolved_at is None
    assert json.loads(flag.observed_json) == {"left_to_spend": "945.85", "flagged_field": "left_to_spend"}
