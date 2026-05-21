"""initial tables

Revision ID: 0_initial_tables
Revises: 
Create Date: 2025-01-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0_initial_tables'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('user',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('is_superuser', sa.Boolean(), nullable=False),
    sa.Column('moodle_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    
    op.create_table('datasource',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('source_type', sa.Integer(), nullable=False),
    sa.Column('sync_status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('last_sync', sa.DateTime(), nullable=True),
    sa.Column('last_sync_error', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('knowledgebase',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('last_sync', sa.DateTime(), nullable=True),
    sa.Column('last_sync_error', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('knowledgebasedatasourcelink',
    sa.Column('knowledge_base_id', sa.Uuid(), nullable=False),
    sa.Column('datasource_id', sa.Uuid(), nullable=False),
    sa.Column('files', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.ForeignKeyConstraint(['datasource_id'], ['datasource.id'], ),
    sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledgebase.id'], ),
    sa.PrimaryKeyConstraint('knowledge_base_id', 'datasource_id')
    )
    
    op.create_table('moodledatasourceconfig',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('datasource_id', sa.Uuid(), nullable=False),
    sa.Column('domain', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('token', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.ForeignKeyConstraint(['datasource_id'], ['datasource.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('datasource_id')
    )
    
    op.create_table('nextclouddatasourceconfig',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('datasource_id', sa.Uuid(), nullable=False),
    sa.Column('url', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('username', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('password', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.ForeignKeyConstraint(['datasource_id'], ['datasource.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('datasource_id')
    )
    
    op.create_table('chatbot',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('knowledge_base_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledgebase.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('moodlecourse',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('datasource_config_id', sa.Uuid(), nullable=False),
    sa.Column('moodle_course_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('moodle_course_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('moodle_course_files', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('metadata_last_sync', sa.DateTime(), nullable=True),
    sa.Column('metadata_version', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('content_last_sync', sa.DateTime(), nullable=True),
    sa.Column('content_sync_status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('content_sync_error', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('sections_downloaded', sa.Integer(), nullable=False),
    sa.Column('activities_downloaded', sa.Integer(), nullable=False),
    sa.Column('total_sections', sa.Integer(), nullable=False),
    sa.Column('total_activities', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['datasource_config_id'], ['moodledatasourceconfig.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('datasource_config_id', 'moodle_course_id')
    )
    
    op.create_table('chatsession',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_message_at', sa.DateTime(), nullable=False),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('chatbot_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['chatbot_id'], ['chatbot.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('chatmessage',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('role', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('content', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('tokens_used', sa.Integer(), nullable=True),
    sa.Column('processing_time', sa.Float(), nullable=True),
    sa.Column('error', sa.Boolean(), nullable=False),
    sa.Column('chat_session_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['chat_session_id'], ['chatsession.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chatmessage_role'), 'chatmessage', ['role'], unique=False)
    op.create_index(op.f('ix_moodlecourse_moodle_course_id'), 'moodlecourse', ['moodle_course_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_moodlecourse_moodle_course_id'), table_name='moodlecourse')
    op.drop_index(op.f('ix_chatmessage_role'), table_name='chatmessage')
    op.drop_table('chatmessage')
    op.drop_table('chatsession')
    op.drop_table('moodlecourse')
    op.drop_table('chatbot')
    op.drop_table('nextclouddatasourceconfig')
    op.drop_table('moodledatasourceconfig')
    op.drop_table('knowledgebasedatasourcelink')
    op.drop_table('knowledgebase')
    op.drop_table('datasource')
    op.drop_table('user')