from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# Identifiers used by Alembic with generated codes (script.py.mako)
revision = "a4eae1d87ff5"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute('CREATE EXTENSION "pgcrypto"')
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('document_event',
    sa.Column('parent', postgresql.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('hist', postgresql.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('uid', postgresql.UUID(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('tstamp', sa.DateTime(), server_default=sa.text("timezone('UTC'::text, CURRENT_TIMESTAMP)"), nullable=False),
    sa.PrimaryKeyConstraint('parent', 'hist')
    )
    op.create_table('document_hist',
    sa.Column('hid', postgresql.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('pid', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('tstamp', sa.DateTime(), server_default=sa.text("timezone('UTC'::text, CURRENT_TIMESTAMP)"), nullable=False),
    sa.PrimaryKeyConstraint('hid')
    )
    op.create_table('user_info',
    sa.Column('uid', postgresql.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('tstamp', sa.DateTime(), server_default=sa.text("timezone('UTC'::text, CURRENT_TIMESTAMP)"), nullable=False),
    sa.PrimaryKeyConstraint('uid')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('user_info')
    op.drop_table('document_hist')
    op.drop_table('document_event')
    # ### end Alembic commands ###
    op.get_bind().execute('DROP EXTENSION "pgcrypto"')
