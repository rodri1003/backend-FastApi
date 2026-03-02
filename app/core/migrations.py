"""
Ejecuta las migraciones de Alembic al arranque para asegurar
que las tablas existan antes del seed.
"""
from __future__ import annotations

import logging
import os

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)


def run_migrations() -> None:
    """Ejecuta alembic upgrade head de forma programática."""
    # Raíz del proyecto (donde está alembic.ini)
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    alembic_ini_path = os.path.join(base_dir, "alembic.ini")
    script_location = os.path.join(base_dir, "alembic")

    config = Config(alembic_ini_path)
    config.set_main_option("script_location", script_location)
    command.upgrade(config, "head")
    logger.info("Migraciones Alembic aplicadas correctamente.")
