from alembic import op
import sqlalchemy as sa


# Identifiers used by Alembic with generated codes (script.py.mako)
revision = "a336641643e8"
down_revision = "bdbe3a08fef7"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("snapshot_pkey", "snapshot")
    op.add_column("snapshot", sa.Column("digest", sa.LargeBinary(length=40)))
    op.execute("""
CREATE FUNCTION snapshot_hash() RETURNS trigger
LANGUAGE plpgsql
AS $$BEGIN
  NEW.digest = digest(NEW.data::text, 'SHA1');
  RETURN NEW;
END$$
    """)
    op.execute("""
CREATE TRIGGER trigger_snapshot_hash
BEFORE INSERT OR UPDATE ON snapshot
FOR EACH ROW EXECUTE PROCEDURE snapshot_hash()
    """)
    op.execute("UPDATE snapshot SET digest = NULL")  # Fill all digests
    op.alter_column("snapshot", "digest", nullable=False)
    op.create_primary_key("snapshot_pkey", "snapshot",
                          ["digest", "source", "tstamp"])


def downgrade():
    op.drop_constraint("snapshot_pkey", "snapshot")
    op.execute("DROP TRIGGER trigger_snapshot_hash ON snapshot")
    op.execute("DROP FUNCTION snapshot_hash")
    op.drop_column("snapshot", "digest")
    op.create_primary_key("snapshot_pkey", "snapshot",
                          ["data", "source", "tstamp"])
