from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identifiers used by Alembic with generated codes (script.py.mako)
revision = "bdbe3a08fef7"
down_revision = "b701f7322b6f"
branch_labels = None
depends_on = None

SQL_UTC = sa.text("timezone('UTC'::text, CURRENT_TIMESTAMP)")


def upgrade():
    op.create_table("snapshot",
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("tstamp", sa.DateTime(), server_default=SQL_UTC,
                  nullable=False),
        sa.Column("uid", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["uid"], ["user_info.uid"],
                                onupdate="CASCADE"),
        sa.PrimaryKeyConstraint("data", "source", "tstamp")
    )


def downgrade():
    op.drop_table("snapshot")
