"""loan version schedule penalties (Flyway V8__loan_version_schedule_penalties.sql)"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sql_runner import forward_only, run_sql_file  # noqa: E402

revision = "v08"
down_revision = "v07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("V8__loan_version_schedule_penalties.sql")


def downgrade() -> None:
    forward_only(revision)
