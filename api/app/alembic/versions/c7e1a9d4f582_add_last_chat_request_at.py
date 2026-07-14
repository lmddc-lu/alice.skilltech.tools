"""Add last_chat_request_at to chatbot

Records the last time a chat request hit a bot so "recently used" can be
read directly (e.g. to skip actively-used bots during a progressive reindex).
Nullable: NULL means no chat since the column was added.

Revision ID: c7e1a9d4f582
Revises: f4d9c1e6a2b8
Create Date: 2026-07-02 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7e1a9d4f582'
down_revision = 'f4d9c1e6a2b8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'chatbot',
        sa.Column('last_chat_request_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column('chatbot', 'last_chat_request_at')
