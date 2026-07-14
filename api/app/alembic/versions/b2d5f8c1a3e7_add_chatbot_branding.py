"""Add per-chatbot branding fields

Accent colour and an optional header logo for the chat interface. Editable
by instance admins only; NULL means the chatbot uses the built-in default
look.

Revision ID: b2d5f8c1a3e7
Revises: c7e1a9d4f582
Create Date: 2026-07-13 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2d5f8c1a3e7'
down_revision = 'c7e1a9d4f582'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'chatbot',
        sa.Column('accent_color', sa.String(length=7), nullable=True),
    )
    op.add_column(
        'chatbot',
        sa.Column('header_logo_storage_path', sa.String(length=1024), nullable=True),
    )


def downgrade():
    op.drop_column('chatbot', 'header_logo_storage_path')
    op.drop_column('chatbot', 'accent_color')
