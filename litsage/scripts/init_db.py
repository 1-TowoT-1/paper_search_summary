import sys
from pathlib import Path

from sqlalchemy import inspect

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.models.db import Base, engine


def main() -> None:
    print(f"Database URL: {engine.url.render_as_string(hide_password=False)}")
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    tables = sorted(inspector.get_table_names())
    print("Tables in database:")
    for table in tables:
        print(f"- {table}")

    expected = sorted(Base.metadata.tables.keys())
    missing = [table for table in expected if table not in tables]
    if missing:
        raise SystemExit(f"Missing expected tables: {', '.join(missing)}")

    print("Database initialization completed.")


if __name__ == "__main__":
    main()
    