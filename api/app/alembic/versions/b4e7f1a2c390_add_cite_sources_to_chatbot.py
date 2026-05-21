"""Add cite_sources to chatbot

Revision ID: b4e7f1a2c390
Revises: a1b2c3d4e5f6
Create Date: 2026-04-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4e7f1a2c390'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chatbot', sa.Column('cite_sources', sa.Boolean(), nullable=False, server_default=sa.text('true')))


def downgrade():
    op.drop_column('chatbot', 'cite_sources')
