"""Add DTE fields to UserProfile

Revision ID: 2d2a5d54df8d
Revises: 5797ef78ebc7
Create Date: 2026-04-23 10:41:57.722456

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql

# revision identifiers, used by Alembic.
revision = '2d2a5d54df8d'
down_revision = '5797ef78ebc7'
branch_labels = None
depends_on = None

def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = :tbl AND COLUMN_NAME = :col"
        ),
        {"tbl": table_name, "col": column_name},
    )
    return result.scalar() > 0


def upgrade() -> None:
    for col_name, col_type in [
        ("person_type", sa.String(length=20)),
        ("nrc", sa.String(length=50)),
        ("dui", sa.String(length=20)),
        ("nit", sa.String(length=20)),
        ("economic_activity", sa.String(length=255)),
        ("taxpayer_type", sa.String(length=50)),
    ]:
        if not _column_exists("user_profiles", col_name):
            op.add_column("user_profiles", sa.Column(col_name, col_type, nullable=True))


def downgrade() -> None:
    op.drop_column('user_profiles', 'taxpayer_type')
    op.drop_column('user_profiles', 'economic_activity')
    op.drop_column('user_profiles', 'nit')
    op.drop_column('user_profiles', 'dui')
    op.drop_column('user_profiles', 'nrc')
    op.drop_column('user_profiles', 'person_type')

