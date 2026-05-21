"""JobFile error_code column

Revision ID: d5f1a9e72c8b
Revises: c7a4e3f8b2d1
Create Date: 2026-04-13 15:00:00.000000

"""
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd5f1a9e72c8b'
down_revision = 'c7a4e3f8b2d1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'jobfile',
        sa.Column('error_code', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )


def downgrade():
    op.drop_column('jobfile', 'error_code')
