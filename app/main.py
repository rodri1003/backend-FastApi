# Main application entry point
import os
os.environ["PYTHONHTTPSVERIFY"] = "0"

from app.core.ssl_patch import apply_ssl_patch
apply_ssl_patch()

# Patch urllib3 SSL verification for local environment (helps Cloudinary and proxy trust)
try:
    import ssl
    import urllib3
    import urllib3.util.ssl_
    import urllib3.connection
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # 1. Patch create_urllib3_context
    original_create_urllib3_context = urllib3.util.ssl_.create_urllib3_context
    def patched_create_urllib3_context(*args, **kwargs):
        kwargs['cert_reqs'] = ssl.CERT_NONE
        return original_create_urllib3_context(*args, **kwargs)
    urllib3.util.ssl_.create_urllib3_context = patched_create_urllib3_context
    urllib3.util.create_urllib3_context = patched_create_urllib3_context

    # 2. Patch ssl_wrap_socket to bypass proxy SSL inspection issues
    original_ssl_wrap_socket = urllib3.util.ssl_.ssl_wrap_socket
    def patched_ssl_wrap_socket(*args, **kwargs):
        kwargs['cert_reqs'] = ssl.CERT_NONE
        if 'ssl_context' in kwargs and kwargs['ssl_context'] is not None:
            try:
                kwargs['ssl_context'].check_hostname = False
                kwargs['ssl_context'].verify_mode = ssl.CERT_NONE
            except Exception:
                pass
        return original_ssl_wrap_socket(*args, **kwargs)
    urllib3.util.ssl_.ssl_wrap_socket = patched_ssl_wrap_socket

    # 3. Patch urllib3.connection.HTTPSConnection.connect (essential for urllib3 2.x)
    original_connect = urllib3.connection.HTTPSConnection.connect
    def patched_connect(self, *args, **kwargs):
        if hasattr(self, 'ssl_context') and self.ssl_context is not None:
            try:
                self.ssl_context.check_hostname = False
                self.ssl_context.verify_mode = ssl.CERT_NONE
            except Exception:
                pass
        if hasattr(self, 'cert_reqs'):
            self.cert_reqs = ssl.CERT_NONE
        return original_connect(self, *args, **kwargs)
    urllib3.connection.HTTPSConnection.connect = patched_connect
except Exception as e:
    print(f"[SSL Patch Warning] Failed to patch urllib3: {e}")


from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.users import router as users_router
from app.api.auth import router as auth_router
from app.api.admin import router as admin_router
from app.api.rooms import router as rooms_router
from app.api.reservations import router as reservations_router
from app.api.payments import router as payments_router
from app.api.webhooks import router as webhooks_router
from app.api.notifications import router as notifications_router
from app.api.reports import router as reports_router
from app.api.settings import router as settings_router
from app.core.initial_data import init_rbac_data
from app.core.cloudinary import init_cloudinary

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "https://keyless-accessarily-quintin.ngrok-free.dev"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        loc = error.get("loc", [])
        field = loc[-1] if loc else "campo"
        msg = error.get("msg", "")
        type_err = error.get("type", "")

        # Traducciones comunes de Pydantic
        if "string_too_short" in type_err:
            limit = error.get("ctx", {}).get("min_length")
            friendly_msg = f"El campo '{field}' debe tener al menos {limit} caracteres."
        elif "less_than_equal" in type_err:
            limit = error.get("ctx", {}).get("le") or error.get("ctx", {}).get("lt")
            friendly_msg = f"El valor de '{field}' debe ser menor o igual a {limit}."
        elif "greater_than" in type_err:
            ctx = error.get("ctx", {})
            limit = ctx.get("gt") if ctx.get("gt") is not None else ctx.get("ge")
            friendly_msg = f"El valor de '{field}' debe ser mayor a {limit}."
        elif "value_error.email" in type_err or "assertion_error" in type_err:
            friendly_msg = msg # Ya suele venir traducido por nosotros o ser descriptivo
        else:
            friendly_msg = msg

        errors.append(friendly_msg)

    return JSONResponse(
        status_code=422,
        content={"detail": errors[0] if errors else "Error de validación"},
    )

from app.services.reservation_service import auto_cancel_expired_reservations, auto_send_checkin_reminders
from app.services.notification_service import auto_cleanup_old_notifications
from app.services.system_settings_service import seed_defaults
from app.db.session import SessionLocal
import asyncio

@app.on_event("startup")
def on_startup() -> None:
    init_rbac_data()
    init_cloudinary()
    
    # Ejecutar migración física de la tabla si no existe
    from app.db.session import engine
    from sqlalchemy import text
    import os
    
    base_dir = os.path.dirname(os.path.dirname(__file__))
    sql_path = os.path.join(base_dir, "scripts", "migrate_system_settings.sql")
    if os.path.exists(sql_path):
        try:
            with open(sql_path, "r", encoding="utf-8") as f:
                sql_content = f.read()
            with engine.begin() as connection:
                connection.execute(text(sql_content))
            print("[Migration] system_settings table initialized successfully in SQL Server.")
        except Exception as e:
            print(f"[Migration Error] Failed to run migrate_system_settings.sql automatically: {e}")
    else:
        print(f"[Migration Warning] Migration file not found at {sql_path}")
    
    # Migración de cargos incidentales
    inc_sql_path = os.path.join(base_dir, "scripts", "migrate_incidental_charges.sql")
    if os.path.exists(inc_sql_path):
        try:
            with open(inc_sql_path, "r", encoding="utf-8") as f:
                sql_content = f.read()
            # Ejecutar cada bloque separado por GO
            with engine.begin() as connection:
                for block in sql_content.split("GO"):
                    block = block.strip()
                    if block:
                        connection.execute(text(block))
            print("[Migration] incidental_charges tables initialized successfully in SQL Server.")
        except Exception as e:
            print(f"[Migration Error] Failed to run migrate_incidental_charges.sql: {e}")
    else:
        print(f"[Migration Warning] incidental charges migration file not found at {inc_sql_path}")
        
    # Sembrar configuraciones por defecto
    db = SessionLocal()
    try:
        seed_defaults(db)
    finally:
        db.close()
        
    asyncio.create_task(auto_cancel_expired_reservations())
    asyncio.create_task(auto_send_checkin_reminders())
    asyncio.create_task(auto_cleanup_old_notifications())


app.include_router(users_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(rooms_router)
app.include_router(reservations_router)
app.include_router(payments_router)
app.include_router(webhooks_router)
app.include_router(notifications_router)
app.include_router(reports_router)
app.include_router(settings_router)


@app.get("/")
def root():
    return {"message": "Backend funcionando correctamente"}
