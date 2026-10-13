"""Executes a Flyway-style SQL file from ``migrations/sql`` inside an Alembic revision."""

from pathlib import Path

from alembic import op

SQL_DIR = Path(__file__).parent / "sql"


def run_sql_file(name: str) -> None:
    op.execute((SQL_DIR / name).read_text())


def forward_only(revision: str) -> None:
    raise NotImplementedError(f"Migration {revision} is forward-only (mirrors the original Flyway history)")
