import sys
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.security import hash_password
from app.models.db import SessionLocal, User


def main() -> None:
    username = "czh_debug"
    email = "czh_debug@example.com"
    password = "hbxt9688"

    db = SessionLocal()
    try:
        existing = db.query(User).filter((User.username == username) | (User.email == email)).first()
        if existing:
            print(f"User already exists: {existing.id}")
            return

        user = User(id=uuid4(), username=username, email=email, password_hash=hash_password(password))
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"Registered user: {user.id} {user.username} {user.email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
