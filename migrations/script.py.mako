<%!
    import json
    import re

    def dump(obj):
        """Alternative "repr" with double quotes for strings/None."""
        return re.sub(r"^null$", "None", json.dumps(obj))
%>\
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}\


# Identifiers used by Alembic with generated codes (script.py.mako)
revision = ${dump(up_revision)}
down_revision = ${dump(down_revision)}
branch_labels = ${dump(branch_labels)}
depends_on = ${dump(depends_on)}


def upgrade():
    ${upgrades if upgrades else "pass"}


def downgrade():
    ${downgrades if downgrades else "pass"}
