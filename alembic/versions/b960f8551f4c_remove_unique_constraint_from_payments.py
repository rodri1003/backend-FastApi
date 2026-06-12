"""remove_unique_constraint_from_payments

Revision ID: b960f8551f4c
Revises: c832835c906d
Create Date: 2026-06-12 00:28:09.327540

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b960f8551f4c'
down_revision = 'c832835c906d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQL Server specific dynamic drop of unique constraint/index on payments(reservation_id)
    op.execute("""
        -- 1. Check and drop Unique Constraint
        DECLARE @constraint_name NVARCHAR(256);
        SELECT @constraint_name = c.name
        FROM sys.key_constraints c
        INNER JOIN sys.index_columns ic ON c.parent_object_id = ic.object_id AND c.unique_index_id = ic.index_id
        INNER JOIN sys.columns col ON ic.object_id = col.object_id AND ic.column_id = col.column_id
        WHERE c.parent_object_id = OBJECT_ID('payments')
          AND col.name = 'reservation_id'
          AND c.type = 'UQ';

        IF @constraint_name IS NOT NULL
        BEGIN
            EXEC('ALTER TABLE [payments] DROP CONSTRAINT [' + @constraint_name + ']');
        END

        -- 2. Check and drop Unique Index (just in case)
        DECLARE @index_name NVARCHAR(256);
        SELECT @index_name = i.name
        FROM sys.indexes i
        INNER JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
        INNER JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
        WHERE i.object_id = OBJECT_ID('payments')
          AND c.name = 'reservation_id'
          AND i.is_unique = 1
          AND i.is_primary_key = 0;

        IF @index_name IS NOT NULL
        BEGIN
            EXEC('DROP INDEX [' + @index_name + '] ON [payments]');
        END
    """)


def downgrade() -> None:
    op.create_unique_constraint('uq_payments_reservation_id', 'payments', ['reservation_id'])

