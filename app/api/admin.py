"""
API administrativa: usuarios, roles, permisos (Casbin) y bitácora.
Acceso mediante permisos granulares (users:read, roles:create, etc.).
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User, Role, UserRole
from app.models.audit import AuditLog
from app.schemas.user import UserRead, UserCreateAdmin, UserUpdateAdmin, RoleRead, RoleCreate, RoleUpdate
from app.schemas.admin import PolicyRead, PolicyCreate, AuditLogRead
from app.permissions.deps import require_permission
from app.services.user_service import create_user_admin, update_user_admin
from app.services.audit_service import log_action
from app.permissions.casbin_enforcer import get_enforcer

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/ping", dependencies=[Depends(require_permission("admin", "read"))])
def admin_ping(current_user: User = Depends(get_current_user)):
    return {"message": "Acceso admin OK", "user": current_user.email}


# ----- Usuarios -----


@router.get("/users", response_model=list[UserRead], dependencies=[Depends(require_permission("users", "read"))])
def list_users(
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    users = (
        db.query(User)
        .options(selectinload(User.roles), selectinload(User.profile))
        .order_by(User.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return users


@router.post("/users", response_model=UserRead, status_code=201, dependencies=[Depends(require_permission("users", "create"))])
def create_user(
    user_in: UserCreateAdmin,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = create_user_admin(db, user_in)
    log_action(
        db, user_id=current_user.id, resource="users", action="create",
        method="POST", path="/admin/users", status_code=201, request=request,
        metadata={"created_user_id": user.id, "email": user.email},
    )
    return user


@router.patch("/users/{user_id}", response_model=UserRead, dependencies=[Depends(require_permission("users", "update"))])
def update_user(
    user_id: int,
    data: UserUpdateAdmin,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = update_user_admin(db, user_id, data, current_user_id=current_user.id)
    log_action(
        db, user_id=current_user.id, resource="users", action="update",
        method="PATCH", path=f"/admin/users/{user_id}", status_code=200, request=request,
        metadata={"updated_user_id": user_id},
    )
    return user


@router.delete("/users/{user_id}", status_code=204, dependencies=[Depends(require_permission("users", "delete"))])
def deactivate_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="No puedes desactivar tu propia cuenta.",
        )
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    u.is_active = False
    db.commit()
    log_action(
        db, user_id=current_user.id, resource="users", action="deactivate",
        method="DELETE", path=f"/admin/users/{user_id}", status_code=204, request=request,
        metadata={"deactivated_user_id": user_id},
    )
    return None


# ----- Roles -----


@router.get("/roles", response_model=list[RoleRead], dependencies=[Depends(require_permission("roles", "read"))])
def list_roles(db: Session = Depends(get_db)):
    return db.query(Role).all()


@router.post("/roles", response_model=RoleRead, status_code=201, dependencies=[Depends(require_permission("roles", "create"))])
def create_role(
    data: RoleCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(Role).filter(Role.name == data.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Ya existe un rol con ese nombre.")
    role = Role(name=data.name, description=data.description)
    db.add(role)
    db.commit()
    db.refresh(role)
    log_action(
        db, user_id=current_user.id, resource="roles", action="create",
        method="POST", path="/admin/roles", status_code=201, request=request,
        metadata={"role_id": role.id, "name": role.name},
    )
    return role


@router.patch("/roles/{role_id}", response_model=RoleRead, dependencies=[Depends(require_permission("roles", "update"))])
def update_role(
    role_id: int,
    data: RoleUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Rol no encontrado")
    if data.name is not None:
        other = db.query(Role).filter(Role.name == data.name, Role.id != role_id).first()
        if other:
            raise HTTPException(status_code=409, detail="Ya existe un rol con ese nombre.")
        role.name = data.name
    if data.description is not None:
        role.description = data.description
    db.commit()
    db.refresh(role)
    log_action(
        db, user_id=current_user.id, resource="roles", action="update",
        method="PATCH", path=f"/admin/roles/{role_id}", status_code=200, request=request,
        metadata={"role_id": role_id},
    )
    return role


@router.delete("/roles/{role_id}", status_code=204, dependencies=[Depends(require_permission("roles", "delete"))])
def delete_role(
    role_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Rol no encontrado")
    count = db.query(UserRole).filter(UserRole.role_id == role_id).count()
    if count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"No se puede eliminar: {count} usuario(s) tienen asignado este rol.",
        )
    db.delete(role)
    db.commit()
    log_action(
        db, user_id=current_user.id, resource="roles", action="delete",
        method="DELETE", path=f"/admin/roles/{role_id}", status_code=204, request=request,
        metadata={"role_id": role_id, "name": role.name},
    )
    return None


# ----- Permisos (Casbin) -----

from app.permissions.utils import RESOURCES as PERM_RESOURCES, ACTIONS as PERM_ACTIONS


@router.get(
    "/permissions/metadata",
    response_model=dict,
    dependencies=[Depends(require_permission("permissions", "read"))],
)
def get_permissions_metadata():
    """
    Devuelve recursos y acciones válidos para políticas (fuente única en backend).
    Incluye '*' para políticas wildcard en Casbin.
    """
    return {
        "resources": [*PERM_RESOURCES, "*"],
        "actions": [*PERM_ACTIONS, "*"],
    }


@router.get("/permissions", response_model=list[PolicyRead], dependencies=[Depends(require_permission("permissions", "read"))])
def list_permissions(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    enforcer = get_enforcer()
    policies = enforcer.get_policy()
    slice_ = policies[offset : offset + limit]
    return [PolicyRead(sub=p[0], obj=p[1], act=p[2]) for p in slice_]


@router.post("/permissions", response_model=PolicyRead, status_code=201, dependencies=[Depends(require_permission("permissions", "create"))])
def add_permission(
    data: PolicyCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforcer = get_enforcer()
    if enforcer.has_policy(data.sub, data.obj, data.act):
        raise HTTPException(status_code=409, detail="La política ya existe.")
    enforcer.add_policy(data.sub, data.obj, data.act)
    enforcer.save_policy()
    log_action(
        db, user_id=current_user.id, resource="permissions", action="create",
        method="POST", path="/admin/permissions", status_code=201, request=request,
        metadata={"sub": data.sub, "obj": data.obj, "act": data.act},
    )
    return PolicyRead(sub=data.sub, obj=data.obj, act=data.act)


@router.delete("/permissions", status_code=204, dependencies=[Depends(require_permission("permissions", "delete"))])
def remove_permission(
    request: Request,
    sub: str = Query(...), obj: str = Query(...), act: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.name == sub).first()
    if role:
        user_ids_with_role = [ur.user_id for ur in db.query(UserRole).filter(UserRole.role_id == role.id).all()]
        if len(user_ids_with_role) == 1 and user_ids_with_role[0] == current_user.id:
            raise HTTPException(
                status_code=400,
                detail="No puedes eliminar políticas del único rol con el que cuentas.",
            )
    enforcer = get_enforcer()
    if not enforcer.has_policy(sub, obj, act):
        raise HTTPException(status_code=404, detail="Política no encontrada.")
    enforcer.remove_policy(sub, obj, act)
    enforcer.save_policy()
    log_action(
        db, user_id=current_user.id, resource="permissions", action="delete",
        method="DELETE", path="/admin/permissions", status_code=204, request=request,
        metadata={"sub": sub, "obj": obj, "act": act},
    )
    return None


# ----- Bitácora -----


@router.get("/audit-logs", response_model=list[AuditLogRead], dependencies=[Depends(require_permission("audit_logs", "read"))])
def list_audit_logs(
    db: Session = Depends(get_db),
    event_type: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    limit: int = Query(default=100, le=500, ge=1),
    offset: int = Query(default=0, ge=0),
):
    q = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if event_type:
        q = q.filter(AuditLog.event_type == event_type)
    if user_id is not None:
        q = q.filter(AuditLog.user_id == user_id)
    return q.offset(offset).limit(limit).all()
