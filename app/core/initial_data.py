from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import Role, User, UserProfile, UserRole, PermissionResource
from app.permissions.casbin_enforcer import get_enforcer


def _get_db() -> Session:
    return SessionLocal()


def init_rbac_data() -> None:
    """
    Inicializa datos básicos de RBAC:
    - Roles base
    - Usuario administrador inicial (+ perfil)
    - Asignación de rol admin al usuario inicial
    - Políticas iniciales de Casbin
    """
    db = _get_db()
    try:
        # Roles base
        admin_role = _get_or_create_role(
            db,
            name="admin",
            description="Administrador del sistema",
        )
        editor_role = _get_or_create_role(
            db,
            name="editor",
            description="Editor de recursos",
        )
        user_role = _get_or_create_role(
            db,
            name="cliente",
            description="Usuario estándar",
        )
        gerente_role = _get_or_create_role(
            db,
            name="gerente",
            description="Gerente de hotel",
        )
        recepcionista_role = _get_or_create_role(
            db,
            name="recepcionista",
            description="Personal de recepción",
        )

        # Usuario administrador inicial
        admin_email = "admin@example.com"
        admin_user = db.query(User).filter(User.email == admin_email).first()
        if not admin_user:
            admin_user = User(
                email=admin_email,
                password_hash=hash_password("Admin123!"),
                is_active=True,
                is_verified=True,
            )
            db.add(admin_user)
            db.flush()

        # Perfil del administrador inicial
        if not admin_user.profile:
            profile = UserProfile(
                user_id=admin_user.id,
                first_name="Super",
                last_name="Admin",
                phone="12345678",
                avatar_url=None,
                date_of_birth=None,
            )
            db.add(profile)

        # Asignar rol admin al usuario inicial
        if not (
            db.query(UserRole)
            .filter(
                UserRole.user_id == admin_user.id,
                UserRole.role_id == admin_role.id,
            )
            .first()
        ):
            db.add(
                UserRole(
                    user_id=admin_user.id,
                    role_id=admin_role.id,
                )
            )

        # Inicializar recursos de permisos estándar
        resources = ["users", "rooms", "reservations", "roles", "permissions", "audit_logs", "payments", "settings", "incidentals"]
        for res_name in resources:
            if not db.query(PermissionResource).filter(PermissionResource.name == res_name).first():
                db.add(PermissionResource(name=res_name))

        db.commit()

        # Políticas Casbin iniciales
        _init_casbin_policies()
    finally:
        db.close()


def _get_or_create_role(db: Session, name: str, description: str) -> Role:
    role = db.query(Role).filter(Role.name == name).first()
    if role:
        return role

    role = Role(name=name, description=description)
    db.add(role)
    db.flush()
    return role


def _init_casbin_policies() -> None:
    """
    Crea políticas iniciales de Casbin de forma idempotente

    - admin: acceso total a todos los recursos/acciones
    """
    enforcer = get_enforcer()

    # admin -> * / *
    if not enforcer.has_policy("admin", "*", "*"):
        enforcer.add_policy("admin", "*", "*")

    # gerente -> incidentals:create, incidentals:read, incidentals:update
    for action in ["create", "read", "update"]:
        if not enforcer.has_policy("gerente", "incidentals", action):
            enforcer.add_policy("gerente", "incidentals", action)

    # recepcionista -> incidentals:create, incidentals:read
    for action in ["create", "read"]:
        if not enforcer.has_policy("recepcionista", "incidentals", action):
            enforcer.add_policy("recepcionista", "incidentals", action)

    enforcer.save_policy()

