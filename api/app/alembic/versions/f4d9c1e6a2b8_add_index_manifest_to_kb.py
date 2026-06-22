"""Add index_manifest to knowledgebase

Records the embedding/index config a Qdrant collection was built with so the API
can detect index drift (embedding model swap, dim change, sparse toggle) before
querying a stale collection.

Existing rows are intentionally left NULL. 
Revision ID: f4d9c1e6a2b8
Revises: d2f4a6b8c013
Create Date: 2026-06-12 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f4d9c1e6a2b8"
down_revision = "d2f4a6b8c013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "knowledgebase",
        sa.Column("index_manifest", sa.String(), nullable=True),
    )


def downgrade():
    op.drop_column("knowledgebase", "index_manifest")
