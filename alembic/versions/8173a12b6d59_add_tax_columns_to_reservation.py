"""Add tax columns to reservation

Revision ID: 8173a12b6d59
Revises: d817c83cbad6
Create Date: 2026-04-27 15:34:58.992103

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql

# revision identifiers, used by Alembic.
revision = '8173a12b6d59'
down_revision = 'd817c83cbad6'
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
        ("subtotal", sa.Numeric(precision=10, scale=2)),
        ("tax_iva", sa.Numeric(precision=10, scale=2)),
        ("tax_tourism", sa.Numeric(precision=10, scale=2)),
    ]:
        if not _column_exists("reservations", col_name):
            op.add_column("reservations", sa.Column(col_name, col_type, nullable=True))


def downgrade() -> None:
    op.drop_column('reservations', 'tax_tourism')
    op.drop_column('reservations', 'tax_iva')
    op.drop_column('reservations', 'subtotal')

