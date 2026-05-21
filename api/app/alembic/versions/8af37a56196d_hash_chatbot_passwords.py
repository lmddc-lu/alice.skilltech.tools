"""Hash chatbot passwords

Revision ID: 8af37a56196d
Revises: f2359fb94ff2
Create Date: 2026-01-09

"""
from alembic import op
import sqlalchemy as sa
from passlib.context import CryptContext


# revision identifiers, used by Alembic.
revision = '8af37a56196d'
down_revision = 'f2359fb94ff2'
branch_labels = None
depends_on = None

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def upgrade():
    connection = op.get_bind()

    # hash any plaintext passwords (skip rows already bcrypt-prefixed)
    result = connection.execute(
        sa.text(
            "SELECT id, password FROM chatbot "
            "WHERE password IS NOT NULL "
            "AND password NOT LIKE '$2b$%' "
            "AND password NOT LIKE '$2a$%' "
            "AND password NOT LIKE '$2y$%'"
        )
    )

    for row in result:
        chatbot_id = row[0]
        plaintext_password = row[1]
        hashed_password = pwd_context.hash(plaintext_password)
        connection.execute(
            sa.text("UPDATE chatbot SET password = :hash WHERE id = :id"),
            {"hash": hashed_password, "id": chatbot_id}
        )

    op.alter_column('chatbot', 'password', new_column_name='password_hash')


def downgrade():
    # passwords stay hashed; this only renames the column
    op.alter_column('chatbot', 'password_hash', new_column_name='password')
