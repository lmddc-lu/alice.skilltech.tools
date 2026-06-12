"""Add pii_filter_enabled to chatbot

Revision ID: d2f4a6b8c013
Revises: a8e3f2c91b67
Create Date: 2026-06-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd2f4a6b8c013'
down_revision = 'a8e3f2c91b67'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chatbot', sa.Column('pii_filter_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade():
    op.drop_column('chatbot', 'pii_filter_enabled')
