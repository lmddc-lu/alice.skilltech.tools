"""Add force_ocr to chatbot

Revision ID: c5f8g2b3d491
Revises: b4e7f1a2c390
Create Date: 2026-04-07 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c5f8g2b3d491'
down_revision = 'd4f8e2a1b3c5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chatbot', sa.Column('force_ocr', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade():
    op.drop_column('chatbot', 'force_ocr')
