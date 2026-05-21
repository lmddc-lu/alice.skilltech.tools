"""JobFile table and progress_updated_at

Revision ID: a7f3b1c29e04
Revises: c5f8g2b3d491
Create Date: 2026-04-10 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'a7f3b1c29e04'
down_revision = 'c5f8g2b3d491'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'job',
        sa.Column('progress_updated_at', sa.DateTime(), nullable=True),
    )
    # seed existing rows so mark_stalled_jobs has a baseline
    op.execute("UPDATE job SET progress_updated_at = started_at WHERE started_at IS NOT NULL")

    op.create_table(
        'jobfile',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('job_id', sa.Uuid(), nullable=False),
        sa.Column('external_file_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('filename', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('state', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('error_message', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['job.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('job_id', 'external_file_id', name='uq_jobfile_job_extid'),
    )
    op.create_index(op.f('ix_jobfile_job_id'), 'jobfile', ['job_id'], unique=False)
    op.create_index(op.f('ix_jobfile_external_file_id'), 'jobfile', ['external_file_id'], unique=False)
    op.create_index(op.f('ix_jobfile_state'), 'jobfile', ['state'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_jobfile_state'), table_name='jobfile')
    op.drop_index(op.f('ix_jobfile_external_file_id'), table_name='jobfile')
    op.drop_index(op.f('ix_jobfile_job_id'), table_name='jobfile')
    op.drop_table('jobfile')
    op.drop_column('job', 'progress_updated_at')
