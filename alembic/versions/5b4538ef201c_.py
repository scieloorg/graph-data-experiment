from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '5b4538ef201c'
down_revision = 'a4eae1d87ff5'
branch_labels = None
depends_on = None


def upgrade():
    # ALTER TABLE document_event DROP CONSTRAINT document_event_pkey
    op.execute("""
DO $$DECLARE r record;
BEGIN
  FOR r IN
    SELECT *
    FROM pg_constraint
    JOIN pg_class ON conrelid = pg_class.oid
    WHERE pg_class.relname = 'document_event'
    LOOP
      EXECUTE 'ALTER TABLE ' || quote_ident(r.relname) || ' DROP CONSTRAINT '|| quote_ident(r.conname) || ';';
    END LOOP;
END$$
""")
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('document_event', sa.Column('comment', sa.String(), nullable=True))
    op.add_column('document_event', sa.Column('reason', sa.String(), nullable=False))
    op.alter_column('document_event', 'hist',
               existing_type=postgresql.UUID(),
               nullable=True,
               existing_server_default=sa.text('gen_random_uuid()'))
    op.alter_column('document_event', 'parent',
               existing_type=postgresql.UUID(),
               nullable=True,
               existing_server_default=sa.text('gen_random_uuid()'))
    op.create_unique_constraint('parent_hist_unique', 'document_event', ['parent', 'hist'])
    op.drop_column('document_event', 'title')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('document_event', sa.Column('title', sa.VARCHAR(), autoincrement=False, nullable=False))
    op.drop_constraint('parent_hist_unique', 'document_event', type_='unique')
    op.alter_column('document_event', 'parent',
               existing_type=postgresql.UUID(),
               nullable=False,
               existing_server_default=sa.text('gen_random_uuid()'))
    op.alter_column('document_event', 'hist',
               existing_type=postgresql.UUID(),
               nullable=False,
               existing_server_default=sa.text('gen_random_uuid()'))
    op.drop_column('document_event', 'reason')
    op.drop_column('document_event', 'comment')
    # ### end Alembic commands ###
    op.create_primary_key("document_event_pkey", "document_event",
                          ["parent", "hist"])
