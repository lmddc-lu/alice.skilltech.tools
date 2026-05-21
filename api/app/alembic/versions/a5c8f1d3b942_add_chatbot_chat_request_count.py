"""Add chat_request_count to chatbot

Revision ID: a5c8f1d3b942
Revises: f3a2d8e94b15
Create Date: 2026-05-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a5c8f1d3b942"
down_revision = "f3a2d8e94b15"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "chatbot",
        sa.Column(
            "chat_request_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade():
    op.drop_column("chatbot", "chat_request_count")
