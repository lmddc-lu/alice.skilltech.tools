"""Add chatbot avatar storage path

Revision ID: e1a9b7d4c203
Revises: d5f1a9e72c8b
Create Date: 2026-04-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'e1a9b7d4c203'
down_revision = 'd5f1a9e72c8b'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'chatbot',
        sa.Column(
            'avatar_storage_path',
            sqlmodel.sql.sqltypes.AutoString(length=1024),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column('chatbot', 'avatar_storage_path')
