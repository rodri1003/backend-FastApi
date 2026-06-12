from __future__ import annotations

from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db.session import Base, DATABASE_URL
from app.models import audit as audit_models
from app.models import user as user_models
from app.models import room as room_models
from app.models import reservation as reservation_models
from app.models import payment as payment_models
from app.models import room_type as room_type_models
from app.models import notification as notification_models
from app.models import extra_amenity as extra_amenity_models  # Amenidades extras con costo
from app.models import amenity as amenity_models
from app.models import incidental_charge as incidental_charge_models
from app.models import system_setting as system_setting_models


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = str(DATABASE_URL)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": str(DATABASE_URL)},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

