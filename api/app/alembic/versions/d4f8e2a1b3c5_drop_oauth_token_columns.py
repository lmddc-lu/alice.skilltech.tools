"""Drop unused OAuth provider token columns

Revision ID: d4f8e2a1b3c5
Revises: b4e7f1a2c390
Create Date: 2026-04-07 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d4f8e2a1b3c5"
down_revision = "b4e7f1a2c390"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("oauthsession", "access_token")
    op.drop_column("oauthsession", "refresh_token")
    op.drop_column("oauthsession", "id_token")


def downgrade():
    op.add_column("oauthsession", sa.Column("access_token", sa.String(), nullable=True))
    op.add_column("oauthsession", sa.Column("refresh_token", sa.String(), nullable=True))
    op.add_column("oauthsession", sa.Column("id_token", sa.String(), nullable=True))
