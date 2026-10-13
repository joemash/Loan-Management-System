"""loan product constraints (Flyway V11__loan_product_constraints.sql)"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sql_runner import forward_only, run_sql_file  # noqa: E402

revision = "v11"
down_revision = "v10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("V11__loan_product_constraints.sql")


def downgrade() -> None:
    forward_only(revision)
