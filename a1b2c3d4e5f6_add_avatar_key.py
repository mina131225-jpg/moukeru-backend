"""add avatar_key to user_profiles

Revision ID: a1b2c3d4e5f6
Revises: 88a92776c82b
Create Date: 2026-04-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '88a92776c82b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add avatar_key column to user_profiles if it doesn't exist
    # Using raw SQL with IF NOT EXISTS to be safe on re-runs
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'user_profiles' AND column_name = 'avatar_key'
            ) THEN
                ALTER TABLE user_profiles ADD COLUMN avatar_key VARCHAR;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_profiles', 'avatar_key')