from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'b29522cb896e'
down_revision = '5b4538ef201c'
branch_labels = None
depends_on = None


SQL_UTC_STRING = "timezone('UTC'::text, CURRENT_TIMESTAMP)"
SQL_UTC = sa.text(SQL_UTC_STRING)
SQL_UUID = sa.text("gen_random_uuid()") # Require pgcrypto


def upgrade():
    op.execute('CREATE EXTENSION "fuzzystrmatch"')
    op.execute("""
CREATE FUNCTION check_unpublished() RETURNS trigger
LANGUAGE plpgsql
AS $$BEGIN
  IF OLD.published THEN
    RAISE EXCEPTION 'already_published';
  END IF;
  RETURN NULL;
END$$
    """)
    op.execute("""
CREATE FUNCTION check_parent_published() RETURNS trigger
LANGUAGE plpgsql
AS $$BEGIN
  IF NOT (
    SELECT published
    FROM document_hist
    WHERE hid = NEW.parent
  ) THEN
    RAISE EXCEPTION 'unpublished_parent';
  END IF;
  RETURN NULL;
END$$
    """)
    op.execute("""
CREATE FUNCTION check_document_cycle() RETURNS trigger
LANGUAGE plpgsql
AS $$BEGIN
  IF NEW.hist IN (
    WITH RECURSIVE all_events(parent) AS (
        SELECT NEW.parent
      UNION
        SELECT e.parent
        FROM all_events ae, document_event e
        WHERE e.hist = ae.parent
      )
    SELECT *
    FROM all_events
  ) THEN
    RAISE EXCEPTION 'parent_cycle';
  END IF;
  RETURN NULL;
END$$
    """)
    op.execute("""
CREATE CONSTRAINT TRIGGER trigger_check_unpublished
AFTER UPDATE OR DELETE
ON document_hist
NOT DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW
EXECUTE PROCEDURE check_unpublished()
    """)
    op.execute("""
CREATE CONSTRAINT TRIGGER trigger_check_parent_published
AFTER INSERT
ON document_event
NOT DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW
EXECUTE PROCEDURE check_parent_published()
    """)
    op.execute("""
CREATE CONSTRAINT TRIGGER trigger_check_document_cycle
AFTER INSERT
ON document_event
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE PROCEDURE check_document_cycle()
    """)
    op.alter_column("user_info", "uid",
        existing_type=postgresql.UUID(),
        type_=sa.String(),
        existing_server_default=SQL_UUID,
        server_default=None,
    )
    op.alter_column("document_hist", "tstamp",
        existing_type=postgresql.TIMESTAMP(),
        nullable=True,
        existing_server_default=SQL_UTC,
        server_default=None,
    )
    op.alter_column("document_event", "hist",
        existing_type=postgresql.UUID(),
        nullable=False,
        existing_server_default=SQL_UUID,
        server_default=None,
    )
    op.alter_column("document_event", "uid",
        existing_type=postgresql.UUID(),
        type_=sa.String(),
    )
    op.create_foreign_key("parent_fk",
        "document_event", "document_hist",
        ["parent"], ["hid"],
        onupdate="CASCADE",
    )
    op.create_foreign_key("hist_fk",
        "document_event", "document_hist",
        ["hist"], ["hid"],
        onupdate="CASCADE",
        ondelete="CASCADE",
    )
    op.create_foreign_key("uid_fk",
        "document_event", "user_info",
        ["uid"], ["uid"],
        onupdate="CASCADE",
    )
    op.add_column("document_hist", sa.Column(
        "metadata", postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'{}'"),
        nullable=False,
    ))
    op.add_column("document_hist", sa.Column(
        "published", sa.Boolean(),
        server_default=sa.text("false"),
        nullable=True,
    ))
    op.add_column("document_hist", sa.Column(
        "deleted", sa.Boolean(),
        server_default=sa.text("false"),
        nullable=True,
    ))
    # Adding a NOT NULL column without a default
    # breaks if we already have some data,
    # so let split this into two parts
    op.add_column("user_info", sa.Column(
        "ldap_cn", sa.String(),
        nullable=True,
    ))
    op.execute("UPDATE user_info SET ldap_cn = name")
    op.alter_column("user_info", "ldap_cn",
        nullable=False,
    )
    op.create_index("null_hist_index", "document_event", ["hist"],
        unique=True,
        postgresql_where=sa.text("parent IS NULL")
    )
    op.create_index("parent_hist_index", "document_event", ["parent", "hist"],
        unique=True,
    )
    op.drop_constraint("parent_hist_unique", "document_event", type_="unique")


def downgrade():
    # Downgrade can't happen unless user IDs are UUID,
    # this UPDATE replaces the non-UUID IDs by UUID ones
    # and the ONCASCADE propagates it everywhere
    op.execute(r"""
UPDATE user_info
SET uid = gen_random_uuid()
WHERE uid !~ '\d{8}-\d{4}-\d{4}-\d{4}-\d{12}'
    """)
    op.create_unique_constraint(
        "parent_hist_unique", "document_event", ["parent", "hist"]
    )
    op.drop_index("parent_hist_index", table_name="document_event")
    op.drop_index("null_hist_index", table_name="document_event")
    op.drop_column("user_info", "ldap_cn")
    op.drop_column("document_hist", "deleted")
    op.drop_column("document_hist", "published")
    op.drop_column("document_hist", "metadata")
    op.drop_constraint("uid_fk", "document_event", type_="foreignkey")
    op.drop_constraint("hist_fk", "document_event", type_="foreignkey")
    op.drop_constraint("parent_fk", "document_event", type_="foreignkey")
    op.alter_column("document_event", "uid",
        type_=postgresql.UUID(),
        existing_type=sa.String(),
        postgresql_using="uid::uuid",
    )
    op.alter_column("document_event", "hist",
        existing_type=postgresql.UUID(),
        nullable=True,
        existing_server_default=None,
        server_default=SQL_UUID,
    )
    op.alter_column("document_hist", "tstamp",
        existing_type=postgresql.TIMESTAMP(),
        type_=postgresql.TIMESTAMP(),
        nullable=False,
        existing_server_default=None,
        server_default=SQL_UTC,
        postgresql_using=SQL_UTC_STRING,
    )
    op.alter_column("user_info", "uid",
        existing_type=sa.String(),
        type_=postgresql.UUID(),
        existing_server_default=None,
        server_default=SQL_UUID,
        postgresql_using="uid::uuid",
    )
    op.execute('DROP EXTENSION "fuzzystrmatch"')
    op.execute("DROP TRIGGER trigger_check_parent_published ON document_event")
    op.execute("DROP TRIGGER trigger_check_document_cycle ON document_event")
    op.execute("DROP TRIGGER trigger_check_unpublished ON document_hist")
    op.execute("DROP FUNCTION check_document_cycle")
    op.execute("DROP FUNCTION check_parent_published")
    op.execute("DROP FUNCTION check_unpublished")
