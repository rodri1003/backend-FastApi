# Main application entry point
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
from app.core.initial_data import init_rbac_data
from app.core.cloudinary import init_cloudinary

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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

@app.on_event("startup")
def on_startup() -> None:
    init_rbac_data()
    init_cloudinary()


app.include_router(users_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(rooms_router)
app.include_router(reservations_router)
app.include_router(payments_router)
app.include_router(webhooks_router)


@app.get("/")
def root():
    return {"message": "Backend funcionando correctamente"}
