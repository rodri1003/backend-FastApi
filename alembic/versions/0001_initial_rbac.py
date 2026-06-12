from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_initial_rbac"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    """Check if a table already exists in the database (SQL Server)."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME = :tbl"
        ),
        {"tbl": table_name},
    )
    return result.scalar() > 0


def _index_exists(index_name: str) -> bool:
    """Check if an index already exists in the database (SQL Server)."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT COUNT(*) FROM sys.indexes WHERE name = :idx"),
        {"idx": index_name},
    )
    return result.scalar() > 0


def _create_index_safe(name: str, table: str, columns: list, **kwargs):
    """Create an index only if it does not already exist."""
    if not _index_exists(name):
        op.create_index(name, table, columns, **kwargs)


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────
    if not _table_exists("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("email", sa.String(length=100), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column(
                "is_active", sa.Boolean, nullable=False, server_default=sa.text("1")
            ),
            sa.Column(
                "is_verified",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("email", name="uq_users_email"),
        )
    _create_index_safe("ix_users_email", "users", ["email"])

    # ── roles ──────────────────────────────────────────────
    if not _table_exists("roles"):
        op.create_table(
            "roles",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(length=50), nullable=False, unique=True),
            sa.Column("description", sa.String(length=255), nullable=True),
        )
    _create_index_safe("uq_roles_name", "roles", ["name"], unique=True)

    # ── user_profiles ──────────────────────────────────────
    if not _table_exists("user_profiles"):
        op.create_table(
            "user_profiles",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.Integer, nullable=False, unique=True),
            sa.Column("first_name", sa.String(length=100), nullable=False),
            sa.Column("last_name", sa.String(length=100), nullable=False),
            sa.Column("phone", sa.String(length=50), nullable=True),
            sa.Column("avatar_url", sa.String(length=255), nullable=True),
            sa.Column("date_of_birth", sa.Date(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                ondelete="CASCADE",
            ),
        )
    _create_index_safe("ix_user_profiles_id", "user_profiles", ["id"])
    _create_index_safe(
        "uq_user_profiles_user_id", "user_profiles", ["user_id"], unique=True
    )

    # ── user_roles ─────────────────────────────────────────
    if not _table_exists("user_roles"):
        op.create_table(
            "user_roles",
            sa.Column("user_id", sa.Integer, nullable=False),
            sa.Column("role_id", sa.Integer, nullable=False),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["role_id"],
                ["roles.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("user_id", "role_id"),
        )

    # ── casbin_rule ────────────────────────────────────────
    if not _table_exists("casbin_rule"):
        op.create_table(
            "casbin_rule",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("ptype", sa.String(length=255), nullable=True),
            sa.Column("v0", sa.String(length=255), nullable=True),
            sa.Column("v1", sa.String(length=255), nullable=True),
            sa.Column("v2", sa.String(length=255), nullable=True),
            sa.Column("v3", sa.String(length=255), nullable=True),
            sa.Column("v4", sa.String(length=255), nullable=True),
            sa.Column("v5", sa.String(length=255), nullable=True),
        )
    _create_index_safe("ix_casbin_rule_id", "casbin_rule", ["id"])


def downgrade() -> None:
    op.drop_index("ix_casbin_rule_id", table_name="casbin_rule")
    op.drop_table("casbin_rule")

    op.drop_table("user_roles")

    op.drop_index("uq_user_profiles_user_id", table_name="user_profiles")
    op.drop_index("ix_user_profiles_id", table_name="user_profiles")
    op.drop_table("user_profiles")

    op.drop_index("uq_roles_name", table_name="roles")
    op.drop_table("roles")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

