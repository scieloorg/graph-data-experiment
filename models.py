from sqlalchemy import Column, Index, MetaData, Table, text, ForeignKey, \
                       Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID


SQL_UTC = text("timezone('UTC'::text, CURRENT_TIMESTAMP)")
SQL_UUID = text("gen_random_uuid()") # Require pgcrypto

metadata = MetaData()


t_user_info = Table(
    "user_info", metadata,
    Column("uid", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("ldap_cn", String, nullable=False),
    Column("tstamp", DateTime, nullable=False, server_default=SQL_UTC),
)

t_document_hist = Table(
    "document_hist", metadata,
    Column("hid", UUID, primary_key=True, server_default=SQL_UUID),
    Column("pid", String, nullable=False),
    Column("title", String, nullable=False),
    Column("metadata", JSONB, nullable=False, server_default=text("'{}'")),
    Column("published", Boolean, server_default=text("false")),
    Column("deleted", Boolean, server_default=text("false")),
    Column("tstamp", DateTime),
)

t_document_event = Table(
    "document_event", metadata,
    Column("parent", UUID,
        ForeignKey("document_hist.hid", onupdate="CASCADE"),
        nullable=True,
    ),
    Column("hist", UUID,
        ForeignKey("document_hist.hid",
            onupdate="CASCADE",
            ondelete="CASCADE", # When removing an unpublished document
        ),
        nullable=False,
    ),
    Column("uid", String,
        ForeignKey("user_info.uid", onupdate="CASCADE"),
        nullable=False,
    ),
    Column("reason", String, nullable=False),
    Column("comment", String),
    Column("tstamp", DateTime, nullable=False, server_default=SQL_UTC),
)

parent_hist_index = Index("parent_hist_index",
    t_document_event.c.parent, t_document_event.c.hist,
    unique=True,
)

null_hist_index = Index("null_hist_index",
    t_document_event.c.hist,
    unique=True,
    postgresql_where=t_document_event.c.parent == None,
)
