from sqlalchemy import Column, MetaData, Table, text, DateTime, String
from sqlalchemy.dialects.postgresql.base import UUID


SQL_UTC = text("timezone('UTC'::text, CURRENT_TIMESTAMP)")
SQL_UUID = text("gen_random_uuid()") # Require pgcrypto

metadata = MetaData()


t_user_info = Table(
    "user_info", metadata,
    Column("uid", UUID, primary_key=True, server_default=SQL_UUID),
    Column("name", String, nullable=False),
    Column("tstamp", DateTime, nullable=False, server_default=SQL_UTC),
)

t_document_hist = Table(
    "document_hist", metadata,
    Column("hid", UUID, primary_key=True, server_default=SQL_UUID),
    Column("pid", String, nullable=False),
    Column("title", String, nullable=False),
    Column("tstamp", DateTime, nullable=False, server_default=SQL_UTC),
)

t_document_event = Table(
    "document_event", metadata,
    Column("parent", UUID, primary_key=True, server_default=SQL_UUID),
    Column("hist", UUID, primary_key=True, server_default=SQL_UUID),
    Column("uid", UUID, nullable=False),
    Column("title", String, nullable=False),
    Column("tstamp", DateTime, nullable=False, server_default=SQL_UTC),
)
