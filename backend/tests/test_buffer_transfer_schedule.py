from decimal import Decimal
from backend import models


def test_buffer_transfer_rule_persists_with_expected_defaults(db_session):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db_session.add(user)
    db_session.flush()
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings, current_balance=Decimal("0"))
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("0"))
    db_session.add_all([savings, checking])
    db_session.flush()

    rule = models.BufferTransferRule(
        user_id=user.id,
        from_account_id=savings.id,
        to_account_id=checking.id,
        action_threshold=Decimal("100.00"),
        target_floor=Decimal("200.00"),
        increment=Decimal("1000.00"),
        check_day=1,
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    assert rule.id is not None
    assert rule.is_active is True
    assert rule.from_account.name == "Savings"
    assert rule.to_account.name == "Main Checking"
    assert savings.outgoing_buffer_rules == [rule]
    assert checking.incoming_buffer_rules == [rule]
