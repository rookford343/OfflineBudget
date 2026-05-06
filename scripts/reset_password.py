#!/usr/bin/env python3
"""
Reset a user's password directly in the database.

Use this when a user is locked out and no admin can log in to use the UI.

Run from the project root:
    source .venv/bin/activate
    python scripts/reset_password.py <username> <new_password>

Example:
    python scripts/reset_password.py admin newpassword123
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal, create_tables
from backend.auth import hash_password
from backend import models

if len(sys.argv) != 3:
    print("Usage: python scripts/reset_password.py <username> <new_password>")
    sys.exit(1)

username = sys.argv[1]
new_password = sys.argv[2]

if len(new_password) < 6:
    print("Error: password must be at least 6 characters")
    sys.exit(1)

create_tables()
db = SessionLocal()

try:
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        print(f"Error: no user with username '{username}'")
        print()
        print("Existing users:")
        for u in db.query(models.User).order_by(models.User.username).all():
            status = "active" if u.is_active else "inactive"
            print(f"  {u.username}  ({u.role.value}, {status})")
        sys.exit(1)

    user.hashed_password = hash_password(new_password)
    if not user.is_active:
        user.is_active = True
        print(f"Note: account was inactive — re-activated")
    db.commit()
    print(f"Password reset for '{username}'")
finally:
    db.close()
