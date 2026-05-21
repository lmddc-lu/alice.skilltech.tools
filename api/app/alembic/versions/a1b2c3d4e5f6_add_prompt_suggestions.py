"""Add prompt_suggestions to chatbot

Revision ID: a1b2c3d4e5f6
Revises: c3a1f8b92d47
Create Date: 2026-03-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "c3a1f8b92d47"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "chatbot",
        sa.Column("prompt_suggestions", sa.String(), nullable=True),
    )


def downgrade():
    op.drop_column("chatbot", "prompt_suggestions")
