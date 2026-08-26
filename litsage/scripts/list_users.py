import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models.db import SessionLocal, User, engine


def main() -> None:
    print(f"Database URL: {engine.url.render_as_string(hide_password=True)}")
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.created_at.desc()).all()
        print(f"User count: {len(users)}")
        for user in users:
            print(f"{user.id} | {user.username} | {user.email} | {user.created_at}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
