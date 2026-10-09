"""The user's primary checking account: the one the Forecast, Safety Margin,
daily email and Wish List all walk. One definition so they never disagree."""
from sqlalchemy.orm import Session
from backend import models


def primary_checking(db: Session, user_id: int) -> models.Account | None:
    """Lowest-id active checking account, or None."""
    return db.query(models.Account).filter(
        models.Account.user_id == user_id,
        models.Account.type == models.AccountType.checking,
        models.Account.is_active == True,
    ).order_by(models.Account.id).first()
