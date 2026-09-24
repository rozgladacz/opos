"""Add optional unit identification emblems."""

import sqlalchemy as sa
from alembic import op

revision = "20260908_0004"
down_revision = "20260817_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in ("unit_templates", "roster_units"):
        if "emblem" not in {c["name"] for c in sa.inspect(bind).get_columns(table)}:
            op.add_column(table, sa.Column("emblem", sa.String(24), nullable=True))


def downgrade() -> None:
    for table in ("unit_templates", "roster_units"):
        op.drop_column(table, "emblem")
