import sys
from pathlib import Path

from sqlalchemy import inspect, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models.db import engine


def main() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    print("tables:", ", ".join(sorted(tables)))

    if "alembic_version" in tables:
        with engine.connect() as conn:
            versions = conn.execute(text("select version_num from alembic_version")).scalars().all()
        print("alembic_version:", versions)
    else:
        print("alembic_version: <missing>")

    for table_name in ["papers", "paper_files", "paper_chunks"]:
        if table_name not in tables:
            print(f"{table_name}: <missing>")
            continue
        columns = [column["name"] for column in inspector.get_columns(table_name)]
        print(f"{table_name} columns:", ", ".join(columns))


if __name__ == "__main__":
    main()
