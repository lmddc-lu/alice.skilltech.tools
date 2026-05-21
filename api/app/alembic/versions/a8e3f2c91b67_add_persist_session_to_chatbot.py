"""Add persist_session to chatbot

Revision ID: a8e3f2c91b67
Revises: a5c8f1d3b942
Create Date: 2026-05-27 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a8e3f2c91b67'
down_revision = 'a5c8f1d3b942'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chatbot', sa.Column('persist_session', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade():
    op.drop_column('chatbot', 'persist_session')
