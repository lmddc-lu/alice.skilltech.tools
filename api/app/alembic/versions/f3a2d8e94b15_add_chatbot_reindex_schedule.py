"""Add chatbot reindex schedule fields

Revision ID: f3a2d8e94b15
Revises: e1a9b7d4c203
Create Date: 2026-04-27 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'f3a2d8e94b15'
down_revision = 'e1a9b7d4c203'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'chatbot',
        sa.Column(
            'reindex_schedule_enabled',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        'chatbot',
        sa.Column(
            'reindex_schedule_frequency',
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
        ),
    )
    op.add_column(
        'chatbot',
        sa.Column('reindex_schedule_day_of_week', sa.Integer(), nullable=True),
    )
    op.add_column(
        'chatbot',
        sa.Column('reindex_schedule_day_of_month', sa.Integer(), nullable=True),
    )
    op.add_column(
        'chatbot',
        sa.Column('reindex_schedule_hour', sa.Integer(), nullable=True),
    )
    op.add_column(
        'chatbot',
        sa.Column(
            'reindex_schedule_minute',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
    )


def downgrade():
    op.drop_column('chatbot', 'reindex_schedule_minute')
    op.drop_column('chatbot', 'reindex_schedule_hour')
    op.drop_column('chatbot', 'reindex_schedule_day_of_month')
    op.drop_column('chatbot', 'reindex_schedule_day_of_week')
    op.drop_column('chatbot', 'reindex_schedule_frequency')
    op.drop_column('chatbot', 'reindex_schedule_enabled')
