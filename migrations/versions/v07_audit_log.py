"""audit log (Flyway V7__audit_log.sql)"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sql_runner import forward_only, run_sql_file  # noqa: E402

revision = "v07"
down_revision = "v06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("V7__audit_log.sql")


def downgrade() -> None:
    forward_only(revision)
