from __future__ import annotations

import os
from functools import lru_cache

import casbin
from casbin_sqlalchemy_adapter import Adapter

from app.db.session import DATABASE_URL


@lru_cache
def get_enforcer() -> casbin.Enforcer:
    """
    Devuelve una instancia singleton de Enforcer de Casbin.
    """
    base_dir = os.path.dirname(__file__)
    model_path = os.path.join(base_dir, "model.conf")

    adapter = Adapter(str(DATABASE_URL))
    enforcer = casbin.Enforcer(model_path, adapter)
    enforcer.load_policy()
    return enforcer

