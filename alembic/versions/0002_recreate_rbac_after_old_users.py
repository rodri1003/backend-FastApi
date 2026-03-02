"""
Migración para bases que ya tenían la tabla users antigua.
Elimina tablas en orden y recrea el esquema RBAC completo.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_rbac_recreate"
down_revision: Union[str, None] = "0001_initial_rbac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Eliminar tablas en orden (por FKs). SQL Server 2016+: IF EXISTS
    conn.execute(sa.text("IF OBJECT_ID('dbo.user_roles', 'U') IS NOT NULL DROP TABLE dbo.user_roles"))
    conn.execute(sa.text("IF OBJECT_ID('dbo.user_profiles', 'U') IS NOT NULL DROP TABLE dbo.user_profiles"))
    conn.execute(sa.text("IF OBJECT_ID('dbo.users', 'U') IS NOT NULL DROP TABLE dbo.users"))
    conn.execute(sa.text("IF OBJECT_ID('dbo.roles', 'U') IS NOT NULL DROP TABLE dbo.roles"))
    conn.execute(sa.text("IF OBJECT_ID('dbo.casbin_rule', 'U') IS NOT NULL DROP TABLE dbo.casbin_rule"))

    # Recrear users (sin índice explícito en id; la PK ya lo crea en MSSQL)
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=50), nullable=False, unique=True),
        sa.Column("description", sa.String(length=255), nullable=True),
    )
    op.create_index("uq_roles_name", "roles", ["name"], unique=True)

    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False, unique=True),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("avatar_url", sa.String(length=255), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_user_profiles_id", "user_profiles", ["id"])
    op.create_index("uq_user_profiles_user_id", "user_profiles", ["user_id"], unique=True)

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("role_id", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )

    op.create_table(
        "casbin_rule",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ptype", sa.String(length=255), nullable=True),
        sa.Column("v0", sa.String(length=255), nullable=True),
        sa.Column("v1", sa.String(length=255), nullable=True),
        sa.Column("v2", sa.String(length=255), nullable=True),
        sa.Column("v3", sa.String(length=255), nullable=True),
        sa.Column("v4", sa.String(length=255), nullable=True),
        sa.Column("v5", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_casbin_rule_id", "casbin_rule", ["id"])


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
