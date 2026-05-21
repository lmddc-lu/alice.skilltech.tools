"""Add token and api_enabled to chatbot

Revision ID: c3a1f8b92d47
Revises: 8af37a56196d
Create Date: 2026-02-27 00:00:00.000000
"""

import uuid

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

# revision identifiers, used by Alembic.
revision = "c3a1f8b92d47"
down_revision = "8af37a56196d"
branch_labels = None
depends_on = None


def upgrade():
    # 7ef1ca659243 may not have run, so add token only if missing
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'chatbot' AND column_name = 'token'"
        )
    )
    if not result.fetchone():
        op.add_column(
            "chatbot",
            sa.Column("token", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        )
        rows = conn.execute(sa.text("SELECT id FROM chatbot WHERE token IS NULL"))
        for row in rows:
            token = str(uuid.uuid4()).replace("-", "")
            conn.execute(
                sa.text("UPDATE chatbot SET token = :token WHERE id = :id"),
                {"token": token, "id": row.id},
            )
        op.alter_column("chatbot", "token", nullable=False)

    op.add_column(
        "chatbot",
        sa.Column("api_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade():
    op.drop_column("chatbot", "api_enabled")
    op.drop_column("chatbot", "token")
