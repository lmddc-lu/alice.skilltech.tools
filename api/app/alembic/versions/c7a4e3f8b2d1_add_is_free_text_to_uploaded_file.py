"""Add is_free_text to uploadedfile

Revision ID: c7a4e3f8b2d1
Revises: b8c4f2d9a7e1
Create Date: 2026-04-13 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7a4e3f8b2d1'
down_revision = 'b8c4f2d9a7e1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'uploadedfile',
        sa.Column(
            'is_free_text',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )


def downgrade():
    op.drop_column('uploadedfile', 'is_free_text')
