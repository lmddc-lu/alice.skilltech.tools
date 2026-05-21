"""JobFile error_detail column

Revision ID: b8c4f2d9a7e1
Revises: a7f3b1c29e04
Create Date: 2026-04-13 10:00:00.000000

"""
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b8c4f2d9a7e1'
down_revision = 'a7f3b1c29e04'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'jobfile',
        sa.Column('error_detail', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )


def downgrade():
    op.drop_column('jobfile', 'error_detail')
